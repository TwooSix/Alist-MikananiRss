from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from alist_mikananirss.bot.tgbot import TelegramBot


@pytest.fixture
def telegram_bot():
    return TelegramBot(bot_token="test_token", user_id="test_user_id")


@pytest.mark.asyncio
@patch("aiohttp.ClientSession.post")
async def test_telegram_bot_send_message(mock_post, telegram_bot):
    mock_response = AsyncMock()
    mock_response.raise_for_status = MagicMock()
    mock_post.return_value.__aenter__.return_value = mock_response

    message = "Test message"
    result = await telegram_bot.send_message(message)

    assert result is True
    mock_post.assert_called_once_with(
        "https://api.telegram.org/bottest_token/sendMessage",
        json={"chat_id": "test_user_id", "text": message, "parse_mode": "HTML"},
    )
    mock_response.raise_for_status.assert_called_once()
