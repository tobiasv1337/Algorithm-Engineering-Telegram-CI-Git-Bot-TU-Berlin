import os
import shutil
import json
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from git_manager.git_operations import generate_ssh_key, clone_repository, get_chat_dir
from utils.file_operations import save_chat_config, load_chat_config, delete_chat_config


async def get_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Respond with the current chat's ID.
    """
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"The current chat ID is: `{chat_id}`")


async def add_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Add a chat ID to the broadcast list.
    """
    chat_id = update.effective_chat.id

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /add_chat_id <chat_id>")
        return

    new_chat_id = context.args[0]

    config = load_chat_config(chat_id)
    if not config:
        await update.message.reply_text("No configuration found for this chat.\n If the bot only broadcasts to this chat via /add_chat_id, configuration is only allowed via the admin's initial chat.")
        return

    broadcast_list = config.get("broadcast_chat_ids", [])
    if new_chat_id in broadcast_list:
        await update.message.reply_text(f"Chat ID `{new_chat_id}` is already in the broadcast list.")
        return

    broadcast_list.append(new_chat_id)
    save_chat_config(chat_id, {"broadcast_chat_ids": broadcast_list})

    await update.message.reply_text(f"Chat ID `{new_chat_id}` has been added to the broadcast list.")


async def remove_chat_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Remove a chat ID from the broadcast list.
    """
    chat_id = update.effective_chat.id

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /remove_chat_id <chat_id>")
        return

    remove_chat_id = context.args[0]

    config = load_chat_config(chat_id)
    if not config:
        await update.message.reply_text("No configuration found for this chat.\n If the bot only broadcasts to this chat via /add_chat_id, configuration is only allowed via the admin's initial chat.")
        return

    broadcast_list = config.get("broadcast_chat_ids", [])
    if remove_chat_id not in broadcast_list:
        await update.message.reply_text(f"Chat ID `{remove_chat_id}` is not in the broadcast list.")
        return

    broadcast_list.remove(remove_chat_id)
    save_chat_config(chat_id, {"broadcast_chat_ids": broadcast_list})

    await update.message.reply_text(f"Chat ID `{remove_chat_id}` has been removed from the broadcast list.")


async def list_chat_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    List all chat IDs in the broadcast list.
    """
    chat_id = update.effective_chat.id

    config = load_chat_config(chat_id)
    if not config:
        await update.message.reply_text("No configuration found for this chat.\n If the bot only broadcasts to this chat via /add_chat_id, configuration is only allowed via the admin's initial chat.")
        return

    broadcast_list = config.get("broadcast_chat_ids", [])
    if not broadcast_list:
        await update.message.reply_text("The broadcast list is currently empty.")
        return

    formatted_list = "\n".join(broadcast_list)
    await update.message.reply_text(f"Current broadcast list:\n{formatted_list}")


def reset_user_data(context):
    """
    Reset all temporary keys in context.user_data.
    Keeps persistent keys intact.
    """
    keys_to_remove = [
        "state",
        "config_step",
        "update_step",
        "update_key",
        "update_contest_id",
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)  # Safely remove keys if they exist


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Greet the user and provide detailed information about the bot.
    """
    user = update.effective_user.first_name
    message = (
        f"👋 *Welcome, {user}!*\n\n"
        "🤖 This bot is designed to assist with the *Algorithm Engineering* module at TU Berlin.\n"
        "It continuously monitors your repository, automatically compiles and tests your code, and submits it to the OIOIOI test platform.\n"
        "Successful submissions are automatically merged into the specified branch.\n\n"
        "📌 *Key Features:*\n"
        "• Monitors specified branches for new commits.\n"
        "• Automatically compiles code and checks for errors.\n"
        "• Submits code to the OIOIOI platform for testing.\n"
        "• Notifies you of the test results and submission status.\n"
        "• Automatically merges passing commits into the target branch.\n\n"
        "📋 *How to Set Up:*\n"
        "1️⃣ Run `/setup` to configure the bot for your repository.\n"
        "   During setup, you'll provide:\n"
        "   • Repository URL\n"
        "   • Primary branch name (e.g., `main` or `master`)\n"
        "   • Git authentication method (e.g., SSH key)\n"
        "   • OIOIOI credentials (username and password)\n"
        "2️⃣ Add additional chats (e.g., a group chat) by:\n"
        "   • Adding the bot to the chat.\n"
        "   • Running `/get_chat_id` in the group to retrieve its ID.\n"
        "   • Running `/add_chat_id <chat_id>` in your private chat with the bot to link the group.\n\n"
        "📚 *Help and Configuration:*\n"
        "• Use `/help` to view all available commands and instructions.\n"
        "• Use `/config` to update settings like the OIOIOI API key for a new contest.\n"
        "• Use `/get_chat_id` to retrieve the current chat ID.\n"
        "• Use `/add_chat_id` and `/remove_chat_id` to manage broadcast chats.\n\n"
        "👨‍💻 *About the Developer:*\n"
        "• *Name:* Tobias Veselsky\n"
        "• *University:* Technische Universität Berlin\n"
        "• *Email:* [veselsky@tu-berlin.de](mailto:veselsky@tu-berlin.de)\n"
        "• *GitHub:* [tobiasv1337](https://github.com/tobiasv1337)\n\n"
        "🚀 *Get Started:*\n"
        "Run `/setup` to configure your repository and start using the bot."
    )
    await update.message.reply_text(message, parse_mode="MarkdownV2")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Provide detailed information about the bot, its functionality, and available commands.
    """
    message = (
        "🆘 *Help Menu*\n\n"
        "🤖 *About the Bot:*\n"
        "This bot is designed to assist with the *Algorithm Engineering* module at TU Berlin\\. "
        "It automates repository monitoring, code compilation, testing, and submission to the OIOIOI platform\\. "
        "Key functionalities include notifying users about test results and merging passing commits automatically\\.\n\n"
        
        "👨‍💻 *Developer:*\n"
        "• *Name:* Tobias Veselsky\n"
        "• *University:* Technische Universität Berlin\n"
        "• *Email:* [veselsky@tu\\-berlin\\.de](mailto:veselsky@tu-berlin.de)\n"
        "• *GitHub:* [tobiasv1337](https://github.com/tobiasv1337)\n\n"
        
        "📋 *Commands Overview:*\n"
        "• `/start` \\- Greet the user and provide an overview of the bot\\. Includes instructions on how to set up and use the bot effectively\\.\n\n"
        "• `/setup` \\- Begin the initial setup for repository monitoring:\n"
        "   \\- Specify the repository URL\\.\n"
        "   \\- Set the primary branch name \\(e\\.g\\., `main` or `master`\\)\\.\n"
        "   \\- Choose a Git authentication method \\(e\\.g\\., SSH key\\)\\.\n"
        "   \\- Provide OIOIOI credentials \\(username and password\\)\\.\n"
        "   \\- The bot will automatically clone the repository and save the configuration\\.\n\n"
        "• `/config` \\- Update specific configuration settings for the bot:\n"
        "   \\- Modify parameters like `repo_url`, `primary_branch`, or authentication details\\.\n"
        "   \\- Update OIOIOI API keys for new contests\\.\n"
        "   \\- Use this command to adjust existing settings without redoing the setup\\.\n\n"
        "• `/get_chat_id` \\- Retrieve the current chat's ID\\. Useful when adding the bot to a group or secondary chat\\.\n\n"
        "• `/add_chat_id <chat_id>` \\- Add another chat to the bot's broadcast list:\n"
        "   \\- Use `/get_chat_id` in the target chat to retrieve its ID\\.\n"
        "   \\- Run this command with the retrieved ID in your main bot chat to link the additional chat\\.\n\n"
        "• `/remove_chat_id <chat_id>` \\- Remove a previously linked chat from the broadcast list:\n"
        "   \\- Specify the chat ID to stop broadcasting messages to that chat\\.\n\n"
        "• `/list_chat_ids` \\- List all linked chats that the bot broadcasts to:\n"
        "   \\- Displays the IDs of all configured chats for verification\\.\n\n"
        "• `/delete` \\- Delete the bot's current configuration and repository data:\n"
        "   \\- Deletes the repository files and all associated settings\\.\n"
        "   \\- Use this command with caution, as the action is irreversible\\.\n\n"
        "• `/abort` \\- Reset the bot's current configuration state:\n"
        "   \\- Clears any ongoing setup or configuration steps\\.\n"
        "   \\- Does *not* stop active CI tasks or bot functionality\\.\n\n"
        "• `/help` \\- Display this help message with detailed information about the bot and its commands\\.\n\n"
        "• `/sample_config` \\- Retrieve a sample `submission_config\\.json` file:\n"
        "   \\- Provides a template to include in your repository's primary branch\\.\n"
        "   \\- Explains the required fields and their purposes\\.\n\n"
        
        "🛠️ *Setup and Configuration:*\n"
        "1️⃣ Run `/setup` and provide:\n"
        "   • Repository URL\n"
        "   • Primary branch name \\(e\\.g\\., `main` or `master`\\)\n"
        "   • Git authentication method \\(e\\.g\\., SSH key\\)\n"
        "   • OIOIOI credentials \\(username and password\\)\n"
        "2️⃣ Ensure your repository includes a `submission_config\\.json` in the root directory of the primary branch\\.\n"
        "   • This file contains essential configurations for automated processing\\.\n"
        "   • Use `/sample_config` to get a sample configuration file\\.\n"
        "3️⃣ Add additional chats \\(e\\.g\\., group chat\\):\n"
        "   • Add the bot to the group\\.\n"
        "   • Run `/get_chat_id` in the group to get its ID\\.\n"
        "   • Use `/add_chat_id <chat_id>` to link the group to the bot\\.\n\n"
        
        "💡 *Tips:*\n"
        "• Use `/config` to modify settings like OIOIOI API keys or repository details\\.\n"
        "• Run `/list_chat_ids` to confirm all linked chats for message broadcasting\\.\n"
        "• Use `/abort` if you want to reset the bot's configuration state during setup\\.\n\n"
        
        "📂 *Important Note:*\n"
        "The newest commit on the primary branch and every commit to be processed by the bot *must* include a valid `submission_config\\.json` file in the root directory\\.\n\n"
        
        "For further assistance, contact the developer via email or GitHub\\.\n"
        "Happy coding\\! 🚀"
    )
    await update.message.reply_text(message, parse_mode="MarkdownV2")


async def sample_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Provide a sample submission_config.json to the user.
    """
    sample_config = {
        "language": "rust",
        "AUTOCOMMIT": True,
        "ALLOW_WARNINGS": True,
        "ALLOW_ERRORS": False,
        "contest_id": "vc4",
        "problem_short_name": "vc",
        "zip_files": [
            {
                "zip_name": "upper_bound.zip",
                "include_paths": [
                    {"source": "upper_bound/src", "destination": "src"},
                    {"source": "lib", "destination": "lib"},
                    {"source": "upper_bound/Submission.Cargo.toml", "destination": "Cargo.toml"}
                ]
            }
        ],
        "branches": ["submit"],
        "auto_merge_branch": "submit"
    }

    # Convert the sample configuration to a formatted JSON string
    formatted_config = json.dumps(sample_config, indent=2)

    # Explanation about the submission_config.json
    explanation_message = (
        "📂 *Sample submission\\_config\\.json*\n\n"
        "This is an example of a valid `submission\\_config\\.json`\\. This file must be included:\n"
        "• In the root directory of the primary branch \\(e\\.g\\. `main` or `master`\\)\\.\n"
        "• In every commit to be processed by the bot\\.\n\n"
        "The file contains essential settings for the bot's operation:\n\n"
        "1️⃣ *language*: The programming language of your submission \\(e\\.g\\., `rust`\\)\\.\n"
        "2️⃣ *AUTOCOMMIT*: Set to `true` to allow automatic processing of commits\\.\n"
        "3️⃣ *ALLOW\\_WARNINGS*: Whether warnings during compilation are acceptable\\.\n"
        "4️⃣ *ALLOW\\_ERRORS*: Whether errors during compilation are acceptable\\.\n"
        "5️⃣ *contest\\_id*: The OIOIOI contest ID for submission\\.\n"
        "6️⃣ *problem\\_short\\_name*: The problem's short name in OIOIOI\\.\n"
        "7️⃣ *zip\\_files*: A list of specifications for generating ZIP files\\. Each entry includes:\n"
        "   \\- *zip\\_name*: The name of the ZIP file to generate\\.\n"
        "   \\- *include\\_paths*: A list of mappings:\n"
        "      \\- *source*: The path within your repository to include\\.\n"
        "      \\- *destination*: The destination path inside the generated ZIP file\\.\n"
        "      You can define multiple ZIP files, each with its own set of include paths\\.\n"
        "8️⃣ *branches*: A list of branches to monitor for submissions\\.\n"
        "9️⃣ *auto\\_merge\\_branch*: The branch into which passing submissions are automatically merged\\.\n\n"
        "Use this file as a foundation to configure your repository for the bot's operation\\."
    )

    # Send the explanation message
    await update.message.reply_text(explanation_message, parse_mode="MarkdownV2")

    # Send the sample configuration in a separate message
    await update.message.reply_text(
        "```json\n"
        f"{formatted_config}\n"
        "```",
        parse_mode="MarkdownV2"
    )


async def setup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Begin the setup process to configure the bot for a repository.
    """
    chat_id = update.effective_chat.id
    user = update.effective_user.first_name

    # Check if configuration exists
    config = load_chat_config(chat_id)
    if config and config.get("setup_complete"):
        await update.message.reply_text(f"Welcome back, {user}! Your repository is already set up. If you want to change parameters, use `/config`.")
        return

    # Start repository configuration
    await update.message.reply_text(
        "Hello, {user}! "
        "🔧 Let's set up your repository for monitoring and auto-submissions.\n"
        "Please provide the following details step-by-step."
    )
    await update.message.reply_text("What is the repository URL?")
    context.user_data["state"] = "initializing"
    context.user_data["config_step"] = "repo_url"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle user messages for configuration setup or state-specific actions.
    """
    state = context.user_data.get("state")

    if state == "configuring":
        await handle_update_step(update, context)
    elif state == "initializing":
        await handle_initializing(update, context)
    elif state == "deleting":
        await delete(update, context)
    else:
        await update.message.reply_text("I'm not sure what you're asking. Try using /help for a list of available commands.")


async def config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /config command to let users update their configuration values.
    """

    # Show available options for configuring
    options = [
        "repo_url",
        "primary_branch",
        "auth_method",
        "git_username",
        "git_password",
        "oioioi_username",
        "oioioi_password",
        "OIOIOI_API_KEYS",
    ]
    options_text = "\n".join([f"- {option}" for option in options])
    await update.message.reply_text(
        f"Which configuration value would you like to update?\n\n{options_text}\n\n"
        "Send the name of the value (e.g., `repo_url`)."
    )

    context.user_data["state"] = "configuring"
    context.user_data["update_step"] = "choose_key"


async def handle_update_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle user input during the update process.
    """
    chat_id = update.effective_chat.id
    step = context.user_data.get("update_step")

    if step == "choose_key":
        key = update.message.text.strip()
        context.user_data["update_key"] = key

        if key == "OIOIOI_API_KEYS":
            await update.message.reply_text("Enter the contest ID you want to update:")
            context.user_data["update_step"] = "choose_contest"
        else:
            await update.message.reply_text(f"Enter the new value for `{key}`:")
            context.user_data["update_step"] = "update_value"

    elif step == "choose_contest":
        contest_id = update.message.text.strip()
        context.user_data["update_contest_id"] = contest_id
        await update.message.reply_text(f"Enter the new API key for contest `{contest_id}`:")
        context.user_data["update_step"] = "update_value"

    elif step == "update_value":
        key = context.user_data.get("update_key")
        value = update.message.text.strip()

        if key == "OIOIOI_API_KEYS":
            contest_id = context.user_data.get("update_contest_id")
            current_config = load_chat_config(chat_id) or {}
            api_keys = current_config.get("OIOIOI_API_KEYS", {})
            api_keys[contest_id] = value
            save_chat_config(chat_id, {"OIOIOI_API_KEYS": api_keys})
            await update.message.reply_text(f"API key for contest `{contest_id}` updated successfully!")
        else:
            save_chat_config(chat_id, {key: value})
            await update.message.reply_text(f"Configuration for `{key}` updated successfully!")

        reset_user_data(context)  # Reset state after update


async def delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /delete command to initiate and confirm deletion of user data.
    """
    chat_id = update.effective_chat.id
    state = context.user_data.get("state")

    if state == "deleting":
        if update.message.text.strip().lower() in ["yes", "confirm"]:
            try:
                delete_user_data(chat_id)
                await update.message.reply_text("✅ Your configuration and repository have been deleted.")
            except Exception as e:
                await update.message.reply_text(f"❌ Failed to delete your data: {e}")
            finally:
                reset_user_data(context)
        elif update.message.text.strip().lower() in ["no", "cancel"]:
            await update.message.reply_text("❌ Deletion canceled. Your configuration remains intact.")
            reset_user_data(context)
        else:
            await update.message.reply_text("Invalid response. Please respond with 'yes' or 'no'.")
    else:
        await update.message.reply_text(
            "Are you sure you want to delete your configuration and repository? "
            "This action is irreversible. Reply with 'yes' to confirm or 'no' to cancel."
        )
        context.user_data["state"] = "deleting"


async def abort(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /abort command to reset all states and abort any ongoing process.
    """
    reset_user_data(context)
    await update.message.reply_text("❌ All ongoing operations have been aborted. You can start a new operation.")


async def handle_initializing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the initial setup process (repo_url, auth_method, primary_branch, etc.).
    """
    chat_id = update.effective_chat.id
    step = context.user_data.get("config_step")

    if step == "repo_url":
        context.user_data["repo_url"] = update.message.text.strip()
        await update.message.reply_text("What is the primary branch of the repository? (e.g., master or main)")
        context.user_data["config_step"] = "primary_branch"
    elif step == "primary_branch":
        primary_branch = update.message.text.strip()
        if not primary_branch:
            await update.message.reply_text("Invalid input. Please provide the name of the primary branch.")
            return
        context.user_data["primary_branch"] = primary_branch
        await update.message.reply_text("Choose authentication method: [none, https, ssh]")
        context.user_data["config_step"] = "auth_method"
    elif step == "auth_method":
        auth_method = update.message.text.lower().strip()
        if auth_method not in ["none", "https", "ssh"]:
            await update.message.reply_text("Invalid choice. Please choose: [none, https, ssh]")
            return
        context.user_data["auth_method"] = auth_method
        if auth_method == "none":
            await update.message.reply_text("Please provide your OIOIOI username.")
            context.user_data["config_step"] = "oioioi_username"
        elif auth_method == "https":
            await update.message.reply_text("Please provide your Git username.")
            context.user_data["config_step"] = "git_username"
        elif auth_method == "ssh":
            await update.message.reply_text("Should I generate an SSH key for you? (yes/no)")
            context.user_data["config_step"] = "ssh_generate"
    elif step == "git_username":
        context.user_data["git_username"] = update.message.text.strip()
        await update.message.reply_text("Please provide your Git password.")
        context.user_data["config_step"] = "git_password"
    elif step == "git_password":
        context.user_data["git_password"] = update.message.text.strip()
        await update.message.reply_text("Please provide your OIOIOI username.")
        context.user_data["config_step"] = "oioioi_username"
    elif step == "ssh_generate":
        generate_key = update.message.text.lower().strip()
        if generate_key == "yes":
            ssh_key_path = generate_ssh_key(chat_id)
            with open(f"{ssh_key_path}.pub", "r") as key_file:
                public_key = key_file.read()
            await update.message.reply_text("SSH key generated successfully. Add the following public key to your repository:")
            await update.message.reply_text(public_key)
            await update.message.reply_text("Please provide your OIOIOI username.")
            context.user_data["config_step"] = "oioioi_username"
        elif generate_key == "no":
            await update.message.reply_text("Please upload your SSH public key. Send the key as plain text (not a file!). Avoid any extra characters or spaces.")
            context.user_data["config_step"] = "ssh_provided"
        else:
            await update.message.reply_text("Invalid choice. Please choose: [yes, no]")
    elif step == "ssh_provided":
        ssh_key = update.message.text.strip()

        # Validate the SSH key (basic validation)
        if ssh_key.startswith("ssh-") and " " in ssh_key:
            chat_dir = get_chat_dir(chat_id)
            ssh_key_path = os.path.join(chat_dir, "id_rsa.pub")

            if not os.path.exists(chat_dir):
                os.makedirs(chat_dir)

            with open(ssh_key_path, "w") as key_file:
                key_file.write(ssh_key)
            await update.message.reply_text("SSH key saved successfully!")

            await update.message.reply_text("Please provide your OIOIOI username.")
            context.user_data["config_step"] = "oioioi_username"
        else:
            # If the key is invalid, ask the user to provide it again
            await update.message.reply_text("Invalid SSH key format. Please provide a valid SSH public key.")
    elif step == "oioioi_username":
        context.user_data["oioioi_username"] = update.message.text.strip()
        await update.message.reply_text("Please provide your OIOIOI password.")
        context.user_data["config_step"] = "oioioi_password"
    elif step == "oioioi_password":
        context.user_data["oioioi_password"] = update.message.text.strip()
        await complete_setup(chat_id, context)


async def complete_setup(chat_id, context):
    """
    Finalize repository setup and save the configuration.
    """
    config_data = {
        "repo_url": context.user_data.get("repo_url"),
        "primary_branch": context.user_data.get("primary_branch"),
        "auth_method": context.user_data.get("auth_method"),
        "git_username": context.user_data.get("git_username"),
        "git_password": context.user_data.get("git_password"),
        "oioioi_username": context.user_data.get("oioioi_username"),
        "oioioi_password": context.user_data.get("oioioi_password"),
        "setup_complete": True,
    }
    save_chat_config(chat_id, config_data)

    # Clone repository
    try:
        clone_repository(chat_id, config_data["repo_url"])
    except Exception as e:
        await context.bot.send_message(chat_id, f"❌ Failed to clone repository: {e}")
        return

    await context.bot.send_message(chat_id, "✅ Repository and OIOIOI setup are complete and ready for use.")


def delete_user_data(chat_id):
    """
    Delete user-specific configuration and repository files.
    """
    delete_chat_config(chat_id)
    chat_dir = get_chat_dir(chat_id)
    if os.path.exists(chat_dir):
        shutil.rmtree(chat_dir)


def initialize_message_handlers(telegram_bot):
    """
    Register command and message handlers for the Telegram bot.
    """
    telegram_bot.add_handler(CommandHandler("start", start))
    telegram_bot.add_handler(CommandHandler("setup", setup))
    telegram_bot.add_handler(CommandHandler("config", config))
    telegram_bot.add_handler(CommandHandler("delete", delete))
    telegram_bot.add_handler(CommandHandler("abort", abort))
    telegram_bot.add_handler(CommandHandler("get_chat_id", get_chat_id))
    telegram_bot.add_handler(CommandHandler("add_chat_id", add_chat_id))
    telegram_bot.add_handler(CommandHandler("remove_chat_id", remove_chat_id))
    telegram_bot.add_handler(CommandHandler("list_chat_ids", list_chat_ids))
    telegram_bot.add_handler(CommandHandler("help", help_command))
    telegram_bot.add_handler(CommandHandler("sample_config", sample_config))
    telegram_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
