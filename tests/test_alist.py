import pytest
import pytest_asyncio

from core.alist import Alist
from core.common import config_loader

if config_loader.get_use_proxy():
    import os

    proxies = config_loader.get_proxies()
    if "http" in proxies:
        os.environ["HTTP_PROXY"] = proxies["http"]
    if "https" in proxies:
        os.environ["HTTPS_PROXY"] = proxies["https"]


class TestAlist:
    @pytest.fixture
    def alist_info(self):
        envs = {
            "base_url": config_loader.get_base_url(),
            "username": config_loader.get_user_name(),
            "password": config_loader.get_password(),
            "downloader": config_loader.get_downloader(),
        }
        return envs

    @pytest.fixture
    def remote_path(self):
        remote_path = config_loader.get_download_path()
        return remote_path

    @pytest_asyncio.fixture
    async def alist(self, alist_info):
        alist = await Alist.create(alist_info["base_url"], alist_info["downloader"])
        await alist.login(alist_info["username"], alist_info["password"])
        return alist

    @pytest.mark.asyncio
    async def test_login(self, alist: Alist):
        username = config_loader.get_user_name()
        password = config_loader.get_password()
        await alist.login(username, password)

    @pytest.mark.asyncio
    async def test_add_offline_download_task(self, alist: Alist, remote_path):
        urls = [
            "https://releases.ubuntu.com/20.04/ubuntu-20.04.6-live-server-amd64.iso.torrent"
        ]
        await alist.add_offline_download_task(remote_path, urls)

    @pytest.mark.asyncio
    async def test_get_offline_download_task(self, alist: Alist):
        await alist.get_offline_download_task_list()

    @pytest.mark.asyncio
    async def test_get_offline_transfer_task(self, alist: Alist):
        await alist.get_offline_transfer_task_list()

    @pytest.mark.asyncio
    async def test_upload(self, alist: Alist, remote_path):
        test_file = "./tests/test_upload.txt"
        result = await alist.upload(remote_path, test_file)
        assert result is True

    @pytest.mark.asyncio
    async def test_list_dir(self, alist: Alist, remote_path):
        await alist.list_dir(remote_path)
