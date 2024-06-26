import mimetypes
import os
import urllib.parse

import aiohttp

from alist_mikananirss.alist.offline_download import (
    DeletePolicy,
    DownloaderType,
    DownloadTask,
    TaskList,
    TransferTask,
)


class Alist:
    def __init__(
        self, base_url: str, downloader: DownloaderType | str, token: str
    ) -> None:
        self.base_url = base_url
        if isinstance(downloader, str):
            downloader = DownloaderType(downloader)
        self.downloader = downloader
        self.token = token
        self.headers = {
            "User-Agent": "Alist-Mikanirss/v0.0",
            "Content-Type": "application/json",
            "Authorization": token,
        }

    async def __get_json_data(self, response: aiohttp.ClientResponse):
        """Get JSON data from response asynchronously"""
        response.raise_for_status()
        json_data = await response.json()
        if json_data["code"] != 200:
            msg = json_data.get("message", "Unknown error")
            raise aiohttp.ClientResponseError(
                response.request_info,
                response.history,
                status=json_data["code"],
                message=msg,
                headers=response.headers,
            )
        return json_data["data"]

    async def __init_alist_version(self):
        api_url = urllib.parse.urljoin(self.base_url, "/api/public/settings")
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(api_url) as response:
                json_data = await self.__get_json_data(response)
                self.version = json_data["version"][1:]  # 去掉字母v

    async def get_alist_ver(self):
        if not hasattr(self, "version"):
            await self.__init_alist_version()
        return self.version

    async def add_offline_download_task(
        self, save_path: str, urls: list[str]
    ) -> TaskList:
        api_url = urllib.parse.urljoin(self.base_url, "api/fs/add_offline_download")
        body = {
            "delete_policy": DeletePolicy.DeleteOnUploadSucceed.value,
            "path": save_path,
            "urls": urls,
            "tool": self.downloader.value,
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(
                api_url, headers=self.headers, json=body
            ) as response:
                json_data = await self.__get_json_data(response)
        return TaskList([DownloadTask.from_json(task) for task in json_data["tasks"]])

    async def upload(self, save_path: str, file_path: str) -> bool:
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

        async with aiohttp.ClientSession(trust_env=True) as session:
            with open(file_path_encoded, "rb") as f:
                async with session.put(api_url, headers=headers, data=f) as resp:
                    await self.__get_json_data(resp)
        return True

    async def list_dir(
        self, path, password=None, page=1, per_page=30, refresh=False
    ) -> list[str]:
        """List dir.

        Args:
            path (str): dir path
            password (str, optional): dir's password. Defaults to None.
            page (int, optional): page number. Defaults to 1.
            per_page (int, optional): how many item in one page. Defaults to 30.
            refresh (bool, optional): force to refresh. Defaults to False.

        Returns:
            Tuple[bool, List[str]]: Success flag and a list of files in the dir.
        """
        api_url = urllib.parse.urljoin(self.base_url, "api/fs/list")
        body = {
            "path": path,
            "password": password,
            "page": page,
            "per_page": per_page,
            "refresh": refresh,
        }
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(
                api_url, headers=self.headers, json=body
            ) as response:
                json_data = await self.__get_json_data(response)
        if json_data["content"]:
            files_list = [file_info["name"] for file_info in json_data["content"]]
        else:
            files_list = []
        return files_list

    async def __get_task_list(self, task_type: str, status: str) -> TaskList:
        """Get download task list.

        Args:
            task_type (str): download | transfer
            status (str): done | undone

        Returns:
            Tuple[bool, List[Task]]: Success flag and a list of Tasks.
        """
        # Mapping of type and web pages.
        web_page_mapping = {
            "download": "offline_download",
            "transfer": "offline_download_transfer",
        }

        # Determine the web page based on type.
        web_page = web_page_mapping.get(task_type)

        if not web_page:
            raise ValueError(f"Invalid task type: {task_type}")

        api_url = urllib.parse.urljoin(
            self.base_url, f"/api/admin/task/{web_page}/{status}"
        )

        # Get task list
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(api_url, headers=self.headers) as response:
                json_data = await self.__get_json_data(response)

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
        return task_list

    async def get_offline_download_task_list(self) -> TaskList:
        done_task_list = await self.__get_task_list("download", "done")
        undone_task_list = await self.__get_task_list("download", "undone")
        task_list = done_task_list + undone_task_list
        return task_list

    async def get_offline_transfer_task_list(self) -> TaskList:
        done_task_list = await self.__get_task_list("transfer", "done")
        undone_task_list = await self.__get_task_list("transfer", "undone")
        task_list = done_task_list + undone_task_list
        return task_list

    async def rename(self, path, new_name):
        api = "/api/fs/rename"
        api_url = urllib.parse.urljoin(self.base_url, api)
        body = {
            "path": path,
            "name": new_name,
        }

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.post(
                api_url, headers=self.headers, json=body
            ) as response:
                await self.__get_json_data(response)

        return True
