from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger


# https://github.com/alist-org/alist/blob/86b35ae5cfec400871072356fec4dea88303195d/pkg/task/task.go#L27
class AlistTaskStatus(Enum):
    Pending = 0
    Running = 1
    Succeeded = 2
    Canceling = 3
    Canceled = 4
    Errored = 5
    Failing = 6
    Failed = 7
    StateWaitingRetry = 8
    StateBeforeRetry = 9
    UNKNOWN = 10


class AlistDownloaderType(Enum):
    ARIA = "aria2"
    QBIT = "qBittorrent"


class AlistDeletePolicy(Enum):
    DeleteOnUploadSucceed = "delete_on_upload_succeed"
    DeleteOnUploadFailed = "delete_on_upload_failed"
    DeleteNever = "delete_never"
    DeleteAlways = "delete_always"


class AlistTaskType(Enum):
    DOWNLOAD = "offline_download"
    TRANSFER = "offline_download_transfer"
    UNKNOWN = "unknown"


# for task related api call
class AlistTaskState(Enum):
    DONE = "done"
    UNDONE = "undone"


DOWNLOAD_DES_PATTERN = re.compile(r"download\s+(.+?)\s+to \((.+?)\)")
TRANSFER_DES_PATTERN = re.compile(r"transfer (.+?) to \[(.+?)\]")


class AlistTaskError(Exception):
    """Base exception for AlistTask related errors."""


class InvalidTaskDescription(AlistTaskError):
    """Raised when task description is invalid."""


@dataclass
class AlistTask(ABC):
    tid: str
    description: str
    status: AlistTaskStatus
    progress: float
    error_msg: Optional[str] = None
    task_type: AlistTaskType = AlistTaskType.UNKNOWN

    @classmethod
    @abstractmethod
    def from_json(cls, json_data: dict) -> AlistTask:
        tid = json_data["id"]
        description = json_data["name"]
        state_str = json_data["state"]
        progress = json_data["progress"]
        error_str = json_data["error"]
        try:
            status = AlistTaskStatus(state_str)
        except ValueError:
            logger.warning(f'Unknown task status "{state_str}" of task {tid}')
            status = AlistTaskStatus.UNKNOWN
        return cls(tid, description, status, progress, error_str)


@dataclass
class AlistTransferTask(AlistTask):
    uuid: str = ""
    target_path: str = ""

    def __post_init__(self):
        self.task_type = AlistTaskType.TRANSFER

    @classmethod
    def from_json(cls, json_data: dict) -> AlistTransferTask:
        task = super().from_json(json_data)
        match = re.search(TRANSFER_DES_PATTERN, task.description)
        if match:
            temp_filepath = match.group(1)
            target_dir = match.group(2)
            elements = temp_filepath.split("/")
            uuid = elements[elements.index("temp") + 2]

            sub_path = temp_filepath[temp_filepath.rfind(uuid) + len(uuid) + 1 :]
            target_file_path = f"{target_dir}/{sub_path}"
        else:
            raise InvalidTaskDescription(
                f"Failed to get uuid and target filepath from task description: {task.description}"
            )

        _instance = cls(
            tid=task.tid,
            description=task.description,
            status=task.status,
            progress=task.progress,
            error_msg=task.error_msg,
            uuid=uuid,
            target_path=target_file_path,
        )
        return _instance


@dataclass
class AlistDownloadTask(AlistTask):
    url: str = ""
    download_path: str = ""

    def __post_init__(self):
        self.task_type = AlistTaskType.DOWNLOAD

    @classmethod
    def from_json(cls, json_data: dict) -> AlistDownloadTask:
        task = super().from_json(json_data)
        match = re.match(DOWNLOAD_DES_PATTERN, task.description)
        if match:
            url = match.group(1)
            download_path = match.group(2)
        else:
            raise InvalidTaskDescription(
                f"Failed to get url from task description: {task.description}"
            )
        _instance = cls(
            tid=task.tid,
            description=task.description,
            status=task.status,
            progress=task.progress,
            error_msg=task.error_msg,
            url=url,
            download_path=download_path,
        )
        return _instance


class AlistTaskList:

    def __init__(self, tasks: list[AlistTask] = None):
        self.tasks = tasks or []
        self.id_map = {}
        for task in self.tasks:
            self.id_map[task.tid] = task

    def add_task(self, task: AlistTask):
        self.tasks.append(task)
        self.id_map[task.tid] = task

    def __iter__(self):
        return iter(self.tasks)

    def __add__(self, other: AlistTaskList):
        self.tasks.extend(other.tasks)
        self.id_map.update(other.id_map)
        return self

    def __getitem__(self, idx: int) -> AlistTask:
        return self.tasks[idx]

    def __len__(self) -> int:
        return len(self.tasks)

    def __contains__(self, tid: str) -> bool:
        return tid in self.id_map

    def get_by_id(self, tid: str) -> Optional[AlistTask]:
        """Get task by id, return None if not found."""
        return self.id_map.get(tid, None)
