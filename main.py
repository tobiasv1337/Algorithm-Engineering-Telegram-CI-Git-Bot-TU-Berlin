import os
import time
import json
import re
import signal
import subprocess
import requests
import tempfile
from bs4 import BeautifulSoup
from zipfile import ZipFile
from handlers import LANGUAGE_HANDLERS # Import language handlers
from handlers.base_handler import CompilationError
from config.config import Config
from git_manager.git_operations import (fetch_all_branches, get_latest_commit, reset_to_commit, load_config_from_commit, get_tracked_branches)
from api.oioioi import OioioiAPI

# Global variable to track requested shutdown
shutdown_flag = False

def handle_shutdown_signal(signum, frame):
    """Signal handler to stop the script gracefully."""
    global shutdown_flag
    print(f"\nSignal {signum} received. Shutting down gracefully...")
    shutdown_flag = True

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

def escape_markdown(text, exclude=None):
    """Escape special characters in text for Telegram Markdown while preserving formatting."""
    if exclude is None:
        exclude = set('*')  # Allow bold
    escape_chars = '_*[]()~`>#+-=|{}.!'
    return ''.join(f'\\{char}' if char in escape_chars and char not in exclude else char for char in text)

def send_telegram_message(message, parse_mode="MarkdownV2", disable_web_page_preview=True):
    """
    Send a message to the Telegram group. Automatically splits long messages if needed.
    Splits at newline characters when possible.
    """
    url = f"https://api.telegram.org/bot{Config.TELEGRAM_BOT_TOKEN}/sendMessage"
    max_length = 4096  # Telegram's maximum message length

    def split_message_by_newline(message, max_length):
        """
        Split the message at newline characters, ensuring no part exceeds max_length.
        """
        if len(message) <= max_length:
            return [message]

        parts = []
        current_part = ""

        for line in message.split("\n"):
            # If adding the current line exceeds the limit, finalize the current part
            if len(current_part) + len(line) + 1 > max_length:
                parts.append(current_part.strip())
                current_part = ""

            current_part += line + "\n"

        # Append any remaining text as the last part
        if current_part:
            parts.append(current_part.strip())

        return parts

    # Escape special characters while keeping bold and italic
    escaped_message = escape_markdown(message, exclude={'*'})

    # Split message using the newline-aware function
    split_messages = split_message_by_newline(escaped_message, max_length)

    for chat_id in Config.TELEGRAM_CHAT_IDS:
        # Send each part as a separate Telegram message
        for part in split_messages:
            payload = {
                "chat_id": chat_id,
                "text": part.strip(),
                "parse_mode": parse_mode,  # Pass the parse mode as a parameter
                "disable_web_page_preview": disable_web_page_preview  # Pass link preview toggle
            }
            try:
                response = requests.post(url, data=payload)
                if response.status_code == 200:
                    print("Message sent to Telegram successfully.")
                else:
                    print(f"Failed to send message to Telegram. Status code: {response.status_code}")
                    print(f"Response: {response.text}")
            except Exception as e:
                print(f"Error sending message to Telegram: {e}")

def create_zip_files(config):
    """
    Create multiple ZIP files based on the `zip_files` configuration in the submission config.
    Allows specifying destination paths for files and folders within the ZIP.
    Returns a list of created ZIP file paths and the temporary directory used.
    """
    zip_files = config.get("zip_files", [])
    temp_dir = tempfile.TemporaryDirectory()  # Create a temporary directory for ZIP files
    created_files = []

    for zip_config in zip_files:
        zip_name = zip_config.get("zip_name", "submission.zip")
        include_paths = zip_config.get("include_paths", [])
        zip_path = os.path.join(temp_dir.name, zip_name)  # Place ZIP files in the temp directory

        with ZipFile(zip_path, 'w') as zipf:
            for path_mapping in include_paths:
                source_path = os.path.join(Config.REPO_PATH, os.path.normpath(path_mapping["source"]))
                destination_path = os.path.normpath(path_mapping["destination"])

                # Verify that each path is within the repository and not a symlink
                if not source_path.startswith(Config.REPO_PATH) or os.path.islink(source_path):
                    print(f"Skipping unsafe or invalid path: '{source_path}'")
                    continue

                # If the path is a file, add it directly to the specified destination
                if os.path.isfile(source_path):
                    zipf.write(source_path, destination_path)

                # If the path is a directory, walk through and add all files to the destination folder
                elif os.path.isdir(source_path):
                    for root, _, files in os.walk(source_path):
                        if os.path.islink(root):
                            print(f"Skipping symlinked directory: '{root}'")
                            continue
                        for file in files:
                            file_path = os.path.join(root, file)
                            if not os.path.islink(file_path):
                                # Compute the relative path to preserve folder structure
                                relative_path = os.path.relpath(file_path, source_path)
                                zipf.write(file_path, os.path.join(destination_path, relative_path))
                else:
                    print(f"Warning: Path '{source_path}' not found in the repository.")

        created_files.append(zip_path)

    return created_files, temp_dir

def check_for_compiler_errors(config):
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
        send_telegram_message(message)
        return False

    if language not in LANGUAGE_HANDLERS:
        message = (
            f"❌ *Error*: Unsupported language '{language}'.\n"
            f"🛠 Supported languages are: {', '.join(LANGUAGE_HANDLERS.keys())}.\n\n"
            "💡 If you need support for this language, please contact the bot administrator."
        )
        print(message)
        send_telegram_message(message)
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
                        send_telegram_message(warning_message)

                        if not config.get("ALLOW_WARNINGS", False):
                            all_projects_meet_criteria = False
                            break

                    print(f"✅ Compilation check completed successfully for {os.path.basename(zip_file)}.")

                except CompilationError as e:
                    error_message = (
                        f"❌ *Compiler Errors Detected in {os.path.basename(zip_file)}*\n\n{str(e)}"
                    )
                    print(error_message)
                    send_telegram_message(error_message)

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
                send_telegram_message(unexpected_error_message)
                all_projects_meet_criteria = False
                break

    temp_dir.cleanup()
    return all_projects_meet_criteria

def perform_auto_merge(branch, grouped_results, commit_hash):
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
            send_telegram_message(
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
            send_telegram_message(
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
            send_telegram_message(
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
            send_telegram_message(
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
            send_telegram_message(
                f"❌ *Push Failed*\n"
                f"The merged changes for `{Config.PRIMARY_BRANCH}` could not be pushed to the remote.\n"
                f"Details:\n```\n{push_result.stderr.strip()}\n```"
            )
            return

        # Send Telegram notification about success
        send_telegram_message(f"✅ *Auto-Merge Successful*\n"
                              f"Branch `{branch}` was successfully merged into `{Config.PRIMARY_BRANCH}`.\n"
                              f"{test_summary}")
    except subprocess.CalledProcessError as e:
        # Handle unexpected errors during merge and notify via Telegram
        send_telegram_message(f"❌ *Auto-Merge Failed*\n"
                              f"Error during merging branch `{branch}` into `{Config.PRIMARY_BRANCH}`.\n"
                              f"Details: {str(e)}")


def main():
    global shutdown_flag
    global last_commit_per_branch

    oioioi_api = OioioiAPI(Config.OIOIOI_BASE_URL, Config.OIOIOI_USERNAME, Config.OIOIOI_PASSWORD)
    oioioi_api.login()

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
                send_telegram_message(message)

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
                    send_telegram_message(message)
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
                    send_telegram_message(message)
                    last_commit_per_branch[branch] = current_commit
                    save_last_commits(last_commit_per_branch)
                    continue

                # Create ZIP files based on include paths
                zip_files, temp_dir = create_zip_files(config)

                try:
                    # Submit the solution and retrieve the submission ID
                    submission_id = oioioi_api.submit_solution(config["contest_id"], config["problem_short_name"], zip_files, branch)
                    if submission_id:
                        oioioi_api.wait_for_results(config["contest_id"], submission_id)

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
                                send_telegram_message(
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