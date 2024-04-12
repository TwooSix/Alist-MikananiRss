import pytest
from aioresponses import aioresponses
from alist_mikananirss.alist.api import Alist


@pytest.fixture
def alist_client():
    # 创建 Alist 实例
    return Alist(base_url="http://fake-url.com", downloader="aria2", token="fake-token")


@pytest.fixture
def mock_aioresponse():
    with aioresponses() as m:
        yield m


@pytest.mark.asyncio
async def test_get_alist_ver(alist_client, mock_aioresponse):
    mock_aioresponse.get(
        "http://fake-url.com/api/public/settings",
        payload={"code": 200, "data": {"version": "v1.0.0"}},
    )

    version = await alist_client.get_alist_ver()
    assert version == "1.0.0"


@pytest.mark.asyncio
async def test_add_offline_download_task(alist_client: Alist, mock_aioresponse):
    torrent_url = "http://example.com/file"
    download_path = "/save/path"
    mock_aioresponse.post(
        "http://fake-url.com/api/fs/add_offline_download",
        payload={
            "code": 200,
            "data": {
                "tasks": [
                    {
                        "error": "",
                        "id": "123",
                        "name": f"download {torrent_url} to ({download_path})",
                        "progress": 0,
                        "state": 0,
                        "status": "",
                    }
                ]
            },
            "message": "success",
        },
    )

    task_list = await alist_client.add_offline_download_task(
        download_path, [torrent_url]
    )
    assert len(task_list) == 1
    assert task_list[0].tid == "123"
    assert task_list[0].url == torrent_url


@pytest.mark.asyncio
async def test_list_dir(alist_client: Alist, mock_aioresponse):
    mock_aioresponse.post(
        "http://fake-url.com/api/fs/list",
        payload={
            "code": 200,
            "message": "success",
            "data": {
                "content": [
                    {
                        "name": "m",
                        "size": 0,
                        "is_dir": True,
                        "modified": "2023-07-19T09:48:13.695585868+08:00",
                        "sign": "",
                        "thumb": "",
                        "type": 1,
                    }
                ],
                "total": 1,
                "readme": "",
                "write": True,
                "provider": "unknown",
            },
        },
    )

    file_list = await alist_client.list_dir("/")
    assert file_list[0] == "m"


@pytest.mark.asyncio
async def test_rename(alist_client: Alist, mock_aioresponse):
    mock_aioresponse.post(
        "http://fake-url.com/api/fs/rename",
        payload={"code": 200, "message": "success", "data": None},
    )

    res = await alist_client.rename("1", "2")
    assert res
