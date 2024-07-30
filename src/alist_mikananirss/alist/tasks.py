import re
from enum import Enum

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


class AlistTaskState(Enum):
    DONE = "done"
    UNDONE = "undone"


class AlistTask:
    def __init__(self, tid, description, status, progress, error_msg=None) -> None:
        self.tid = tid
        self.description = description
        self.status = status
        self.progress = progress
        self.error_msg = error_msg
        self.task_type: AlistTaskType = None

    @classmethod
    def from_json(cls, json_data):
        tid = json_data["id"]
        description = json_data["name"]
        state_str = json_data["state"]
        progress = json_data["progress"]
        error_str = json_data["error"]
        try:
            status = AlistTaskStatus(state_str)
        except ValueError:
            logger.warning(f"Unknown task status {state_str} of task {tid}")
            status = AlistTaskStatus.UNKNOWN
        return cls(tid, description, status, progress, error_str)

    def update_status(self, status: AlistTaskStatus):
        self.status = status


class AlistTransferTask(AlistTask):
    def __init__(self, tid, description, status, progress, error_msg=None) -> None:
        super().__init__(tid, description, status, progress, error_msg)
        self.download_task_id = None
        self.task_type = AlistTaskType.TRANSFER
        pattern = r"transfer (.+?) to \["
        match = re.search(pattern, self.description)
        if match:
            extracted_string = match.group(1)
            elements = extracted_string.split("/")
            self.uuid = elements[-2]
            self.file_name = elements[-1]
        else:
            logger.error(
                f"Can't find uuid/filename in task {self.tid}: {self.description}"
            )

    def set_download_task(self, task: AlistTask):
        self.download_task_id = task.tid

    def __repr__(self) -> str:
        return f"<TransferTask {self.tid}>"


class AlistDownloadTask(AlistTask):
    def __init__(self, tid, url, status, progress, error_msg=None) -> None:
        super().__init__(tid, url, status, progress, error_msg)
        self.transfer_task_id = set()
        self.is_started_transfer = False
        self.uuid = None
        self.url = None
        self.task_type = AlistTaskType.DOWNLOAD
        self.__init_url()

    def __init_url(self):
        pattern = r"download\s+(.+?)\s+to"
        match = re.match(pattern, self.description)
        if match:
            self.url = match.group(1)
        else:
            raise ValueError(f"Invalid task name {self.description}")

    def add_transfer_task(self, task: AlistTransferTask):
        self.transfer_task_id.add(task.tid)

    def set_started_transfer(self, uuid: str):
        self.is_started_transfer = True
        self.uuid = uuid

    def __repr__(self) -> str:
        return f"<DownloadTask {self.tid}>"


class AlistTaskList:
    def __init__(
        self, tasks: list[AlistTransferTask | AlistDownloadTask] = None
    ) -> None:
        if tasks is None:
            tasks = []
        self.tasks = tasks
        self.id_task_map = {}
        for task in tasks:
            self.id_task_map[task.tid] = task

    def append(self, task: AlistTransferTask | AlistDownloadTask):
        self.tasks.append(task)
        self.id_task_map[task.tid] = task

    def __add__(self, other):
        if isinstance(other, AlistTaskList):
            return AlistTaskList(self.tasks + other.tasks)
        else:
            raise TypeError("Operands must be instance of TaskList")

    def __getitem__(
        self, index: int | str
    ) -> AlistDownloadTask | AlistTransferTask | None:
        if isinstance(index, int):
            return self.tasks[index]
        elif isinstance(index, str):
            return self.id_task_map.get(index)

    def __contains__(self, task: AlistTask):
        return task.tid in self.id_task_map

    def __len__(self):
        return len(self.tasks)

    def __iter__(self):
        return iter(self.tasks)
