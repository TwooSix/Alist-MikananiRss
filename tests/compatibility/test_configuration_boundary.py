from openlist_ani.adapters.configuration import compile_core_settings
from openlist_ani.adapters.configuration.models import UserConfig
from openlist_ani.adapters.configuration.writer import update_rss_urls


def test_legacy_metadata_config_compiles_to_provider_order():
    config = UserConfig.model_validate(
        {
            "metadata_parser": {"provider": "regex"},
            "metadata_validator": {"provider": "tmdb"},
        }
    )

    assert compile_core_settings(config).metadata_providers == ("regex", "tmdb")


def test_new_metadata_provider_list_overrides_legacy_config():
    config = UserConfig.model_validate(
        {
            "metadata": {"providers": ["llm", "tmdb"]},
            "metadata_parser": {"provider": "regex"},
            "metadata_validator": {"provider": "none"},
        }
    )

    assert compile_core_settings(config).metadata_providers == ("ai", "tmdb")


def test_rss_update_preserves_unrelated_comments(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text(
        "# keep this comment\n[rss]\n# feeds comment\nurls = []\n\n"
        '[openlist]\nurl = "https://example.test"\n',
        encoding="utf-8",
    )

    update_rss_urls(path, ["https://example.test/rss"])

    content = path.read_text(encoding="utf-8")
    assert "# keep this comment" in content
    assert "# feeds comment" in content
    assert 'url = "https://example.test"' in content
    assert '"https://example.test/rss"' in content
