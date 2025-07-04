import os
import shutil
import json
from telegram import Update, BotCommand
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes, Application
from git_manager.git_operations import generate_ssh_key, clone_repository, get_chat_dir, delete_last_commit_data
from utils.file_operations import save_chat_config, load_chat_config, delete_chat_config, get_repo_path, delete_old_auth_data

# White-listed configuration options for /config command
config_whitelist = [
    "repo_url",
    "primary_branch",
    "auth_method",
    "git_username",
    "git_password",
    "oioioi_username",
    "oioioi_password",
    "OIOIOI_API_KEYS",
]

TERMS_AND_CONDITIONS = (
    "📜 *Terms and Conditions*\n\n"
    "1️⃣ The owner of this bot is not responsible/liable for any problems that occur due to its usage\\. "
    "By using this bot, you accept that the usage is entirely at your own risk\\.\n\n"
    "2️⃣ Any attacks on this bot, including malicious activity, are forbidden\\. "
    "All activity is logged and may be forwarded to local authorities if necessary\\.\n\n"
    "3️⃣ This bot is intended only for use within the TU Berlin course\\. "
    "As credentials are valid only for this course, the bot stores repositories, configuration data, and credentials \\(including passwords\\) in plain text\\. "
    "Only provide data that you are comfortable with sharing\\. By using this bot, you agree to accept this risk\\.\n\n"
    "By typing *`accept`*, you agree to these terms and conditions and can proceed with the setup\\.\n"
    "If you do not agree, type *`abort`*\\."
)


async def ensure_user_setup(chat_id, update):
    """
    Check if the user has completed the setup.
    If not, send an error message. Return True if setup is complete.
    """
    config = load_chat_config(chat_id)
    if not config or not config.get("setup_complete", False):
        await update.message.reply_text(
            "❌ The bot is not fully configured yet.\n"
            "Please complete the setup using /setup before accessing this command."
        )
        return False
    return True


async def register_commands(application: Application):
    """
    Register bot commands to show them in the list when the user types '/'.
    """
    commands = [
        BotCommand("start", "Learn about the bot, its purpose, and how to begin"),
        BotCommand("setup", "Configure the bot for your repository"),
        BotCommand("config", "Modify settings like repo URL or API keys"),
        BotCommand("get_chat_id", "Get the current chat's ID"),
        BotCommand("add_chat_id", "Link another chat to receive bot messages"),
        BotCommand("remove_chat_id", "Unlink a chat from receiving bot messages"),
        BotCommand("list_chat_ids", "View all linked chats for broadcasting"),
        BotCommand("delete", "Remove all configurations and repository data"),
        BotCommand("abort", "Cancel the current setup or configuration process"),
        BotCommand("help", "Get detailed information about the bot and its commands"),
        BotCommand("sample_config", "Download a sample submission_config.json template"),
    ]
    await application.bot.set_my_commands(commands)


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

    if not await ensure_user_setup(chat_id, update):
        return

    if not context.args or not context.args[0].lstrip("-").isdigit():
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

    if not await ensure_user_setup(chat_id, update):
        return

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

    if not await ensure_user_setup(chat_id, update):
        return

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
        "config_step",
        "update_key",
        "update_contest_id",
        "ssh_public_key",
        "ssh_private_key",
    ]
    for key in keys_to_remove:
        context.user_data.pop(key, None)  # Safely remove keys if they exist


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Greet the user and provide detailed information about the bot.
    """
    user = update.effective_user.first_name
    message = (
        f"👋 *Welcome, {user}\\!*\n\n"
        "🤖 This bot is designed to assist with the *Algorithm Engineering* module at TU Berlin\\.\n"
        "It continuously monitors your repository, automatically compiles and tests your code, and submits it to the OIOIOI test platform\\.\n"
        "Successful submissions are automatically merged into the specified branch\\.\n\n"
        "📌 *Key Features:*\n"
        "• Monitors specified branches for new commits\\.\n"
        "• Automatically compiles code and checks for errors\\.\n"
        "• Submits code to the OIOIOI platform for testing\\.\n"
        "• Notifies you of the test results and submission status\\.\n"
        "• Automatically merges passing commits into the target branch\\.\n\n"
        "📋 *How to Set Up:*\n"
        "1️⃣ Run /setup to configure the bot for your repository\\.\n"
        "   During setup, you'll provide:\n"
        "   • Repository URL\n"
        "   • Primary branch name \\(e\\.g\\., `main` or `master`\\)\n"
        "   • Git authentication method \\(e\\.g\\. SSH key\\)\n"
        "   • OIOIOI credentials \\(username and password\\)\n"
        "2️⃣ Add additional chats \\(e\\.g\\. a group chat\\) by:\n"
        "   • Adding the bot to the chat\\.\n"
        "   • Running /get\\_chat\\_id in the group to retrieve its ID\\.\n"
        "   • Running /add\\_chat\\_id <chat\\_id\\> in your private chat with the bot to link the group\\.\n\n"
        "📚 *Help and Configuration:*\n"
        "• Use /help to view all available commands and instructions\\.\n"
        "• Use /config to update settings like the OIOIOI API key for a new contest\\.\n"
        "• Use /get\\_chat\\_id to retrieve the current chat ID\\.\n"
        "• Use /add\\_chat\\_id and /remove\\_chat\\_id to manage broadcast chats\\.\n\n"
        "👨‍💻 *About the Developer:*\n"
        "• *Name:* Tobias Veselsky\n"
        "• *University:* Technische Universität Berlin\n"
        "• *Email:* [veselsky@tu\\-berlin\\.de]\\(mailto:veselsky@tu\\-berlin\\.de\\)\n"
        "• *GitHub:* [tobiasv1337]\\(https://github\\.com/tobiasv1337\\)\n\n"
        "🚀 *Get Started:*\n"
        "Run /setup to configure your repository and start using the bot\\."
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
        "• /start \\- Greet the user and provide an overview of the bot\\. Includes instructions on how to set up and use the bot effectively\\.\n\n"
        "• /setup \\- Begin the initial setup for repository monitoring:\n"
        "   \\- Specify the repository URL\\.\n"
        "   \\- Set the primary branch name \\(e\\.g\\. `main` or `master`\\)\\.\n"
        "   \\- Choose a Git authentication method \\(e\\.g\\. SSH key\\)\\.\n"
        "   \\- Provide OIOIOI credentials \\(username and password\\)\\.\n"
        "   \\- The bot will automatically clone the repository and save the configuration\\.\n\n"
        "• /config \\- Update specific configuration settings for the bot:\n"
        "   \\- Modify parameters like `repo\\_url`, `primary\\_branch`, or authentication details\\.\n"
        "   \\- Update OIOIOI API keys for new contests\\.\n"
        "   \\- Use this command to adjust existing settings without redoing the setup\\.\n\n"
        "• /get\\_chat\\_id \\- Retrieve the current chat's ID\\. Useful when adding the bot to a group or secondary chat\\.\n\n"
        "• /add\\_chat\\_id <chat\\_id\\> \\- Add another chat to the bot's broadcast list:\n"
        "   \\- Use `/get\\_chat\\_id` in the target chat to retrieve its ID\\.\n"
        "   \\- Run this command with the retrieved ID in your main bot chat to link the additional chat\\.\n\n"
        "• /remove\\_chat\\_id <chat\\_id\\> \\- Remove a previously linked chat from the broadcast list:\n"
        "   \\- Specify the chat ID to stop broadcasting messages to that chat\\.\n\n"
        "• /list\\_chat\\_ids \\- List all linked chats that the bot broadcasts to:\n"
        "   \\- Displays the IDs of all configured chats for verification\\.\n\n"
        "• /delete \\- Delete the bot's current configuration and repository data:\n"
        "   \\- Deletes the repository files and all associated settings\\.\n"
        "   \\- Use this command with caution, as the action is irreversible\\.\n\n"
        "• /abort \\- Reset the bot's current configuration state:\n"
        "   \\- Clears any ongoing setup or configuration steps\\.\n"
        "   \\- Does *not* stop active CI tasks or bot functionality\\.\n\n"
        "• /help \\- Display this help message with detailed information about the bot and its commands\\.\n\n"
        "• /sample\\_config \\- Retrieve a sample `submission\\_config\\.json` file:\n"
        "   \\- Provides a template to include in your repository's primary branch\\.\n"
        "   \\- Explains the required fields and their purposes\\.\n\n"
        
        "🛠️ *Setup and Configuration:*\n"
        "1️⃣ Run /setup and provide:\n"
        "   • Repository URL\n"
        "   • Primary branch name \\(e\\.g\\. `main` or `master`\\)\n"
        "   • Git authentication method \\(e\\.g\\. SSH key\\)\n"
        "   • OIOIOI credentials \\(username and password\\)\n"
        "2️⃣ Ensure your repository includes a `submission\\_config\\.json` in the root directory of the primary branch\\.\n"
        "   • This file contains essential configurations for automated processing\\.\n"
        "   • Use /sample\\_config to get a sample configuration file\\.\n"
        "3️⃣ Add additional chats \\(e\\.g\\., group chat\\):\n"
        "   • Add the bot to the group\\.\n"
        "   • Run /get\\_chat\\_id in the group to get its ID\\.\n"
        "   • Use /add\\_chat\\_id <chat\\_id\\> to link the group to the bot\\.\n\n"
        
        "💡 *Tips:*\n"
        "• Use /config to modify settings like OIOIOI API keys or repository details\\.\n"
        "• Run /list\\_chat\\_ids to confirm all linked chats for message broadcasting\\.\n"
        "• Use /abort if you want to reset the bot's configuration state during setup\\.\n\n"
        
        "📂 *Important Note:*\n"
        "The newest commit on the primary branch and every commit to be processed by the bot *must* include a valid `submission\\_config\\.json` file in the root directory\\.\n\n"
        
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
        await update.message.reply_text(f"Welcome back, {user}! Your repository is already set up. If you want to change parameters, use /config.")
        return

    # Send terms and conditions
    await update.message.reply_text(
        f"Hello, {user}! 🔧 Let's set up your repository for monitoring and auto-submissions.\n"
        "Before proceeding, please review and accept the terms and conditions.",
    )
    await update.message.reply_text(TERMS_AND_CONDITIONS, parse_mode="MarkdownV2")
    
    # Set the state for accepting terms
    context.user_data["state"] = "accept_terms"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle user messages for configuration setup, terms acceptance, or other actions.
    """
    state = context.user_data.get("state")

    if state == "accept_terms":
        response = update.message.text.strip().lower()
        if response == "accept":
            await update.message.reply_text("✅ Thank you for accepting the terms. Let's continue with the setup.\nPlease provide the following details step-by-step:")
            await update.message.reply_text("What is the repository URL?\n *IMPORTANT*: Make sure to your repo url is in this format: https://github\\.com/tobiasv1337/vertex\\_cover \\(always provide the https link and without any \\.git ending etc\\.\\)", parse_mode="MarkdownV2")
            context.user_data["state"] = "initializing"
            context.user_data["config_step"] = "repo_url"
        elif response == "abort":
            await update.message.reply_text("❌ Setup aborted. You can restart the process by sending /setup.")
            reset_user_data(context)
        else:
            await update.message.reply_text("Invalid response. Please type *`accept`* to proceed or *`abort`* to cancel.", parse_mode="MarkdownV2")

    elif state == "initializing":
        await handle_initializing(update, context)
    elif state == "configuring":
        await handle_config_step(update, context)
    elif state == "deleting":
        await delete(update, context)
    else:
        await update.message.reply_text("I'm not sure what you're asking. Try using /help for a list of available commands.")


async def config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /config command to let users update their configuration values.
    """
    chat_id = update.effective_chat.id

    if not await ensure_user_setup(chat_id, update):
        return

    options_text = "\n".join([f"- {option}" for option in config_whitelist])
    await update.message.reply_text(
        f"Which configuration value would you like to update?\n\n{options_text}\n\n"
        "Send the name of the value (e.g., `repo_url`)."
    )

    context.user_data["state"] = "configuring"
    context.user_data["config_step"] = "choose_key"


async def handle_config_step(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle user input during the config process.
    """
    chat_id = update.effective_chat.id
    step = context.user_data.get("config_step")

    if step == "choose_key":
        key = update.message.text.strip()
        context.user_data["update_key"] = key

        if key == "OIOIOI_API_KEYS":
            # Handle nested configuration for API keys
            await update.message.reply_text("Enter the contest ID you want to update:")
            context.user_data["config_step"] = "choose_contest"
        elif key in config_whitelist:
            if key == "auth_method":
                await update.message.reply_text("Choose a new authentication method: [none, https, ssh]")
            elif key == "repo_url":
                await update.message.reply_text("Enter the new repository URL. *IMPORTANT*: Make sure to your repo url is in this format: https://github\\.com/tobiasv1337/vertex\\_cover \\(always provide the https link and without any \\.git ending etc\\.\\)", parse_mode="MarkdownV2")
            else:
                await update.message.reply_text(f"Enter the new value for `{key}`:")
            context.user_data["config_step"] = "update_value"
        else:
            await update.message.reply_text(
                f"Invalid configuration option. Please choose from the following:\n\n"
                f"{', '.join(config_whitelist)}"
            )
            return

    elif step == "choose_contest":
        contest_id = update.message.text.strip()
        context.user_data["update_contest_id"] = contest_id
        await update.message.reply_text(f"Enter the new API key for contest `{contest_id}`:")
        context.user_data["config_step"] = "update_value"

    elif step == "update_value":
        key = context.user_data.get("update_key")
        new_value = update.message.text.strip()

        if key == "OIOIOI_API_KEYS":
            contest_id = context.user_data.get("update_contest_id")
            current_config = load_chat_config(chat_id) or {}
            api_keys = current_config.get("OIOIOI_API_KEYS", {})
            api_keys[contest_id] = new_value
            save_chat_config(chat_id, {"OIOIOI_API_KEYS": api_keys})
            await update.message.reply_text(f"API key for contest `{contest_id}` updated successfully!")
            reset_user_data(context)
        elif key == "auth_method":
            delete_old_auth_data(chat_id)

            save_chat_config(chat_id, {key: new_value})
            if new_value == "ssh":
                await update.message.reply_text("Would you like me to generate an SSH key pair for you? (yes/no)")
                context.user_data["config_step"] = "ssh_generate"
            elif new_value == "https":
                await update.message.reply_text("Please provide your Git username.")
                context.user_data["config_step"] = "git_username"
            elif new_value == "none":
                await update.message.reply_text("Authentication method updated to 'none'.")
                await reclone_repository(update, chat_id, key)
                reset_user_data(context)
            else:
                await update.message.reply_text("Invalid authentication method. Please choose: [none, https, ssh]")
        else:
            # Update a regular configuration key
            save_chat_config(chat_id, {key: new_value})

            if key in ["repo_url", "primary_branch"]:
                await reclone_repository(update, chat_id, key)
            else:
                await update.message.reply_text(f"Configuration for `{key}` updated successfully!")
            reset_user_data(context)

    elif step == "git_username":
        git_username = update.message.text.strip()
        save_chat_config(chat_id, {"git_username": git_username})
        await update.message.reply_text("Please provide your Git password.")
        context.user_data["config_step"] = "git_password"

    elif step == "git_password":
        git_password = update.message.text.strip()
        save_chat_config(chat_id, {"git_password": git_password})
        await update.message.reply_text("Git credentials updated successfully.")
        await reclone_repository(update, chat_id, "auth_method")
        reset_user_data(context)

    elif step == "ssh_generate":
        generate_key = update.message.text.strip().lower()
        if generate_key == "yes":
            ssh_key_path = generate_ssh_key(chat_id)
            with open(f"{ssh_key_path}.pub", "r") as pub_file:
                public_key = pub_file.read()
            with open(ssh_key_path, "r") as priv_file:
                private_key = priv_file.read()

            save_ssh_keys(chat_id, public_key, private_key)

            await update.message.reply_text(
                "SSH key pair generated successfully! Add the public key to your repository's SSH settings.\n\n"
                f"Public Key:"
            )
            await update.message.reply_text(public_key)
            await reclone_repository(update, chat_id, "ssh_key")
            reset_user_data(context)
        elif generate_key == "no":
            await update.message.reply_text(
                "Please provide your SSH public key first.\n\n"
                "It should start with `ssh-`. Copy and paste it as plain text."
            )
            context.user_data["config_step"] = "ssh_public_key"
        else:
            await update.message.reply_text("Invalid choice. Please respond with 'yes' or 'no'.")

    elif step == "ssh_public_key":
        ssh_public_key = update.message.text.strip()
        if ssh_public_key.startswith("ssh-") and " " in ssh_public_key:
            context.user_data["ssh_public_key"] = ssh_public_key
            await update.message.reply_text(
                "Public key received. Now, please provide your private key.\n\n"
                "The private key should start with `-----BEGIN OPENSSH PRIVATE KEY-----`.\n"
                "Ensure you copy the entire key block and send it as plain text."
            )
            context.user_data["config_step"] = "ssh_private_key"
        else:
            await update.message.reply_text(
                "Invalid public key format. Ensure it starts with `ssh-` and resend the key."
            )

    elif step == "ssh_private_key":
        ssh_private_key = update.message.text.strip()
        if ssh_private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
            save_ssh_keys(chat_id, context.user_data["ssh_public_key"], ssh_private_key)
            del context.user_data["ssh_public_key"]
            await update.message.reply_text("SSH keys saved successfully!")
            await reclone_repository(update, chat_id, "ssh_key")
            reset_user_data(context)
        else:
            await update.message.reply_text(
                "Invalid private key format. Ensure it starts with `-----BEGIN OPENSSH PRIVATE KEY-----` and resend the key."
            )


async def reclone_repository(update: Update, chat_id, key):
    """
    Re-clone the repository after updating the configuration.
    """

    # Notify the user about the repository reset
    await update.message.reply_text(
        f"⚠️ *Configuration Updated*\n"
        f"• `{key}` has been changed.\n"
        "The repository will be reset and re-cloned with the new configuration."
    )

    # Delete the old repository
    repo_path = get_repo_path(chat_id)
    if os.path.exists(repo_path):
        shutil.rmtree(repo_path)
        await update.message.reply_text("Old repository deleted.")

    # Re-clone the repository
    try:
        repo_url = load_chat_config(chat_id)["repo_url"]
        clone_repository(chat_id, repo_url)
        await update.message.reply_text("✅ Repository re-cloned successfully.")
    except Exception as e:
        await update.message.reply_text(
            f"❌ *Error Re-Cloning Repository*\nDetails: {e}"
        )


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
            await update.message.reply_text(
                "Would you like me to generate an SSH key pair for you? (yes/no)\n\n"
                "If you select 'no', you will need to provide both the public and private keys manually."
            )
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
            with open(f"{ssh_key_path}.pub", "r") as pub_file:
                public_key = pub_file.read()
            with open(ssh_key_path, "r") as priv_file:
                private_key = priv_file.read()

            save_ssh_keys(chat_id, public_key, private_key)

            await update.message.reply_text(
                "SSH key pair generated successfully! Add the public key to your repository's SSH settings.\n\n"
                f"Public Key:"
            )
            await update.message.reply_text(public_key)
            await update.message.reply_text("Please provide your OIOIOI username.")
            context.user_data["config_step"] = "oioioi_username"
        elif generate_key == "no":
            await update.message.reply_text(
                "Please provide your SSH public key first.\n\n"
                "It should start with `ssh-`. Copy and paste it as plain text."
            )
            context.user_data["config_step"] = "ssh_public_key"
        else:
            await update.message.reply_text("Invalid choice. Please respond with 'yes' or 'no'.")
    elif step == "ssh_public_key":
        ssh_public_key = update.message.text.strip()
        if ssh_public_key.startswith("ssh-") and " " in ssh_public_key:
            context.user_data["ssh_public_key"] = ssh_public_key
            await update.message.reply_text(
                "Public key received. Now, please provide your private key.\n\n"
                "The private key should start with `-----BEGIN OPENSSH PRIVATE KEY-----`.\n"
                "Ensure you copy the entire key block and send it as plain text."
            )
            context.user_data["config_step"] = "ssh_private_key"
        else:
            await update.message.reply_text(
                "Invalid public key format. Ensure it starts with `ssh-` and resend the key."
            )
    elif step == "ssh_private_key":
        ssh_private_key = update.message.text.strip()
        if ssh_private_key.startswith("-----BEGIN OPENSSH PRIVATE KEY-----"):
            save_ssh_keys(chat_id, context.user_data["ssh_public_key"], ssh_private_key)
            del context.user_data["ssh_public_key"]
            await update.message.reply_text("SSH keys saved successfully!")
            await update.message.reply_text("Please provide your OIOIOI username.")
            context.user_data["config_step"] = "oioioi_username"
        else:
            await update.message.reply_text(
                "Invalid private key format. Ensure it starts with `-----BEGIN OPENSSH PRIVATE KEY-----` and resend the key."
            )
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

    reset_user_data(context)

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
    delete_last_commit_data(chat_id)
    chat_dir = get_chat_dir(chat_id)
    if os.path.exists(chat_dir):
        shutil.rmtree(chat_dir)


def save_ssh_keys(chat_id, public_key, private_key):
    """
    Save both the public and private SSH keys for a given chat ID.
    """
    chat_dir = get_chat_dir(chat_id)

    if not os.path.exists(chat_dir):
        os.makedirs(chat_dir)

    public_key_path = os.path.join(chat_dir, "id_rsa.pub")
    private_key_path = os.path.join(chat_dir, "id_rsa")

    with open(public_key_path, "w") as pub_file:
        pub_file.write(public_key)
    with open(private_key_path, "w") as priv_file:
        priv_file.write(private_key)

    # Set permissions for the private key
    os.chmod(private_key_path, 0o600)


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
