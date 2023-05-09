from core.api import Alist
from core.api import TelegramBot


class TestAlistApi:
    domain = "localhost:5244"
    # domain = "www.example.com"
    username = "test"
    password = "test"
    test_path = "/test"

    def test_alist_login(self):
        alist = Alist(self.domain)
        resp_json = alist.login(self.username, self.password)
        assert resp_json["code"] == 200

    def test_alist_add_aria2_task(self):
        torrent_url = "magnet:?xt=urn:btih:af9edbcb71798164bf4ffd362f527d35fbeb1545&tr=http%3a%2f%2ft.nyaatracker.com%2fannounce&tr=http%3a%2f%2ftracker.kamigami.org%3a2710%2fannounce&tr=http%3a%2f%2fshare.camoe.cn%3a8080%2fannounce&tr=http%3a%2f%2fopentracker.acgnx.se%2fannounce&tr=http%3a%2f%2fanidex.moe%3a6969%2fannounce&tr=http%3a%2f%2ft.acg.rip%3a6699%2fannounce&tr=https%3a%2f%2ftr.bangumi.moe%3a9696%2fannounce&tr=udp%3a%2f%2ftr.bangumi.moe%3a6969%2fannounce&tr=http%3a%2f%2fopen.acgtracker.com%3a1096%2fannounce&tr=udp%3a%2f%2ftracker.opentrackr.org%3a1337%2fannounce"

        alist = Alist(self.domain)
        alist.login(self.username, self.password)

        resp_json = alist.add_aria2(self.test_path, [torrent_url])
        assert resp_json["code"] == 200

    def test_alsit_upload(self):
        test_file = "./tests/test_upload.txt"
        alist = Alist(self.domain)
        alist.login(self.username, self.password)
        resp_json = alist.upload(self.test_path, test_file)
        assert resp_json["code"] == 200


class TestTelegramApi:
    bot_token = ""
    chat_id = ""

    def test_telegram_send_message(self):
        telegram = TelegramBot(self.bot_token, self.chat_id)
        resp_json = telegram.send_message("test")
        assert resp_json["ok"]
