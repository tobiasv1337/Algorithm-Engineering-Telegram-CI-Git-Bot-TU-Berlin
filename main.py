import time
import signal
from config.config import Config
from git_manager.git_operations import (get_commit_message, load_last_commits, save_last_commits, fetch_all_branches, get_latest_commit, reset_to_commit, load_config_from_commit, get_tracked_branches, perform_auto_merge)
from api.oioioi import OioioiAPI
from api.telegram import TelegramBot
from utils.file_operations import create_zip_files
from utils.system import handle_shutdown_signal, shutdown_flag
from handlers.compilation_manager import check_for_compiler_errors

def process_commit(branch, current_commit, config, oioioi_api, telegram_bot):
    """
    Process a new commit: validate, compile, submit, and handle results.
    """
    # Reset to the specific commit
    reset_to_commit(current_commit)

    # Check for compiler errors
    if not check_for_compiler_errors(config):
        message = (
            f"\u274c *Compilation Failed*\n"
            f"\u2022 *Branch*: `{branch}`\n"
            f"\u2022 *Commit Hash*: `{current_commit}`\n"
            f"\u2022 *Warnings Allowed*: {config.get('ALLOW_WARNINGS', False)}\n"
            f"\u2022 *Errors Allowed*: {config.get('ALLOW_ERRORS', False)}"
        )
        print(message)
        telegram_bot.send_message(message)
        return False

    # Create ZIP files for submission
    zip_files, temp_dir = create_zip_files(config)
    try:
        # Submit the solution
        submission_id = oioioi_api.submit_solution(
            config["contest_id"], config["problem_short_name"], zip_files, branch, telegram_bot
        )
        if submission_id:
            oioioi_api.wait_for_results(config["contest_id"], submission_id, telegram_bot)

            # Handle auto-merge
            if branch == config.get("auto_merge_branch"):
                grouped_results = oioioi_api.fetch_test_results(config["contest_id"], submission_id)
                if grouped_results and not any(
                    "error" in test["result"].lower()
                    for group in grouped_results.values()
                    for test in group["tests"]
                ):
                    perform_auto_merge(branch, grouped_results, current_commit, telegram_bot)
                else:
                    telegram_bot.send_message(
                        f"⚠️ *Auto-Merge Skipped*\n"
                        f"Branch `{branch}` was not merged into `{Config.PRIMARY_BRANCH}` due to test failures."
                    )
    finally:
        temp_dir.cleanup()
    return True

def process_branch(branch, last_commit_per_branch, oioioi_api, telegram_bot):
    """
    Process a branch: check for new commits and handle them.
    """
    current_commit = get_latest_commit(branch)
    if current_commit is None or current_commit == last_commit_per_branch.get(branch):
        return  # No new commit or branch does not exist

    # Save the current commit to avoid reprocessing
    last_commit_per_branch[branch] = current_commit
    save_last_commits(last_commit_per_branch)

    # Notify about the new commit
    commit_message = get_commit_message(current_commit)
    telegram_bot.send_message(
        f"\ud83d\udea8 *New Commit Detected*\n"
        f"\u2022 *Branch*: `{branch}`\n"
        f"\u2022 *Commit Hash*: `{current_commit}`\n"
        f"\u2022 *Message*: {commit_message}\n"
    )

    # Load the config for the commit
    config = load_config_from_commit(current_commit)
    if not config or not config.get("AUTOCOMMIT", False):
        message = (
            f"\u26a0\ufe0f *Skipping Submission*\n"
            f"\u2022 *Reason*: AUTOCOMMIT is disabled or config is missing.\n"
            f"\u2022 *Branch*: `{branch}`\n"
            f"\u2022 *Commit Hash*: `{current_commit}`"
        )
        print(message)
        telegram_bot.send_message(message)
        return

    # Process the commit
    process_commit(branch, current_commit, config, oioioi_api, telegram_bot)

def main():
    global shutdown_flag
    last_commit_per_branch = load_last_commits()

    oioioi_api = OioioiAPI(Config.OIOIOI_BASE_URL, Config.OIOIOI_USERNAME, Config.OIOIOI_PASSWORD)
    oioioi_api.login()

    telegram_bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN, Config.TELEGRAM_CHAT_IDS)

    while not shutdown_flag:
        fetch_all_branches()
        branches_to_check = get_tracked_branches()

        for branch in branches_to_check:
            process_branch(branch, last_commit_per_branch, oioioi_api, telegram_bot)

        time.sleep(Config.CHECK_INTERVAL)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)  # Ctrl+C
    signal.signal(signal.SIGTERM, handle_shutdown_signal)  # Termination signal

    print("Starting script. Press Ctrl+C to stop.")
    main()