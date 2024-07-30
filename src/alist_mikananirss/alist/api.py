import asyncio
import mimetypes
import os
import urllib.parse
from dataclasses import dataclass
from typing import Optional

import aiohttp

from alist_mikananirss.alist.tasks import (
    AlistDeletePolicy,
    AlistDownloaderType,
    AlistDownloadTask,
    AlistTask,
    AlistTaskList,
    AlistTaskState,
    AlistTaskStatus,
    AlistTaskType,
    AlistTransferTask,
)


@dataclass
class AlistConfig:
    base_url: str
    token: str
    downloader: AlistDownloaderType


class AlistClientError(Exception):
    pass


class Alist:
    def __init__(self, config: AlistConfig):
        self.config = config
        self.session = None
        self._session_lock = asyncio.Lock()

    async def _ensure_session(self):
        async with self._session_lock:
            if self.session is None or self.session.closed:
                self.session = aiohttp.ClientSession(trust_env=True)

    async def _api_call(
        self,
        method: str,
        endpoint: str,
        custom_headers: dict[str, str] = None,
        **kwargs,
    ):
        await self._ensure_session()
        url = urllib.parse.urljoin(self.config.base_url, endpoint)
        headers = {
            "Authorization": self.config.token,
            "Content-Type": "application/json",
            "User-Agent": "Alist-Mikanirss",
        }
        if custom_headers:
            headers.update(custom_headers)
        async with self.session.request(method, url, headers=headers, **kwargs) as resp:
            resp.raise_for_status()
            data = await resp.json()
            if data["code"] != 200:
                raise AlistClientError(data.get("message", "Unknown error"))
            return data["data"]

    async def _init_alist_version(self):
        response_data = await self._api_call("GET", "/api/public/settings")
        self.version = response_data["version"][1:]  # 去掉字母v

    async def get_alist_ver(self):
        if not hasattr(self, "version"):
            await self._init_alist_version()
        return self.version

    async def add_offline_download_task(
        self, save_path: str, urls: list[str]
    ) -> "AlistTaskList":
        response_data = await self._api_call(
            "POST",
            "api/fs/add_offline_download",
            json={
                "delete_policy": AlistDeletePolicy.DeleteOnUploadSucceed.value,
                "path": save_path,
                "urls": urls,
                "tool": self.config.downloader,
            },
        )
        return AlistTaskList(
            [AlistDownloadTask.from_json(task) for task in response_data["tasks"]]
        )

    async def upload(self, save_path: str, file_path: str) -> bool:
        file_path = os.path.abspath(file_path)
        file_name = os.path.basename(file_path)

        # Use utf-8 encoding to avoid UnicodeEncodeError
        file_path_encoded = file_path.encode("utf-8")

        mime_type = mimetypes.guess_type(file_name)[0]
        file_stat = os.stat(file_path)
        upload_path = urllib.parse.quote(f"{save_path}/{file_name}")

        headers = {
            "Content-Type": mime_type,
            "Content-Length": str(file_stat.st_size),
            "file-path": upload_path,
        }

        with open(file_path_encoded, "rb") as f:
            await self._api_call("PUT", "api/fs/put", custom_headers=headers, data=f)
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
        response_data = await self._api_call(
            "POST",
            "api/fs/list",
            json={
                "path": path,
                "password": password,
                "page": page,
                "per_page": per_page,
                "refresh": refresh,
            },
        )
        if response_data["content"]:
            files_list = [file_info["name"] for file_info in response_data["content"]]
        else:
            files_list = []
        return files_list

    async def _fetch_tasks(
        self, task_type: AlistTaskType, status: AlistTaskStatus
    ) -> "AlistTaskList":
        json_data = await self._api_call(
            "GET", f"/api/admin/task/{task_type.value}/{status.value}"
        )

        if task_type == AlistTaskType.TRANSFER:
            task_class = AlistTransferTask
        else:
            task_class = AlistDownloadTask

        tasks = [task_class.from_json(task) for task in json_data] if json_data else []
        return AlistTaskList(tasks)

    async def get_task_list(
        self, task_type: AlistTaskType, status: Optional[AlistTaskState] = None
    ) -> AlistTaskList:
        """
        获取任务列表。

        Args:
            task_type (TaskType): 任务类型（下载或传输）
            status (TaskStatus, optional): 任务状态（完成或未完成）。如果为None，则获取所有状态的任务。

        Returns:
            TaskList: 包含指定类型和状态的任务列表
        """
        if status is None:
            done_tasks = await self._fetch_tasks(task_type, AlistTaskState.DONE)
            undone_tasks = await self._fetch_tasks(task_type, AlistTaskState.UNDONE)
            return done_tasks + undone_tasks
        else:
            return await self._fetch_tasks(task_type, status)

    async def cancel_task(
        self,
        task: AlistTask,
    ) -> bool:
        await self._api_call(
            "POST", f"/api/admin/task/{task.task_type.value}/cancel?tid={task.tid}"
        )
        return True

    async def rename(self, path, new_name):
        await self._api_call(
            "POST", "api/fs/rename", json={"path": path, "name": new_name}
        )

        return True
