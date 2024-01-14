import os
import time

from loguru import logger

from core import alist
from core.alist.offline_download import TaskList, TaskStatus
from core.bot import NotificationBot, NotificationMsg
from core.mikan import MikanAnimeResource


def download_new_resources(
    alist: alist.Alist, resources: list[MikanAnimeResource], root_path: str
):
    # group new resource by anime name and season
    resource_group: dict[str, dict[str, list[MikanAnimeResource]]] = {}
    for resource in resources:
        if resource.anime_name not in resource_group:
            resource_group[resource.anime_name] = {}
        if resource.season not in resource_group[resource.anime_name]:
            resource_group[resource.anime_name][resource.season] = []

        resource_group[resource.anime_name][resource.season].append(resource)

    # download new resources by group
    success_resource: list[MikanAnimeResource] = []
    for name, season_group in resource_group.items():
        for season, resources in season_group.items():
            urls = [resource.torrent_url for resource in resources]
            titles = [resource.resource_title for resource in resources]
            subfolder = os.path.join(name, f"Season {season}")
            download_path = os.path.join(root_path, subfolder)
            # download
            status, msg = alist.add_offline_download(download_path, urls)
            if not status:
                logger.error(f"Error when downloading {name}:\n {msg}")
                continue
            titles_str = "\n".join(titles)
            logger.info(f"Start to download {name}:\n {titles_str}")
            success_resource += resources
    for resource in success_resource:
        start_time = time.time()
        while True:
            flag, tmp_task_list = alist.get_offline_download_task_list()
            if not flag:
                # 60s timeout
                now_time = time.time()
                if now_time - start_time > 60:
                    msg = tmp_task_list
                    logger.error(msg)
                    break
                continue
            else:
                task_list = TaskList()
                for task in tmp_task_list:
                    if task.status in [TaskStatus.Pending, TaskStatus.Running]:
                        task_list.append(task)
                for task in task_list:
                    if task.url == resource.torrent_url:
                        resource.set_download_task(task)
                        break
                break
    return success_resource


def send_notification(bots: list[NotificationBot], resources: list[MikanAnimeResource]):
    # build notification msg
    msg = NotificationMsg()
    for resource in resources:
        name = resource.anime_name
        title = resource.resource_title
        msg.update(name, [title])
    for bot in bots:
        bot.send_message(msg)
