import pytest

import config
from core.api import Alist


class TestAlistApi:
    @pytest.fixture
    def login_info(self):
        envs = {
            "base_url": config.BASE_URL,
            # domain = "www.example.com",
            "username": config.USER_NAME,
            "password": config.PASSWORD,
        }
        return envs

    @pytest.fixture
    def remote_path(self):
        remote_path = config.DOWNLOAD_PATH
        return remote_path

    @pytest.fixture
    def alist(self, login_info):
        alist = Alist(login_info["base_url"])
        alist.login(login_info["username"], login_info["password"])
        return alist

    @pytest.fixture
    def mikanani_base_url(self):
        base_url = "mikanani.me"
        # base_url = "mikanime.tv"
        return base_url

    def test_alist_add_aria2_task(self, alist, remote_path, mikanani_base_url):
        torrent_url = "https://i0.hdslb.com/bfs/new_dyn/074e73f8a47df3a26e1b9af8ec75364d512995925.jpg"  # About 250KB
        alist.add_aria2(remote_path, [torrent_url])

    def test_alsit_upload(self, alist, remote_path):
        test_file = "./tests/test_upload.txt"
        alist.upload(remote_path, test_file)
