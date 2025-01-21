import os
import shutil
from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from git_manager.git_operations import generate_ssh_key, clone_repository, get_chat_dir
from utils.file_operations import save_chat_config, load_chat_config, delete_chat_config


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
    Handle the /start command and initialize repository setup.
    """
    chat_id = update.effective_chat.id
    user = update.effective_user.first_name

    # Check if configuration exists
    config = load_chat_config(chat_id)
    if config and config.get("setup_complete"):
        await update.message.reply_text(f"Welcome back, {user}! Your repository is already set up.")
        return

    # Start repository configuration
    await update.message.reply_text(f"Hello, {user}! Let's set up your repository.")
    await update.message.reply_text("What is the repository URL?")
    context.user_data["state"] = "initializing"
    context.user_data["config_step"] = "repo_url"


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle user messages for configuration setup or state-specific actions.
    """
    state = context.user_data.get("state")

    if state == "updating":
        await handle_update_step(update, context)
    elif state == "initializing":
        await handle_initializing(update, context)
    elif state == "deleting":
        await delete(update, context)
    else:
        await update.message.reply_text("I'm not sure what you're asking. Try using /start or /update.")


async def update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the /update command to let users update their configuration values.
    """

    # Show available options for updating
    options = [
        "repo_url",
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

    context.user_data["state"] = "updating"
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
    await update.message.reply_text("❌ All ongoing operations have been aborted. You can start again with /start or /update.")


async def handle_initializing(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle the initial setup process (repo_url, auth_method, etc.).
    """
    chat_id = update.effective_chat.id
    step = context.user_data.get("config_step")

    if step == "repo_url":
        context.user_data["repo_url"] = update.message.text
        await update.message.reply_text("Choose authentication method: [none, https, ssh]")
        context.user_data["config_step"] = "auth_method"
    elif step == "auth_method":
        auth_method = update.message.text.lower()
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
        context.user_data["git_username"] = update.message.text
        await update.message.reply_text("Please provide your Git password.")
        context.user_data["config_step"] = "git_password"
    elif step == "git_password":
        context.user_data["git_password"] = update.message.text
        await update.message.reply_text("Please provide your OIOIOI username.")
        context.user_data["config_step"] = "oioioi_username"
    elif step == "ssh_generate":
        generate_key = update.message.text.lower()
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
            await update.message.reply_text(
                "Invalid SSH key format. Please provide a valid SSH public key."
            )
    elif step == "oioioi_username":
        context.user_data["oioioi_username"] = update.message.text
        await update.message.reply_text("Please provide your OIOIOI password.")
        context.user_data["config_step"] = "oioioi_password"
    elif step == "oioioi_password":
        context.user_data["oioioi_password"] = update.message.text
        await complete_setup(chat_id, context)


async def complete_setup(chat_id, context):
    """
    Finalize repository setup and save the configuration.
    """
    config_data = {
        "repo_url": context.user_data.get("repo_url"),
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
    telegram_bot.add_handler(CommandHandler("update", update))
    telegram_bot.add_handler(CommandHandler("delete", delete))
    telegram_bot.add_handler(CommandHandler("abort", abort))
    telegram_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
