import os
import tempfile
from zipfile import ZipFile
from handlers import LANGUAGE_HANDLERS
from utils.file_operations import create_zip_files
from handlers.base_handler import CompilationError
from api.telegram import TelegramBot


def check_for_compiler_errors(chat_id, config, telegram_bot):
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
        telegram_bot.send_message(chat_id, message)
        return False

    if language not in LANGUAGE_HANDLERS:
        message = (
            f"❌ *Error*: Unsupported language '{language}'.\n"
            f"🛠 Supported languages are: {', '.join(LANGUAGE_HANDLERS.keys())}.\n\n"
            "💡 If you need support for this language, please contact the bot administrator."
        )
        print(message)
        telegram_bot.send_message(chat_id, message)
        return False

    handler = LANGUAGE_HANDLERS[language]

    zip_files, temp_dir = create_zip_files(config, chat_id)
    all_projects_meet_criteria = True

    for zip_file in zip_files:
        with tempfile.TemporaryDirectory() as temp_dir_extract:
            try:
                with ZipFile(zip_file, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir_extract)

                try:
                    result = handler.compile(temp_dir_extract)

                    if result.warnings:
                        warnings_text = "\n".join(result.warnings) if isinstance(result.warnings, list) else str(result.warnings)
                        warning_message = (
                            f"⚠️ *Warnings Detected in {TelegramBot.escape_markdown(os.path.basename(zip_file))}*\n\n"
                            f"{TelegramBot.escape_markdown(warnings_text)}"
                        )
                        print(warning_message)
                        telegram_bot.send_message(chat_id, warning_message, bypass_escaping=True)

                        if not config.get("ALLOW_WARNINGS", False):
                            all_projects_meet_criteria = False
                            break

                    print(f"✅ Compilation check completed successfully for {os.path.basename(zip_file)}.")

                except CompilationError as e:
                    error_message = (
                        f"❌ *Compiler Errors Detected in {TelegramBot.escape_markdown(os.path.basename(zip_file))}*\n\n"
                        f"{TelegramBot.escape_markdown(str(e))}"
                    )
                    print(error_message)
                    telegram_bot.send_message(chat_id, error_message, bypass_escaping=True)

                    if not config.get("ALLOW_ERRORS", False):
                        all_projects_meet_criteria = False
                        break

            except Exception as e:
                unexpected_error_message = (
                    f"❌ *Unexpected Error During Compilation Check*\n\n"
                    f"Project: `{TelegramBot.escape_markdown(os.path.basename(zip_file))}`\n"
                    f"Error: {TelegramBot.escape_markdown(str(e))}"
                )
                print(unexpected_error_message)
                telegram_bot.send_message(chat_id, unexpected_error_message, bypass_escaping=True)
                all_projects_meet_criteria = False
                break

    temp_dir.cleanup()
    return all_projects_meet_criteria
