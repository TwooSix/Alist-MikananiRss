import mimetypes
import os
import urllib.parse

import requests
from loguru import logger

import config


class Alist:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like"
            " Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.39"
        ),
        "Content-Type": "application/json",
    }
    proxies = getattr(config, "PROXIES", None)

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.is_login = False
        self.__get_alist_ver()

    def __get_alist_ver(self) -> str:
        api_url = urllib.parse.urljoin(self.base_url, "/api/public/settings")
        response = requests.get(api_url, proxies=self.proxies)
        response.raise_for_status()
        self.version = response.json()["data"]["version"]

    def login(self, username: str, password: str) -> dict:
        """Login to Alist and get authorization token"""
        api_url = urllib.parse.urljoin(self.base_url, "api/auth/login")
        body = {"username": username, "password": password}

        response = requests.post(
            api_url, headers=self.headers, json=body, proxies=self.proxies
        )

        response.raise_for_status()

        jsonData = response.json()

        if jsonData["code"] != 200:
            error_message = jsonData.get(
                "message", f"Unknonw error when login to {self.base_url} "
            )
            raise ConnectionError(error_message)

        self.token = jsonData["data"]["token"]
        self.headers["Authorization"] = self.token
        self.is_login = True

        return jsonData

    def add_aria2(self, save_path: str, urls: list[str]) -> dict:
        """Add download task to aria2 queue

        Args:
            save_path (str): save path starting from /
            urls (list[str]): download URLs

        Returns:
            dict: response JSON data
        """
        assert self.is_login, "Please login first"
        if self.version < "3.29.0":
            api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_aria2")
            body = {
                "path": save_path,
                "urls": urls,
            }
            logger.warning(
                "api/fs/add_aria2 has been deprecated, please update Alist to 3.29.0+"
            )
        else:
            api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_offline_download")
            body = {
                "delete_policy": "delete_never",
                "path": save_path,
                "urls": urls,
                "tool": "aria2",
            }
        response = requests.post(
            api_url, headers=self.headers, json=body, proxies=self.proxies
        )
        response.raise_for_status()
        json_data = response.json()

        if json_data["code"] != 200:
            error_message = json_data.get(
                "message", f"Unknonw error when adding aria2 tasks to {self.base_url}"
            )
            raise ConnectionError(error_message)

        return json_data

    def upload(self, save_path: str, file_path: str) -> dict:
        """Upload file to Alist

        Args:
            save_path (str): Server file save path
            file_path (str): Local file's path

        Returns:
            dict: response JSON data
        """
        assert self.is_login, "Please login first"

        api_url = urllib.parse.urljoin(self.base_url, "api/fs/put")
        file_path = os.path.abspath(file_path)
        file_name = os.path.basename(file_path)

        # Use utf-8 encoding to avoid UnicodeEncodeError
        file_path_encoded = file_path.encode("utf-8")

        # Create headers
        headers = self.headers.copy()
        mime_type = mimetypes.guess_type(file_name)[0]
        headers["Content-Type"] = mime_type
        file_stat = os.stat(file_path)
        headers["Content-Length"] = str(file_stat.st_size)

        # Use URL encoding
        upload_path = urllib.parse.quote(f"{save_path}/{file_name}")
        headers["file-path"] = upload_path

        with open(file_path_encoded, "rb") as f:
            response = requests.put(
                api_url, headers=headers, data=f, proxies=self.proxies
            )

        json_data = response.json()

        if json_data["code"] != 200:
            error_message = json_data.get(
                "message", f"Unknonw error when uploading to {self.base_url}"
            )
            raise ConnectionError(error_message)

        return json_data
