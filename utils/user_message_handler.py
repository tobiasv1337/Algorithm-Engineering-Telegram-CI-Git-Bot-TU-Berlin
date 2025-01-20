from telegram import Update
from telegram.ext import CommandHandler, MessageHandler, filters, ContextTypes
from git_manager.git_operations import generate_ssh_key, clone_repository
from utils.file_operations import save_chat_config, load_chat_config

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
    context.user_data["config_step"] = "repo_url"

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Handle user messages for configuration setup.
    """
    chat_id = update.effective_chat.id
    step = context.user_data.get("config_step")

    if step == "repo_url":
        # Save repo URL and ask for authentication method
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
            await update.message.reply_text(f"SSH key generated. Add this public key to your repository:\n\n`{public_key}`")
        else:
            await update.message.reply_text("Please upload your SSH public key.")
        await update.message.reply_text("Please provide your OIOIOI username.")
        context.user_data["config_step"] = "oioioi_username"

    elif step == "oioioi_username":
        context.user_data["oioioi_username"] = update.message.text
        await update.message.reply_text("Please provide your OIOIOI password.")
        context.user_data["config_step"] = "oioioi_password"

    elif step == "oioioi_password":
        context.user_data["oioioi_password"] = update.message.text
        complete_setup(chat_id, context)

def complete_setup(chat_id, context):
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
        context.bot.send_message(chat_id, f"❌ Failed to clone repository: {e}")
        return

    context.bot.send_message(chat_id, "✅ Repository and OIOIOI setup are complete and ready for use.")

def initialize_message_handlers(telegram_bot, oioioi_api):
    """
    Register command and message handlers for the Telegram bot.
    """
    telegram_bot.add_handler(CommandHandler("start", start))
    telegram_bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))