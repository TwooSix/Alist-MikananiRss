from __future__ import annotations

import re
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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
TRANSFER_DES_PATTERN = re.compile(r"transfer \[.*\]\((.+)\) to \[(.+)\]\((.+)\)")


class AlistTaskError(Exception):
    """Base exception for AlistTask related errors."""


class InvalidTaskDescription(AlistTaskError):
    """Raised when task description is invalid."""


@dataclass
class AlistTask(ABC):
    tid: str
    description: str
    status: AlistTaskStatus
    status_msg: str
    progress: float
    error_msg: str = ""
    task_type: AlistTaskType = field(init=False)

    @classmethod
    def from_json(cls, json_data: dict) -> "AlistTask":
        """Creates an AlistTask instance from a JSON dictionary."""
        tid = json_data["id"]
        description = json_data["name"]
        status = AlistTaskStatus(json_data["state"])
        status_msg = json_data["status"]
        progress = json_data["progress"]
        error_msg = json_data.get("error")

        return cls(
            tid=tid,
            description=description,
            status=status,
            status_msg=status_msg,
            progress=progress,
            error_msg=error_msg,
        )


@dataclass
class AlistTransferTask(AlistTask):
    uuid: str = field(init=False)
    target_path: str = field(init=False)
    task_type: AlistTaskType = field(default=AlistTaskType.TRANSFER, init=False)

    def __post_init__(self):
        self.task_type = AlistTaskType.TRANSFER
        match = re.match(TRANSFER_DES_PATTERN, self.description)
        if match:
            temp_filepath = match.group(1)
            target_drive = match.group(2)
            drive_subdir = match.group(3)
            target_dirpath = f"{target_drive}{drive_subdir}"
            elements = temp_filepath.split("/")
            uuid = elements[elements.index("temp") + 2]
            sub_path = temp_filepath[temp_filepath.rfind(uuid) + len(uuid) + 1 :]
            target_file_path = f"{target_dirpath}/{sub_path}"
        else:
            raise InvalidTaskDescription(
                f"Failed to get uuid and target filepath from task description: {self.description}"
            )
        self.uuid = uuid
        self.target_path = target_file_path


@dataclass
class AlistDownloadTask(AlistTask):
    url: str = field(init=False)
    download_path: str = field(init=False)
    task_type: AlistTaskType = field(default=AlistTaskType.DOWNLOAD, init=False)

    def __post_init__(self):
        match = re.match(DOWNLOAD_DES_PATTERN, self.description)
        if match:
            url = match.group(1)
            download_path = match.group(2)
        else:
            raise InvalidTaskDescription(
                f"Failed to get url and download path from task description: {self.description}"
            )
        # If seeding, the task status will still be Running
        # We need to change it to Succeeded manually to ensure the task is marked as completed
        if (
            self.status == AlistTaskStatus.Running
            and "offline download completed" in self.status_msg
        ):
            self.status = AlistTaskStatus.Succeeded

        self.url = url
        self.download_path = download_path


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

    def __repr__(self):
        return f"{self.tasks}"

    def get_by_id(self, tid: str) -> Optional[AlistTask]:
        """Get task by id, return None if not found."""
        return self.id_map.get(tid, None)
