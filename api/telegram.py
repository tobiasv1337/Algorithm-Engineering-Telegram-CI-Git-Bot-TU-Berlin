import requests
from utils.file_operations import load_chat_config


class TelegramBot:
    def __init__(self, token):
        """
        Initialize the Telegram bot with the provided token.
        """
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_message(self, chat_id, message, parse_mode="MarkdownV2", disable_web_page_preview=True, broadcast_mode=True):
        """
        Send a message to a single chat or broadcast to additional configured chat IDs if broadcast_mode is enabled.
        Automatically splits long messages if needed. Splits at newline characters when possible.

        Args:
            chat_id (int): The primary chat ID to send the message to.
            message (str): The message to send.
            parse_mode (str): The parse mode for Telegram Markdown (default: "MarkdownV2").
            disable_web_page_preview (bool): Whether to disable link previews (default: True).
            broadcast_mode (bool): Whether to broadcast the message to additional configured chat IDs (default: True).
        """
        max_length = 4096  # Telegram's maximum message length

        def escape_markdown(text, exclude=None):
            """Escape special characters in text for Telegram Markdown while preserving formatting."""
            if exclude is None:
                exclude = set('*')  # Allow bold
            escape_chars = '_*[]()~`>#+-=|{}.!'
            return ''.join(f'\\{char}' if char in escape_chars and char not in exclude else char for char in text)

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

        chat_ids = [chat_id]
        if broadcast_mode:
            # Fetch additional chat IDs from the config
            config = load_chat_config(chat_id)
            chat_ids += config.get("broadcast_chat_ids", [])

        # Send messages to all specified chat IDs
        for single_chat_id in chat_ids:
            self._send_to_single_chat(single_chat_id, split_messages, parse_mode, disable_web_page_preview)

    def _send_to_single_chat(self, chat_id, messages, parse_mode, disable_web_page_preview):
        """
        Helper method to send multiple parts of a message to a single chat.

        Args:
            chat_id (int): The chat ID to send messages to.
            messages (list): List of message parts to send.
            parse_mode (str): The parse mode for Telegram Markdown.
            disable_web_page_preview (bool): Whether to disable link previews.
        """
        for part in messages:
            payload = {
                "chat_id": chat_id,
                "text": part.strip(),
                "parse_mode": parse_mode,
                "disable_web_page_preview": disable_web_page_preview,
            }
            try:
                response = requests.post(self.base_url, data=payload)
                if response.status_code == 200:
                    print(f"Message sent to chat {chat_id} successfully.")
                else:
                    print(f"Failed to send message to chat {chat_id}. Status code: {response.status_code}")
                    print(f"Response: {response.text}")
            except Exception as e:
                print(f"Error sending message to chat {chat_id}: {e}")

    def broadcast_message(self, chat_ids, message):
        """
        Send a message to a list of chat IDs.
        """
        for chat_id in chat_ids:
            self.send_message(chat_id, message)
