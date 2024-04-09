import os
from unittest.mock import AsyncMock

import pytest
from alist_mikananirss.mikan import MikanAnimeResource
from alist_mikananirss.renamer import Renamer


@pytest.fixture
def mock_alist():
    # 创建一个模拟的Alist实例
    alist = AsyncMock()
    alist.rename = AsyncMock(return_value=True)
    alist.list_dir = AsyncMock(return_value=[])
    return alist


@pytest.fixture
def download_path(tmp_path):
    # 创建一个临时下载路径
    return str(tmp_path)


@pytest.fixture
def resource():
    return MikanAnimeResource(
        rid="123",
        name="Fake Anime",
        season=2,
        torrent_url="http://example.com/file.torrent",
        published_date="2021-01-01",
        resource_title="Fake Resource",
        episode=9,
    )


@pytest.mark.asyncio
async def test_build_new_name(mock_alist, resource, download_path):
    renamer = Renamer(mock_alist, download_path)

    local_title = "[Fake Anime][09].mp4"
    expected_new_name = "Fake Anime S02E09.mp4"
    new_name = await renamer._Renamer__build_new_name(resource, local_title)
    assert new_name == expected_new_name


@pytest.mark.asyncio
async def test_rename(mock_alist, resource, download_path):
    # 创建一个Renamer实例
    renamer = Renamer(mock_alist, download_path)

    # 创建一个模拟的资源
    local_title = "[Fake Anime][09].mp4"
    new_name = "Fake Anime S02E09.mp4"

    # 模拟alist.list_dir返回空列表（代表没有其他文件）
    mock_alist.list_dir.return_value = []

    # 调用rename方法
    await renamer.rename(local_title, resource)
    # 构建期望的文件路径和新名称
    expected_filepath = os.path.join(
        download_path, "Fake Anime", "Season 2", local_title
    )
    expected_new_name = new_name

    # 验证是否调用了alist.rename方法，并检查参数
    mock_alist.rename.assert_called_once_with(expected_filepath, expected_new_name)
