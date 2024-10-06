from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alist_mikananirss.bot.pushplus_bot import PushPlusBot, PushPlusChannel


@pytest.fixture
def pushplus_bot():
    return PushPlusBot(user_token="test_token")


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_pushplus_bot_send_message(mock_post, pushplus_bot):
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value.__aenter__.return_value = mock_response
    mock_response.json = AsyncMock(return_value={"code": 200})

    message = "Test message"
    result = await pushplus_bot.send_message(message)

    assert result is True
    mock_post.assert_called_once_with(
        "http://www.pushplus.plus/send/test_token",
        json={
            "title": "Alist MikananiRSS更新推送",
            "content": message,
            "channel": PushPlusChannel.WECHAT.value,
            "template": "html",
        },
    )
    mock_response.raise_for_status.assert_called_once()


def test_pushplus_bot_invalid_channel():
    with pytest.raises(ValueError):
        PushPlusBot(user_token="test_token", channel="invalid_channel")


@pytest.mark.parametrize(
    "channel",
    [
        PushPlusChannel.WECHAT,
        PushPlusChannel.WEBHOOK,
        PushPlusChannel.CP,
        PushPlusChannel.MAIL,
    ],
)
def test_pushplus_bot_valid_channels(channel):
    bot = PushPlusBot(user_token="test_token", channel=channel.value)
    assert bot.channel == channel
