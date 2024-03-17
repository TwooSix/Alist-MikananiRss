import os
from unittest.mock import MagicMock

import pytest

from core.downloader import AlistDownloader
from core.mikan import MikanAnimeResource


class TestsAlistDonwloader:
    @pytest.fixture
    def downloader(self):
        mock_alist = MagicMock()
        return AlistDownloader(alist=mock_alist, use_renamer=True)

    @pytest.fixture
    def download_path(self):
        return "/save/path"

    @pytest.fixture
    def res(self):
        return MikanAnimeResource(
            rid="123",
            name="Fake Anime",
            season="2",
            torrent_url="http://example.com/file.torrent",
            published_date="2021-01-01",
            resource_title="Fake Resource",
        )

    @pytest.mark.asyncio
    async def test_download_path(
        self, downloader: AlistDownloader, res: MikanAnimeResource, download_path
    ):
        path_urls = downloader._AlistDownloader__prepare_download([res], download_path)
        real_path = os.path.join("/save/path", "Fake Anime", "Season 2")
        print(path_urls)
        assert path_urls[real_path] == [res.torrent_url]
