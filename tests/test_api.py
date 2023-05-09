import pytest

from core.api import Alist
from core.api import TelegramBot


class TestAlistApi:
    @pytest.fixture
    def login_info(self):
        envs = {
            "domain": "localhost:5244",
            # domain = "www.example.com",
            "username": "test",
            "password": "test",
        }
        return envs

    @pytest.fixture
    def remote_path(self):
        remote_path = "/test"
        return remote_path

    @pytest.fixture
    def alist(self, login_info):
        alist = Alist(login_info["domain"])
        resp_json = alist.login(login_info["username"], login_info["password"])
        assert resp_json["code"] == 200
        return alist

    @pytest.fixture
    def mikanani_base_url(self):
        base_url = "mikanani.me"
        # base_url = "mikanime.tv"
        return base_url

    def test_alist_add_aria2_task(self, alist, remote_path, mikanani_base_url):
        torrent_url = f"https://{mikanani_base_url}/Download/20230419/af9edbcb71798164bf4ffd362f527d35fbeb1545.torrent"
        resp_json = alist.add_aria2(remote_path, [torrent_url])
        assert resp_json["code"] == 200

    def test_alsit_upload(self, alist, remote_path):
        test_file = "./tests/test_upload.txt"
        resp_json = alist.upload(remote_path, test_file)
        assert resp_json["code"] == 200


class TestTelegramApi:
    @pytest.fixture
    def tele_info(self):
        tele_info = {
            "BotToken": "",
            "ChatID": "",
        }
        return tele_info

    def test_telegram_send_message(self, tele_info):
        telegram = TelegramBot(tele_info["BotToken"], tele_info["ChatID"])
        resp_json = telegram.send_message("test")
        assert resp_json["ok"]
