import mimetypes
import os
import urllib.parse

import requests


class Alist:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like"
            " Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.39"
        ),
        "Content-Type": "application/json",
    }
    isLogin = False

    def __init__(self, domain: str) -> None:
        self.domain = domain
        self.protocol = self._init_protocol(domain)
        self.prefix = self._init_prefix(self.protocol, domain)

    def _init_protocol(self, domain: str) -> str:
        if domain.startswith("localhost") or domain.startswith("127.0.0.1"):
            protocol = "http"
            return protocol
        else:
            protocol = "https"
            return protocol

    def _init_prefix(self, protocol: str, domain: str) -> str:
        prefix = f"{protocol}://{domain}/"
        return prefix

    def login(self, username: str, password: str) -> dict:
        """Login to Alist and get authorization token

        Args:
            username (str): username
            password (str): password

        Raises:
            ConnectionError: Error if response status code is not 200

        Returns:
            dict: response json data
        """
        api = "api/auth/login"
        api_url = urllib.parse.urljoin(self.prefix, api)
        body = {"username": username, "password": password}

        response = requests.request("POST", api_url, headers=self.headers, json=body)
        if response.status_code != 200:
            raise ConnectionError(
                "Error when login to {}: {}".format(self.domain, response.status_code)
            )
        jsonData = response.json()
        if jsonData["code"] != 200:
            raise ConnectionError(
                "Error when login to {}: {}".format(self.domain, jsonData["message"])
            )

        self.token = jsonData["data"]["token"]
        self.headers["Authorization"] = f"{self.token}"
        self.isLogin = True
        return jsonData

    def add_aria2(self, save_path: str, urls: list[str]) -> dict:
        """Add download task to aria2 queue

        Args:
            save_path (str): save path start from /
            urls (list[str]): download urls

        Returns:
            dict: response json data
        """
        assert self.isLogin, "Please login first"
        api = "api/fs/add_aria2"
        api_url = urllib.parse.urljoin(self.prefix, api)
        body = {"path": save_path, "urls": urls}
        response = requests.request("POST", api_url, headers=self.headers, json=body)

        json_data = response.json()
        if json_data["code"] != 200:
            raise ConnectionError(
                "Error when add aria2 tasks to {}: {}".format(
                    self.domain, json_data["message"]
                )
            )

        return json_data

    def upload(self, save_path: str, file_path: str) -> dict:
        """Upload file to Alist

        Args:
            save_path (str): Server file save path
            file_path (str): Local file's path

        Returns:
            dict: response json data
        """
        assert self.isLogin, "Please login first"
        api = "api/fs/put"
        api_url = urllib.parse.urljoin(self.prefix, api)
        file_path = os.path.abspath(file_path)
        file_name = os.path.basename(file_path)
        # use utf-8 encoding to avoid UnicodeEncodeError
        file_path = file_path.encode("utf-8")

        # add headers
        headers = self.headers.copy()
        mime_type = mimetypes.guess_type(file_name)[0]
        headers["Content-Type"] = mime_type
        file_stat = os.stat(file_path)
        headers["Content-Length"] = str(file_stat.st_size)
        # use URL encoding
        upload_path = urllib.parse.quote(f"{save_path}/{file_name}")
        headers["file-path"] = upload_path

        with open(file_path, "rb") as f:
            response = requests.put(api_url, headers=headers, data=f)

        json_data = response.json()
        if json_data["code"] != 200:
            raise ConnectionError(
                "Error when upload to {}: {}".format(self.domain, json_data["message"])
            )

        return json_data
