import pytest
import pytest_asyncio

from core.alist import Alist
from core.common import initializer
from core.common.config_loader import ConfigLoader

initializer.setup_proxy()
config_loader = ConfigLoader("config.yaml")


class TestAlist:
    @pytest.fixture
    def remote_path(self):
        remote_path = config_loader.get("alist.download_path")
        return remote_path

    @pytest_asyncio.fixture
    async def alist(self):
        alist = await initializer.init_alist()
        user_name = config_loader.get("alist.user_name")
        password = config_loader.get("alist.password")
        await alist.login(user_name, password)
        return alist

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
