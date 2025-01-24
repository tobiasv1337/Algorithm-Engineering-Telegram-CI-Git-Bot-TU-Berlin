import time
import signal
import asyncio
from config.config import Config
from git_manager.git_operations import (get_commit_message, load_last_commit, save_last_commit, fetch_all_branches, get_latest_commit, reset_to_commit, load_config_from_commit, get_tracked_branches, perform_auto_merge)
from api.oioioi import OioioiAPI
from api.telegram import TelegramBot
from utils.file_operations import create_zip_files, load_chat_config, save_chat_config, get_all_chat_configs
from utils.system import handle_shutdown_signal, ShutdownSignal
from handlers.compilation_manager import check_for_compiler_errors
from datetime import datetime, timedelta
from utils.user_message_handler import initialize_message_handlers, register_commands
from telegram.ext import Application
from utils.results_utils import send_results_summary_to_telegram

# Global error tracker to handle backoff time for chat IDs
error_tracker = {}


def process_commit(chat_id, branch, current_commit, config, oioioi_api, telegram_bot):
    """
    Process a new commit: validate, compile, submit, and handle results.
    """
    # Reset to the specific commit
    reset_to_commit(chat_id, branch, current_commit, telegram_bot)

    # Check for compiler errors
    if not check_for_compiler_errors(chat_id, config, telegram_bot):
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
        return False

    # Create ZIP files for submission
    zip_files, temp_dir = create_zip_files(config, chat_id)
    try:
        # Submit the solution
        submission_id = oioioi_api.submit_solution(chat_id, config["contest_id"], config["problem_short_name"], zip_files, branch, telegram_bot)
        if submission_id:
            # Append to pending submissions and save both contest_id, submission_id, and commit_hash
            user_config = load_chat_config(chat_id)
            new_pending_submissions = user_config.get("pending_submissions", [])
            new_pending_submissions.append({
                "submission_id": submission_id,
                "contest_id": config["contest_id"],
                "commit_hash": current_commit
            })
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
    Process pending submissions for a given chat ID and handle auto-merge if configured.
    """
    user_config = load_chat_config(chat_id)
    pending_submissions = user_config.get("pending_submissions", [])
    completed_submissions = []

    if pending_submissions and len(pending_submissions) > 0:
        oioioi_api.login()

    for submission in pending_submissions:
        submission_id = submission["submission_id"]
        contest_id = submission["contest_id"]
        commit_hash = submission["commit_hash"]

        results = oioioi_api.fetch_test_results(contest_id, submission_id)
        if results:
            # Notify user about the results
            results_url = oioioi_api.get_results_url(contest_id, submission_id)
            send_results_summary_to_telegram(chat_id, contest_id, results, results_url, telegram_bot)

            # Perform auto-merge if configured
            branch = user_config.get("auto_merge_branch")
            if branch:
                perform_auto_merge(chat_id, branch, results, commit_hash, telegram_bot)

            completed_submissions.append(submission)

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
    current_commit = get_latest_commit(chat_id, branch, telegram_bot)

    if not current_commit or current_commit == last_commit:
        return  # No new commit

    save_last_commit(chat_id, branch, current_commit)

    commit_message = get_commit_message(chat_id, current_commit, telegram_bot)
    telegram_bot.send_message(
        chat_id,
        f"🚨 *New Commit Detected*\n"
        f"• *Branch*: `{branch}`\n"
        f"• *Commit Hash*: `{current_commit}`\n"
        f"• *Message*: {commit_message}"
    )

    # Load configuration for the commit
    config = load_config_from_commit(chat_id, current_commit)
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
    process_commit(chat_id, branch, current_commit, config, oioioi_api, telegram_bot)


def process_chat_id(chat_id, oioioi_api, telegram_bot):
    """
    Process all tasks for a single chat ID.
    """
    global error_tracker
    now = datetime.now()

    # Check if this chat ID is in an error state and respect the backoff time
    if chat_id in error_tracker:
        last_error_time, _ = error_tracker[chat_id]
        if now - last_error_time < Config.BACKOFF_TIME:
            return  # Skip processing this chat ID

    try:
        user_config = load_chat_config(chat_id)
        if not user_config:
            raise ValueError(f"No configuration found for chat ID: {chat_id}")

        # Check for new commits
        fetch_all_branches(chat_id, telegram_bot)
        branches_to_check = get_tracked_branches(chat_id, telegram_bot)

        for branch in branches_to_check:
            process_branch(chat_id, branch, user_config, oioioi_api, telegram_bot)

        # Process pending submissions
        process_pending_submissions(chat_id, oioioi_api, telegram_bot)

        # Clear error state if successful
        if chat_id in error_tracker:
            del error_tracker[chat_id]

    except Exception as e:
        telegram_bot.send_message(
            chat_id, f"❌ *Error Processing User*\n{str(e)}\nI will retry in {Config.BACKOFF_TIME.seconds} seconds."
        )
        error_tracker[chat_id] = (now, str(e))


async def ci_task_loop():
    """
    CI Task Loop: Periodically processes CI-related tasks for all chat IDs.
    """
    telegram_bot = TelegramBot(Config.TELEGRAM_BOT_TOKEN)

    print("▶️ CI Task Loop started.")

    while not ShutdownSignal.flag:
        # Perform CI tasks
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

        await asyncio.sleep(Config.CHECK_INTERVAL)
    
    print("⏹️ CI Task Loop stopped.")


async def telegram_task():
    """
    Telegram Task: Handles incoming bot commands and updates.
    """
    application = Application.builder().token(Config.TELEGRAM_BOT_TOKEN).build()

    initialize_message_handlers(application)
    await register_commands(application)

    await application.initialize()
    await application.updater.start_polling()
    await application.start()
    print("▶️ Telegram bot started.")

    # Keep running until we need to shut down
    while not ShutdownSignal.flag:
        await asyncio.sleep(1)

    # Stop the bot
    await application.stop()
    print("⏹️ Telegram bot stopped.")


async def main():
    """
    Main function to run Telegram bot and CI task loop concurrently.
    """

    bot_task = asyncio.create_task(telegram_task())
    ci_task = asyncio.create_task(ci_task_loop())

    # Run both concurrently
    await asyncio.gather(bot_task, ci_task)


if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, handle_shutdown_signal)  # Ctrl+C
    signal.signal(signal.SIGTERM, handle_shutdown_signal)  # Termination signal

    print("Starting Telegram-Bot and CI tasks. Press Ctrl+C to stop.")
    asyncio.run(main())
