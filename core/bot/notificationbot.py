from . import BotBase, MsgType


class NotificationMsg:
    def __init__(self) -> None:
        self._update_info: dict[str, list] = {}
        self._markdown_msg = None
        self._normal_msg = None

    def format_message(self, markdown=False):
        if not self._update_info:
            return "暂无番剧更新"
        update_anime_list = []
        msg_format = "*[{}]*" if markdown else "[{}]"

        for name in self._update_info.keys():
            update_anime_list.append(msg_format.format(name))

        anime_name_str = ", ".join(update_anime_list)
        msg = f"你订阅的番剧 {anime_name_str} 更新啦\n"

        if markdown:
            # to avoid that [] can't be displayed in markdown
            for name in self._update_info.keys():
                for i in range(len(self._update_info[name])):
                    title = self._update_info[name][i]
                    if "[" in title[0]:
                        self._update_info[name][i] = title.replace("[", "\\[")

        for name, titles in self._update_info.items():
            msg += f"{msg_format.format(name)}:\n"
            msg += "\n".join(titles)
            msg += "\n\n"

        return msg

    def __bool__(self):
        return bool(self._update_info)

    @property
    def markdown_msg(self):
        if not self._markdown_msg:
            self._markdown_msg = self.format_message(markdown=True)
        return self._markdown_msg

    @property
    def normal_msg(self):
        if not self._normal_msg:
            self._normal_msg = self.format_message(markdown=False)
        return self._normal_msg

    def update(self, anime_name: str, titles: list[str]):
        """update anime update info

        Args:
            anime_name (str): the downloaded anime name
            titles (list[str]): the downloaded resources' title of the anime
        """
        if anime_name not in self._update_info.keys():
            self._update_info[anime_name] = []
        self._update_info[anime_name].extend(titles)

        self._markdown_msg = None
        self._normal_msg = None


class NotificationBot:
    def __init__(self, bot_handler: BotBase):
        self.bot = bot_handler

    def send_message(self, msg: NotificationMsg):
        if self.bot.message_type == MsgType.NORMAL:
            return self.bot.send_message(msg.normal_msg)
        elif self.bot.message_type == MsgType.MARKDOWN:
            return self.bot.send_message(msg.markdown_msg)
