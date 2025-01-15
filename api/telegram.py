import requests

class TelegramBot:
    def __init__(self, token, chat_ids):
        """
        Initialize the Telegram bot with the provided token and chat IDs.
        """
        self.token = token
        self.chat_ids = chat_ids
        self.base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"

    def send_message(self, message, parse_mode="MarkdownV2", disable_web_page_preview=True):
        """
        Send a message to the Telegram group. Automatically splits long messages if needed.
        Splits at newline characters when possible.
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

        for chat_id in self.chat_ids:
            # Send each part as a separate Telegram message
            for part in split_messages:
                payload = {
                    "chat_id": chat_id,
                    "text": part.strip(),
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_web_page_preview,
                }
                try:
                    response = requests.post(self.base_url, data=payload)
                    if response.status_code == 200:
                        print("Message sent to Telegram successfully.")
                    else:
                        print(f"Failed to send message to Telegram. Status code: {response.status_code}")
                        print(f"Response: {response.text}")
                except Exception as e:
                    print(f"Error sending message to Telegram: {e}")
