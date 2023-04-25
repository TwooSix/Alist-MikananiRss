import requests
import os
import mimetypes


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
        api_url = f"https://{self.domain}/api/auth/login"
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
        api_url = f"https://{self.domain}/api/fs/add_aria2"
        body = {"path": save_path, "urls": urls}
        response = requests.request("POST", api_url, headers=self.headers, json=body)
        return response.json()

    def upload(self, save_path: str, file_path: str) -> dict:
        """Upload file to Alist

        Args:
            save_path (str): save path start from /
            file (str): file's path

        Returns:
            dict: response json data
        """
        assert self.isLogin, "Please login first"
        api_url = f"https://{self.domain}/api/fs/put"
        file_path = os.path.abspath(file_path)
        file_name = os.path.basename(file_path)
        headers = self.headers.copy()
        mime_type = mimetypes.guess_type(file_name)[0]
        headers["Content-Type"] = mime_type
        headers["Content-Length"] = str(os.path.getsize("save.csv"))
        headers["file-path"] = f"{save_path}/{file_name}"
        with open(file_path, "rb") as f:
            response = requests.put(api_url, headers=headers, data=f)
            return response.json()
