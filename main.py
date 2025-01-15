import os
import time
import json
import signal
import subprocess
import tempfile
from bs4 import BeautifulSoup
from zipfile import ZipFile
from handlers import LANGUAGE_HANDLERS # Import language handlers
from handlers.base_handler import CompilationError
from config.config import Config
from git_manager.git_operations import (fetch_all_branches, get_latest_commit, reset_to_commit, load_config_from_commit, get_tracked_branches)
from api.oioioi import OioioiAPI
from api.telegram import TelegramBot
from utils.file_operations import create_zip_files
from utils.system import handle_shutdown_signal, shutdown_flag

LAST_COMMITS_FILE = "last_commits.json"  # File to store last processed commit for each branch

def load_last_commits():
    """Load the last processed commit hashes from a file."""
    if os.path.exists(LAST_COMMITS_FILE):
        with open(LAST_COMMITS_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_last_commits(last_commit_per_branch):
    """Save the last processed commit hashes to a file."""
    with open(LAST_COMMITS_FILE, 'w') as f:
        json.dump(last_commit_per_branch, f)

last_commit_per_branch = load_last_commits()  # Initialize with saved data if available

def check_for_compiler_errors(config, telegram_bot):
    """
    Run a compilation check for each project specified in the configuration.
    Uses language-specific handlers to process each project in a temporary directory. Handles errors and warnings based on configuration flags.
    Creates ZIP files first, extracts them to temporary directories, and checks each project for compilation errors.
    """
    language = config.get("language")
    if not language:
        message = (
            "❌ *Error*: The language is not specified in the submission configuration.\n"
            "Please specify a language (e.g., 'rust', 'cpp').\n\n"
            f"🛠 Supported languages: {', '.join(LANGUAGE_HANDLERS.keys())}"
        )
        print(message)
        telegram_bot.send_message(message)
        return False

    if language not in LANGUAGE_HANDLERS:
        message = (
            f"❌ *Error*: Unsupported language '{language}'.\n"
            f"🛠 Supported languages are: {', '.join(LANGUAGE_HANDLERS.keys())}.\n\n"
            "💡 If you need support for this language, please contact the bot administrator."
        )
        print(message)
        telegram_bot.send_message(message)
        return False

    handler = LANGUAGE_HANDLERS[language]

    zip_files, temp_dir = create_zip_files(config)
    all_projects_meet_criteria = True

    for zip_file in zip_files:
        with tempfile.TemporaryDirectory() as temp_dir_extract:
            try:
                with ZipFile(zip_file, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir_extract)

                try:
                    result = handler.compile(temp_dir_extract)

                    if result.warnings:
                        warning_message = (
                            f"⚠️ *Warnings Detected in {os.path.basename(zip_file)}*\n\n"
                            f"{result.warnings}"
                        )
                        print(warning_message)
                        telegram_bot.send_message(warning_message)

                        if not config.get("ALLOW_WARNINGS", False):
                            all_projects_meet_criteria = False
                            break

                    print(f"✅ Compilation check completed successfully for {os.path.basename(zip_file)}.")

                except CompilationError as e:
                    error_message = (
                        f"❌ *Compiler Errors Detected in {os.path.basename(zip_file)}*\n\n{str(e)}"
                    )
                    print(error_message)
                    telegram_bot.send_message(error_message)

                    if not config.get("ALLOW_ERRORS", False):
                        all_projects_meet_criteria = False
                        break

            except Exception as e:
                unexpected_error_message = (
                    f"❌ *Unexpected Error During Compilation Check*\n\n"
                    f"Project: `{os.path.basename(zip_file)}`\n"
                    f"Error: {str(e)}"
                )
                print(unexpected_error_message)
                telegram_bot.send_message(unexpected_error_message)
                all_projects_meet_criteria = False
                break

    temp_dir.cleanup()
    return all_projects_meet_criteria

def perform_auto_merge(branch, grouped_results, commit_hash, telegram_bot):
    """
    Automatically merge the specified branch into PRIMARY_BRANCH after successful testing.
    Includes a short summary of test results in the commit message.
    Only performs the merge if there are no conflicts.
    """
    try:
        # Calculate the total number of tests and passed tests
        total_tests = sum(len(group["tests"]) for group in grouped_results.values())
        passed_tests = sum(
            1 for group in grouped_results.values() for test in group["tests"] if test["result"].lower() == "ok"
        )

        # Prepare the test summary for the commit message
        test_summary = f"Tests Passed: {passed_tests}/{total_tests}"

        # Step 1: Fetch the latest changes for the submit branch to ensure it's up to date
        fetch_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "fetch", "origin", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if fetch_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to fetch the latest changes for `{branch}`. Merge aborted.\n"
                f"Details:\n```\n{fetch_result.stderr.strip()}\n```"
            )
            return

        # Step 2: Reset the submit branch to the specific commit hash
        reset_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "checkout", "-B", branch, commit_hash],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if reset_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to reset branch `{branch}` to commit `{commit_hash}`. Merge aborted.\n"
                f"Details:\n```\n{reset_result.stderr.strip()}\n```"
            )
            return

        # Step 3: Checkout the PRIMARY_BRANCH branch
        subprocess.run(["git", "-C", Config.REPO_PATH, "checkout", Config.PRIMARY_BRANCH], check=True)

        # Step 4: Pull the latest changes from the remote to ensure the local branch is up-to-date
        pull_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "pull", "origin", Config.PRIMARY_BRANCH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if pull_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Auto-Merge Failed*\n"
                f"Failed to pull the latest changes for `{Config.PRIMARY_BRANCH}`. Merge aborted.\n"
                f"Details:\n```\n{pull_result.stderr.strip()}\n```"
            )
            return

        # Step 5: Merge the target branch into PRIMARY_BRANCH with --no-commit and --no-ff to detect conflicts
        merge_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "merge", "--no-commit", "--no-ff", branch],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Check for conflicts
        if "CONFLICT" in merge_result.stderr:
            telegram_bot.send_message(
                f"⚠️ *Merge Conflict Detected*\n"
                f"Branch `{branch}` could not be merged into `{Config.PRIMARY_BRANCH}` due to conflicts.\n"
                f"Details:\n```\n{merge_result.stderr.strip()}\n```"
            )

            # Abort the merge
            subprocess.run(["git", "-C", Config.REPO_PATH, "merge", "--abort"], check=True)
            return

        # Step 6: Commit and complete the merge if no conflicts
        commit_message = f"Merge branch '{branch}' into `{Config.PRIMARY_BRANCH}`\n\n{test_summary}"
        subprocess.run(["git", "-C", Config.REPO_PATH, "commit", "-m", commit_message], check=True)

        # Step 7: Push the merged changes to the remote
        push_result = subprocess.run(
            ["git", "-C", Config.REPO_PATH, "push", "origin", Config.PRIMARY_BRANCH],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if push_result.returncode != 0:
            telegram_bot.send_message(
                f"❌ *Push Failed*\n"
                f"The merged changes for `{Config.PRIMARY_BRANCH}` could not be pushed to the remote.\n"
                f"Details:\n```\n{push_result.stderr.strip()}\n```"
            )
            return

        # Send Telegram notification about success
        telegram_bot.send_message(f"✅ *Auto-Merge Successful*\n"
                              f"Branch `{branch}` was successfully merged into `{Config.PRIMARY_BRANCH}`.\n"
                              f"{test_summary}")
    except subprocess.CalledProcessError as e:
        # Handle unexpected errors during merge and notify via Telegram
        telegram_bot.send_message(f"❌ *Auto-Merge Failed*\n"
                              f"Error during merging branch `{branch}` into `{Config.PRIMARY_BRANCH}`.\n"
                              f"Details: {str(e)}")


def main():
    global shutdown_flag
    global last_commit_per_branch

    oioioi_api = OioioiAPI(Config.OIOIOI_BASE_URL, Config.OIOIOI_USERNAME, Config.OIOIOI_PASSWORD)
    oioioi_api.login()

    telegram_bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_IDS)

    while not shutdown_flag:
        fetch_all_branches()

        # Check branches to track from the PRIMARY_BRANCH configuration
        branches_to_check = get_tracked_branches()

        for branch in branches_to_check:
            current_commit = get_latest_commit(branch)

            # Skip if the branch does not exist on the remote
            if current_commit is None:
                continue

            # Check if there's a new commit on this branch
            if branch not in last_commit_per_branch or current_commit != last_commit_per_branch[branch]:
                commit_message = subprocess.check_output(
                    ["git", "-C", Config.REPO_PATH, "log", "-1", "--pretty=%B", current_commit]
                ).strip().decode('utf-8')

                message = (
                    f"🚨 *New Commit Detected*\n"
                    f"• *Branch*: `{branch}`\n"
                    f"• *Commit Hash*: `{current_commit}`\n"
                    f"• *Message*: {commit_message}\n"
                )
                print(message)
                telegram_bot.send_message(message)

                # Load the config file from this specific commit
                config = load_config_from_commit(current_commit)

                # Skip if config is missing or AUTOCOMMIT is not enabled
                if not config or not config.get("AUTOCOMMIT", False):
                    message = (
                        f"⚠️ *Skipping Submission*\n"
                        f"• *Reason*: AUTOCOMMIT is disabled or config is missing.\n"
                        f"• *Branch*: `{branch}`\n"
                        f"• *Commit Hash*: `{current_commit}`"
                    )
                    print(message)
                    telegram_bot.send_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Reset the repository to the specific commit
                reset_to_commit(current_commit)

                # Check for compiler errors and warnings
                if not check_for_compiler_errors(config):
                    message = (
                        f"❌ *Compilation Failed*\n"
                        f"• *Branch*: `{branch}`\n"
                        f"• *Commit Hash*: `{current_commit}`\n"
                        f"• *Warnings Allowed*: {config.get('ALLOW_WARNINGS', False)}\n"
                        f"• *Errors Allowed*: {config.get('ALLOW_ERRORS', False)}"
                    )
                    print(message)
                    telegram_bot.send_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Create ZIP files based on include paths
                zip_files, temp_dir = create_zip_files(config)

                try:
                    # Submit the solution and retrieve the submission ID
                    submission_id = oioioi_api.submit_solution(config["contest_id"], config["problem_short_name"], zip_files, branch, telegram_bot)
                    if submission_id:
                        oioioi_api.wait_for_results(config["contest_id"], submission_id, telegram_bot)

                        # Check if this branch should trigger an auto-merge
                        if branch == config.get("auto_merge_branch"):
                            grouped_results = oioioi_api.fetch_test_results(config["contest_id"], submission_id)

                            # Ensure all tests passed before merging
                            if grouped_results and not any(
                                "error" in test["result"].lower()
                                for group in grouped_results.values()
                                for test in group["tests"]
                            ):
                                perform_auto_merge(branch, grouped_results, current_commit)
                            else:
                                telegram_bot.send_message(
                                    f"⚠️ *Auto-Merge Skipped*\n"
                                    f"Branch `{branch}` was not merged into `{Config.PRIMARY_BRANCH}` due to test failures."
                                )

                finally:
                    # Ensure the temporary directory is cleaned up
                    temp_dir.cleanup()

                # Update the last processed commit for this branch and save to file
                last_commit_per_branch[branch] = current_commit
                save_last_commits(last_commit_per_branch)

        time.sleep(Config.CHECK_INTERVAL)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)  # Ctrl+C
    signal.signal(signal.SIGTERM, handle_shutdown_signal)  # Termination signal

    print("Starting script. Press Ctrl+C to stop.")
    main()