import mimetypes
import os
import urllib.parse

import requests

from core.alist.offline_download import (
    DeletePolicy,
    DownloaderType,
    DownloadTask,
    TaskList,
    TransferTask,
)


class Alist:
    UNLOGGING_MSG = "Please login first"

    def __init__(self, base_url: str, downloader: DownloaderType) -> None:
        self.base_url = base_url
        self.is_login = False
        self.downloader = downloader
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
                " like Gecko) Chrome/112.0.0.0 Safari/537.36 Edg/112.0.1722.39"
            ),
            "Content-Type": "application/json",
        }
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
        response = requests.get(api_url)
        response.raise_for_status()
        self.version = response.json()["data"]["version"][1:]  # 去掉字母v

    def login(self, username: str, password: str) -> tuple[bool, str]:
        """Login to Alist and get authorization token"""
        api_url = urllib.parse.urljoin(self.base_url, "api/auth/login")
        body = {"username": username, "password": password}
        try:
            response = requests.post(api_url, headers=self.headers, json=body)
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
        if not self.is_login:
            return False, self.UNLOGGING_MSG
        # alist author rebuild the offdownload api in version 3.29.0
        if self.version < "3.29.0":
            api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_aria2")
            body = {
                "path": save_path,
                "urls": urls,
            }
        else:
            api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_offline_download")
            body = {
                "delete_policy": DeletePolicy.DeleteOnUploadSucceed.value,
                "path": save_path,
                "urls": urls,
                "tool": self.downloader.value,
            }

        try:
            response = requests.post(api_url, headers=self.headers, json=body)
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

    def add_qbit(self, save_path: str, urls: list[str]) -> tuple[bool, str]:
        if not self.is_login:
            return False, self.UNLOGGING_MSG
        # alist author rebuild the offdownload api in version 3.29.0
        if self.version < "3.29.0":
            api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_qbit")
            body = {
                "path": save_path,
                "urls": urls,
            }
        else:
            api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_offline_download")
            body = {
                "delete_policy": DeletePolicy.DeleteOnUploadSucceed.value,
                "path": save_path,
                "urls": urls,
                "tool": self.downloader.value,
            }

        try:
            response = requests.post(api_url, headers=self.headers, json=body)
            self.__get_json_data(response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                (
                    "Connection error during adding qbit task, please check your"
                    f" network: {e}"
                ),
            )
        except Exception as e:
            return False, f"Error occur during adding qbit task: {e}"

        return True, "Task added successfully"

    def add_offline_download(self, save_path: str, urls: list[str]) -> tuple[bool, str]:
        if self.downloader == DownloaderType.ARIA:
            return self.add_aria2(save_path, urls)
        elif self.downloader == DownloaderType.QBIT:
            return self.add_qbit(save_path, urls)

    def upload(self, save_path: str, file_path: str) -> tuple[bool, str]:
        """Upload file to Alist

        Args:
            save_path (str): Server file save path
            file_path (str): Local file's path

        Returns:
            tuple[bool, str]: (status, msg)
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
                resp = requests.put(api_url, headers=headers, data=f)
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
            tuple[bool, str|list]: (status, msg|files_list)
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
            response = requests.post(api_url, headers=self.headers, json=body)
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

    def __get_task_list(self, task_type: str, status: str) -> tuple[bool, TaskList]:
        """Get download task list.

        Args:
            task_type (str): download | transfer
            status (str): done | undone

        Returns:
            Tuple[bool, List[Task]]: Success flag and a list of Tasks.
        """
        if not self.is_login:
            return False, self.UNLOGGING_MSG

        # Mapping of type and web pages based on version and downloader.
        web_page_mapping = {
            "download": {
                "new_api": "offline_download",
                "aria2": "aria2_down",
                "qBittorrent": "qbit_down",
            },
            "transfer": {
                "new_api": "offline_download_transfer",
                "aria2": "aria2_transfer",
                "qBittorrent": "qbit_transfer",
            },
        }

        # Determine the web page based on type, version, and downloader.
        web_page = web_page_mapping.get(task_type, {}).get(
            "new_api" if self.version >= "3.29.0" else self.downloader.value
        )

        if not web_page:
            return False, f"Invalid type: {task_type}"

        api_url = urllib.parse.urljoin(
            self.base_url, f"/api/admin/task/{web_page}/{status}"
        )

        # Get task list
        try:
            resp = requests.get(api_url, headers=self.headers)
            json_data = self.__get_json_data(resp)
        except requests.exceptions.ConnectionError as e:
            return False, f"Connection error: {e}"
        except Exception as e:
            return False, f"Error: {e}"

        # Parse task list
        if task_type == "transfer":
            if json_data:
                tmp_task_list = [TransferTask.from_json(task) for task in json_data]
            else:
                tmp_task_list = []
            task_list = TaskList(tmp_task_list)
        else:
            if json_data:
                tmp_task_list = [DownloadTask.from_json(task) for task in json_data]
            else:
                tmp_task_list = []
            task_list = TaskList(tmp_task_list)
        return True, task_list

    def get_offline_download_task_list(self) -> tuple[bool, TaskList]:
        flag1, done_task_list = self.__get_task_list("download", "done")
        flag2, undone_task_list = self.__get_task_list("download", "undone")
        if not flag1 or not flag2:
            return False, "Error occur during get offline download task list"
        task_list = done_task_list + undone_task_list
        return True, task_list

    def get_offline_transfer_task_list(self) -> tuple[bool, TaskList]:
        flag1, done_task_list = self.__get_task_list("transfer", "done")
        flag2, undone_task_list = self.__get_task_list("transfer", "undone")
        if not flag1 or not flag2:
            return False, "Error occur during get offline transfer task list"
        task_list = done_task_list + undone_task_list
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
            response = requests.post(api_url, headers=self.headers, json=body)
            self.__get_json_data(response)
        except requests.exceptions.ConnectionError as e:
            return (
                False,
                f"Connection error during rename, please check your network: {e}",
            )
        except Exception as e:
            return False, f"Error occur during rename: {e}"

        return True, ""
