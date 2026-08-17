from __future__ import annotations

from io import StringIO

import openlist_ani.logger as logger_module


def test_sensitive_values_are_redacted_from_log_text():
    message = (
        "proxy=http://user:password@example.com:8080 "
        "rss=https://mikan.example/rss?token=secret "
        "tmdb=https://api.themoviedb.org/search?api_key=tmdb-secret "
        "telegram=https://api.telegram.org/bot123456:secret/sendMessage"
    )

    sanitized = logger_module.sanitize_for_log(message)

    assert "password" not in sanitized
    assert "secret" not in sanitized
    assert "token=<redacted>" in sanitized
    assert "api_key=<redacted>" in sanitized
    assert "bot<redacted>" in sanitized


def test_logger_redacts_before_writing(monkeypatch, tmp_path):
    sink = StringIO()
    monkeypatch.setattr(logger_module, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger_module, "stdout", sink)
    logger_module.configure_logger(level="INFO", log_name="test", file_logging=False)
    try:
        logger_module.logger.info(
            "fetch failed: https://example.com/rss?token=plain-secret"
        )
    finally:
        logger_module.configure_logger()

    assert "plain-secret" not in sink.getvalue()
    assert "token=<redacted>" in sink.getvalue()
