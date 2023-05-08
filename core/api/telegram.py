import requests


class TelegramBot:
    def __init__(self, bot_token, user_id) -> None:
        self.bot_token = bot_token
        self.user_id = user_id

    def send_message(self, message: str) -> dict:
        """Send message to Telegram

        Args:
            message (str): message to send

        Returns:
            dict: response json data
        """
        api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        body = {"chat_id": self.user_id, "text": message}
        response = requests.request("POST", api_url, json=body)
        resp_json = response.json()
        if not resp_json["ok"]:
            raise ConnectionError(
                "Error when send message to {}: {}".format(
                    self.user_id, resp_json["description"]
                )
            )
        return response.json()


if __name__ == "__main__":
    import config  # 复制一份config到当前目录才能进行测试

    bot_token = config.BOT_TOKEN
    user_id = config.USER_ID
    bot = TelegramBot(bot_token, user_id)
    print(bot.send_message("Hello World!"))
