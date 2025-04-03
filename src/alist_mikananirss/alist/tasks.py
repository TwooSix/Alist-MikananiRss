from __future__ import annotations

import re
from abc import ABC
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime


# https://github.com/alist-org/alist/blob/86b35ae5cfec400871072356fec4dea88303195d/pkg/task/task.go#L27
class AlistTaskState(Enum):
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


class CreatorRole(Enum):
    USER = 0
    GUEST = 1
    ADMIN = 2


DOWNLOAD_DES_PATTERN = re.compile(r"download\s+(.+?)\s+to \((.+?)\)")
TRANSFER_DES_PATTERN = re.compile(r"transfer \[.*\]\((.+)\) to \[(.+)\]\((.+)\)")


class AlistTaskError(Exception):
    """Base exception for AlistTask related errors."""


class InvalidTaskDescription(AlistTaskError):
    """Raised when task description is invalid."""


@dataclass
class AlistTask(ABC):
    """Alist offical task object.
    refer to: https://alist.nn.ci/zh/guide/api/task.html#%E8%BF%94%E5%9B%9E%E7%BB%93%E6%9E%9C
    """

    creator: str
    creator_role: CreatorRole
    end_time: datetime
    error: str
    tid: str
    name: str
    progress: float
    start_time: datetime
    state: AlistTaskState
    status: str
    total_bytes: int

    task_type: AlistTaskType = field(init=False)

    @classmethod
    def from_json(cls, json_data: dict) -> "AlistTask":
        """Creates an AlistTask instance from a JSON dictionary."""
        creator = json_data["creator"]
        creator_role = CreatorRole(json_data["creator_role"])
        end_time = (
            datetime.strptime(json_data["end_time"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ")
            if json_data["end_time"]
            else None
        )
        error = json_data["error"]
        tid = json_data["id"]
        name = json_data["name"]
        progress = json_data["progress"]
        start_time = (
            datetime.strptime(
                json_data["start_time"][:26] + "Z", "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            if json_data["start_time"]
            else None
        )
        state = AlistTaskState(json_data["state"])
        status = json_data["status"]
        total_bytes = json_data["total_bytes"]

        return cls(
            creator=creator,
            creator_role=creator_role,
            end_time=end_time,
            error=error,
            tid=tid,
            name=name,
            progress=progress,
            start_time=start_time,
            state=state,
            status=status,
            total_bytes=total_bytes,
        )

    def __hash__(self):
        return hash(self.tid)


@dataclass
class AlistTransferTask(AlistTask):
    """Parsed some neccesary information for transfer task from AlistTask object."""

    uuid: str = field(init=False)  # local temp directory uuid
    target_path: str = field(init=False)  # transfer target filepath
    task_type: AlistTaskType = field(default=AlistTaskType.TRANSFER, init=False)

    def __post_init__(self):
        self.task_type = AlistTaskType.TRANSFER
        match = re.match(TRANSFER_DES_PATTERN, self.name)
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
                f"Failed to get uuid and target filepath from task description: {self.name}"
            )
        self.uuid = uuid
        self.target_path = target_file_path

    def __hash__(self):
        return hash(self.tid)


@dataclass
class AlistDownloadTask(AlistTask):
    url: str = field(init=False)  # download url
    download_path: str = field(init=False)  # The target path in Alist to download to
    task_type: AlistTaskType = field(default=AlistTaskType.DOWNLOAD, init=False)

    def __post_init__(self):
        match = re.match(DOWNLOAD_DES_PATTERN, self.name)
        if match:
            url = match.group(1)
            download_path = match.group(2)
            self.url = url
            self.download_path = download_path
        else:
            raise InvalidTaskDescription(
                f"Failed to get url and download path from task description: {self.name}"
            )
        # If seeding, the task status will still be Running
        # We need to change it to Succeeded manually to ensure the task is marked as completed
        if (
            self.state == AlistTaskState.Running
            and "offline download completed" in self.status
        ):
            self.state = AlistTaskState.Succeeded

    def __hash__(self):
        return hash(self.tid)
