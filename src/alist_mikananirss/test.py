from alist_mikananirss.bot import PushPlusBot, NotificationMsg, NotificationBot
from alist_mikananirss.common import initializer
import asyncio

async def main():
    bots = initializer.init_notification_bots()

    msg = NotificationMsg()
    msg.update(
        "name1", ["[fansub1][title1][1][1080p]", "[fansub2][title2][2][1080p]"]
    )
    msg.update(
        "name2", ["[fansub1][title3] 1 [1080p]", "[fansub2] [title4] 2 [1080p]"]
    )

    for bot in bots:
        res = await bot.send_message(msg)
        assert res

if __name__ == '__main__':
    asyncio.run(main())