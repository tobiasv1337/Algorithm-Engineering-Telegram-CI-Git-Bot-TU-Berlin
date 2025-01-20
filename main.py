import time
import signal
from config.config import Config
from git_manager.git_operations import (get_commit_message, load_last_commit, save_last_commit, fetch_all_branches, get_latest_commit, reset_to_commit, load_config_from_commit, get_tracked_branches)
from api.oioioi import OioioiAPI
from api.telegram import TelegramBot
from utils.file_operations import create_zip_files, load_chat_config, save_chat_config, get_all_chat_configs
from utils.system import handle_shutdown_signal, ShutdownSignal
from handlers.compilation_manager import check_for_compiler_errors


def process_commit(chat_id, branch, current_commit, config, oioioi_api, telegram_bot):
    """
    Process a new commit: validate, compile, submit, and handle results.
    """
    # Reset to the specific commit
    reset_to_commit(chat_id, branch, current_commit)

    # Check for compiler errors
    if not check_for_compiler_errors(config):
        message = (
            f"❌ *Compilation Failed*\n"
            f"• *Branch*: `{branch}`\n"
            f"• *Commit Hash*: `{current_commit}`\n"
            f"• *Warnings Allowed*: {config.get('ALLOW_WARNINGS', False)}\n"
            f"• *Errors Allowed*: {config.get('ALLOW_ERRORS', False)}\n"
            f"Please review the compilation logs for more details."
        )
        print(message)
        telegram_bot.send_message(chat_id, message)
        telegram_bot.send_message(chat_id, message)
        return False

    # Create ZIP files for submission
    zip_files, temp_dir = create_zip_files(config)
    try:
        # Submit the solution
        submission_id = oioioi_api.submit_solution(
            config["contest_id"], config["problem_short_name"], zip_files, branch, telegram_bot
        )
        if submission_id:
            # Append to pending submissions and save
            user_config = load_chat_config(chat_id)
            new_pending_submissions = user_config.get("pending_submissions", [])
            new_pending_submissions.append(submission_id)
            save_chat_config(chat_id, {"pending_submissions": new_pending_submissions})

            # Notify user about the submission
            telegram_bot.send_message(
                chat_id,
                "✅ *Submission Accepted*\n"
                "Results will be checked periodically."
            )
    finally:
        temp_dir.cleanup()

    return True


def process_pending_submissions(chat_id, oioioi_api, telegram_bot):
    """
    Process pending submissions for a given chat ID.
    """
    user_config = load_chat_config(chat_id)
    pending_submissions = user_config.get("pending_submissions", [])
    completed_submissions = []

    if pending_submissions and len(pending_submissions) > 0:
        oioioi_api.login()

    for submission_id in pending_submissions:
        results = oioioi_api.fetch_test_results(user_config["contest_id"], submission_id)
        if results:
            # Notify user about the results
            results_url = oioioi_api.get_results_url(user_config["contest_id"], submission_id)
            telegram_bot.send_message(chat_id, f"📄 *Results Available*\n{results_url}")
            completed_submissions.append(submission_id)

    # Remove completed submissions from the list
    new_pending_submissions = [
        sub for sub in pending_submissions if sub not in completed_submissions
    ]

    save_chat_config(chat_id, {"pending_submissions": new_pending_submissions})


def process_branch(chat_id, branch, user_config, oioioi_api, telegram_bot):
    """
    Process a branch for a specific user.
    """
    last_commit = load_last_commit(chat_id, branch)
    current_commit = get_latest_commit(branch)

    if not current_commit or current_commit == last_commit:
        return  # No new commit

    save_last_commit(chat_id, branch, current_commit)

    commit_message = get_commit_message(current_commit)
    telegram_bot.send_message(
        chat_id,
        f"🚨 *New Commit Detected*\n"
        f"• *Branch*: `{branch}`\n"
        f"• *Commit Hash*: `{current_commit}`\n"
        f"• *Message*: {commit_message}"
    )

    # Load configuration for the commit
    config = load_config_from_commit(current_commit)
    if not config or not config.get("AUTOCOMMIT", False):
        telegram_bot.send_message(
            chat_id,
            f"⚠️ *Skipping Submission*\n"
            f"• *Reason*: AUTOCOMMIT is disabled or config is missing.\n"
            f"• *Branch*: `{branch}`\n"
            f"• *Commit Hash*: `{current_commit}`"
        )
        return

    # Process the commit
    process_commit(chat_id, branch, current_commit, user_config, oioioi_api, telegram_bot)


def process_chat_id(chat_id, oioioi_api, telegram_bot):
    """
    Process all tasks for a single chat ID.
    """
    user_config = load_chat_config(chat_id)
    if not user_config:
        raise ValueError(f"No configuration found for chat ID: {chat_id}")

    # Check for new commits
    fetch_all_branches(chat_id, telegram_bot)
    branches_to_check = get_tracked_branches()
    for branch in branches_to_check:
        process_branch(chat_id, branch, user_config, oioioi_api, telegram_bot)

    # Process pending submissions
    process_pending_submissions(chat_id, oioioi_api, telegram_bot)


def main():
    global shutdown_flag

    telegram_bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)

    while not ShutdownSignal.flag:
        all_chat_configs = get_all_chat_configs()
        chat_ids = all_chat_configs.keys()

        for chat_id in chat_ids:
            try:
                oioioi_api = OioioiAPI(chat_id)
                process_chat_id(chat_id, oioioi_api, telegram_bot)
            except Exception as e:
                telegram_bot.send_message(
                    chat_id, f"❌ *Error Processing User*\n{str(e)}"
                )

        time.sleep(Config.CHECK_INTERVAL)


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)  # Ctrl+C
    signal.signal(signal.SIGTERM, handle_shutdown_signal)  # Termination signal

    print("Starting script. Press Ctrl+C to stop.")
    main()
