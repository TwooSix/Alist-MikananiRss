from alist_mikananirss.websites import ResourceInfo

from . import BotBase


class NotificationMsg:
    """The class to generate notification message"""

    def __init__(self) -> None:
        self._update_info: dict[str, list] = {}
        self.msg = None

    def format_message(self):
        if not self._update_info:
            return "暂无番剧更新"

        msg = "你订阅的番剧"
        for name, titles in self._update_info.items():
            msg += f"<b>[{name}]</b>, "
        msg = msg.rstrip(", ") + " 更新啦：\n"

        for name, titles in self._update_info.items():
            msg += f"<b>[{name}]</b>:\n"
            for title in titles:
                msg += f"{title}\n"
            msg += "\n"
        return msg

    def __bool__(self):
        return bool(self._update_info)

    def __str__(self):
        if not self.msg:
            self.msg = self.format_message()
        return self.msg

    def update(self, anime_name: str, titles: list[str]):
        """update anime update info

        Args:
            anime_name (str): the downloaded anime name
            titles (list[str]): the downloaded resources' title of the anime
        """
        if anime_name not in self._update_info.keys():
            self._update_info[anime_name] = []
        self._update_info[anime_name].extend(titles)

        self.msg = None

    @classmethod
    def from_resources(cls, resources: list[ResourceInfo]):
        """Generate NotificationMsg from resources

        Args:
            resources (list[MikanAnimeResource]): the downloaded resources

        Returns:
            NotificationMsg: the NotificationMsg instance
        """
        msg = cls()
        for resource in resources:
            msg.update(resource.anime_name, [resource.resource_title])
        return msg


class NotificationBot:
    def __init__(self, bot_handler: BotBase):
        self.bot = bot_handler

    async def send_message(self, msg: NotificationMsg):
        return await self.bot.send_message(str(msg))
