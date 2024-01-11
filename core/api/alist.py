import mimetypes
import os
import re
import urllib.parse
from enum import Enum

import requests
from loguru import logger


class Aria2TaskStatus(Enum):
    DOWNLOADING = 1
    TRANSFERRING = 2
    WAITING = 3
    DONE = 4
    ERROR = 5
    UNKNOWN = 6


class Aria2Task:
    def __init__(self, id, url, status, error_msg=None) -> None:
        self.id = id
        self.url = url
        self.status = status
        self.error_msg = error_msg

    @classmethod
    def from_json(cls, json_data):
        name = json_data["name"]
        pattern = r"download\s+(.+?)\s+to"
        match = re.match(pattern, name)
        if match:
            url = match.group(1)
        else:
            raise ValueError(f"Invalid task name: {name}")
        tid = json_data["id"]
        state = json_data["state"]
        status_str = json_data["status"]
        error_str = json_data["error"]
        if state == "running":
            if "transferring" in status_str:
                status = Aria2TaskStatus.TRANSFERRING
            else:
                status = Aria2TaskStatus.DOWNLOADING
        elif state == "succeeded":
            status = Aria2TaskStatus.DONE
        elif state == "pending":
            status = Aria2TaskStatus.WAITING
        elif error_str:
            status = Aria2TaskStatus.ERROR
        else:
            status = Aria2TaskStatus.UNKNOWN
        return cls(tid, url, status, error_str)


class Alist:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like"
            " Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.39"
        ),
        "Content-Type": "application/json",
    }
    UNLOGGING_MSG = "Please login first"

    def __init__(self, base_url: str, proxies=None) -> None:
        self.base_url = base_url
        self.is_login = False
        self.proxies = proxies
        self.__init_alist_ver()

    def __get_json_data(self, response: requests.Response) -> dict:
        """Get JSON data from response

        Args:
            response (requests.Response): Response object

        Returns:
            dict: JSON data
        """
        response.raise_for_status()
        json_data = response.json()
        if json_data["code"] != 200:
            msg = json_data.get("message", "Unknown error")
            raise requests.exceptions.HTTPError(
                f"Error code: {json_data['code']}: {msg}"
            )
        return json_data["data"]

    def __init_alist_ver(self):
        api_url = urllib.parse.urljoin(self.base_url, "/api/public/settings")
        response = requests.get(api_url, proxies=self.proxies)
        response.raise_for_status()
        self.version = response.json()["data"]["version"][1:]  # 去掉字母v

    def login(self, username: str, password: str) -> tuple[bool, str]:
        """Login to Alist and get authorization token"""
        api_url = urllib.parse.urljoin(self.base_url, "api/auth/login")
        body = {"username": username, "password": password}
        try:
            response = requests.post(
                api_url, headers=self.headers, json=body, proxies=self.proxies
            )
            json_data = self.__get_json_data(response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                f"Connection error during login, please check your network: {e}",
            )
        except Exception as e:
            return False, f"Error occur during login: {e}"

        self.token = json_data["token"]
        self.headers["Authorization"] = self.token
        self.is_login = True

        return True, "Login successful"

    def add_aria2(self, save_path: str, urls: list[str]) -> tuple[bool, str]:
        """Add download task to aria2 queue

        Args:
            save_path (str): save path starting from /
            urls (list[str]): download URLs

        Returns:
            dict: response JSON data
        """
        if not self.is_login:
            return False, self.UNLOGGING_MSG

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

        try:
            response = requests.post(
                api_url, headers=self.headers, json=body, proxies=self.proxies
            )
            self.__get_json_data(response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                (
                    "Connection error during adding aria2 task, please check your"
                    f" network: {e}"
                ),
            )
        except Exception as e:
            return False, f"Error occur during adding aria2 task: {e}"

        return True, "Task added successfully"

    def upload(self, save_path: str, file_path: str) -> tuple[bool, str]:
        """Upload file to Alist

        Args:
            save_path (str): Server file save path
            file_path (str): Local file's path

        Returns:
            dict: response JSON data
        """
        if not self.is_login:
            return False, self.UNLOGGING_MSG

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
            try:
                resp = requests.put(
                    api_url, headers=headers, data=f, proxies=self.proxies
                )
                self.__get_json_data(resp)
            except requests.exceptions.ConnectionError as e:
                return (
                    False,
                    f"Connection error during upload, please check your network: {e}",
                )
            except Exception as e:
                return False, f"Error occur during upload: {e}"

        return True, "File uploaded successfully"

    def list_dir(self, path, password=None, page=1, per_page=30, refresh=False):
        """Upload file to Alist

        Args:
            save_path (str): Server file save path
            file_path (str): Local file's path

        Returns:
            dict: response JSON data
        """
        if not self.is_login:
            return False, self.UNLOGGING_MSG

        api_url = urllib.parse.urljoin(self.base_url, "api/fs/list")
        body = {
            "path": path,
            "password": password,
            "page": page,
            "per_page": per_page,
            "refresh": refresh,
        }

        try:
            response = requests.post(
                api_url, headers=self.headers, json=body, proxies=self.proxies
            )
            json_data = self.__get_json_data(response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                f"Connection error during list dir, please check your network: {e}",
            )
        except Exception as e:
            return False, f"Error occur during list dir: {e}"
        if json_data["content"]:
            files_list = [file_info["name"] for file_info in json_data["content"]]
        else:
            files_list = []
        return True, files_list

    def get_aria2_task_list(self) -> tuple[bool, list[Aria2Task]]:
        if not self.is_login:
            return False, self.UNLOGGING_MSG

        # prepare url
        download_undone_api = "/api/admin/task/aria2_down/undone"
        download_done_api = "/api/admin/task/aria2_down/done"
        download_undone_url = urllib.parse.urljoin(self.base_url, download_undone_api)
        download_done_url = urllib.parse.urljoin(self.base_url, download_done_api)

        # get task list
        try:
            download_undone_response = requests.get(
                download_undone_url, headers=self.headers, proxies=self.proxies
            )
            download_undone_json_data = self.__get_json_data(download_undone_response)
            download_done_response = requests.get(
                download_done_url, headers=self.headers, proxies=self.proxies
            )
            download_done_json_data = self.__get_json_data(download_done_response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                (
                    "Connection error during get aria2 task list, please check your"
                    f" network: {e}"
                ),
            )
        except Exception as e:
            return False, f"Error occur during get aria2 task list: {e}"

        # parse task list
        task_list = []
        if download_undone_json_data:
            for task in download_undone_json_data:
                task_list.append(Aria2Task.from_json(task))
        if download_done_json_data:
            for task in download_done_json_data:
                task_list.append(Aria2Task.from_json(task))
        return True, task_list

    def rename(self, path, new_name):
        if not self.is_login:
            return False, self.UNLOGGING_MSG
        api = "/api/fs/rename"
        api_url = urllib.parse.urljoin(self.base_url, api)
        body = {
            "path": path,
            "name": new_name,
        }

        try:
            response = requests.post(
                api_url, headers=self.headers, json=body, proxies=self.proxies
            )
            self.__get_json_data(response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                f"Connection error during rename, please check your network: {e}",
            )
        except Exception as e:
            return False, f"Error occur during rename: {e}"

        return True, ""
