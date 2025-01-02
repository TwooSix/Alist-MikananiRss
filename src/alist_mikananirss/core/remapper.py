from dataclasses import dataclass
from typing import Optional

from loguru import logger

from alist_mikananirss.common.config_loader import ConfigLoader
from alist_mikananirss.websites import ResourceInfo

from ..utils import Singleton


@dataclass
class RemapFrom:
    """Conditions to match for remapping"""

    anime_name: Optional[str] = None
    season: Optional[str] = None
    fansub: Optional[str] = None


@dataclass
class RemapTo:
    """Target values for remapping"""

    anime_name: Optional[str] = None
    season: Optional[str] = None
    episode_offset: Optional[int] = None


class Remapper:
    """A class for mapping properties between ResourceInfo objects according to user-defined rules

    Attributes:
        from_ (dict): the 'from' section of YAML
        to_ (dict): the 'to' section of YAML

    Example:
        >>> remapper = Remapper(cfg["from"], cfg["to])
        >>> if(remapper.match(resource_info)):
        >>>   remapper.remap(resource_info)
    """

    def __init__(self, from_: RemapFrom, to_: RemapTo):
        self.from_ = from_
        self.to_ = to_

    def match(self, resource_info: ResourceInfo) -> bool:
        if (
            (
                self.from_.anime_name
                and resource_info.anime_name != self.from_.anime_name
            )
            or (self.from_.season and resource_info.season != self.from_.season)
            or (self.from_.fansub and resource_info.fansub != self.from_.fansub)
        ):
            return False
        return True

    def remap(self, resource_info: ResourceInfo):
        if self.to_.anime_name:
            logger.info(
                f'Remap {resource_info.resource_title}\'s anime_name from "{resource_info.anime_name}" to "{self.to_.anime_name}"'
            )
            resource_info.anime_name = self.to_.anime_name

        if self.to_.season:
            logger.info(
                f'Remap {resource_info.resource_title}\'s season from "{resource_info.season}" to "{self.to_.season}"'
            )
            resource_info.season = self.to_.season

        if self.to_.episode_offset:
            logger.info(
                f'Remap {resource_info.resource_title}\'s episode_offset from "{resource_info.episode}" to "{resource_info.episode + self.to_.episode_offset}"'
            )
            resource_info.episode += self.to_.episode_offset


class RemapperManager(metaclass=Singleton):
    """A class for managing Remapper objects

    Example:
        >>> RemapperManager.add_remapper(cfg["from"], cfg["to"])
        >>> remapper = RemapperManager.match(resource_info)
        >>> if remapper:
        >>>   RemapperManager.remap(remapper, resource_info)
    """

    def __init__(self):
        self._remappers = []

    @classmethod
    def load_remappers_from_cfg(cls, cfg_path: str):
        lder = ConfigLoader(cfg_path)
        remapper_cfgs = lder.get("remap")
        for cfg in remapper_cfgs:
            from_ = RemapFrom(
                cfg["from"].get("anime_name", None),
                cfg["from"].get("season", None),
                cfg["from"].get("fansub", None),
            )
            to_ = RemapTo(
                cfg["to"].get("anime_name", None),
                cfg["to"].get("season", None),
                cfg["to"].get("episode_offset", None),
            )
            RemapperManager.add_remapper(from_, to_)

    @classmethod
    def add_remapper(cls, from_: RemapFrom, to_: RemapTo) -> Remapper:
        instance = cls()
        remapper = Remapper(from_, to_)
        instance._remappers.append(remapper)
        return remapper

    @classmethod
    def remove_remapper(cls, remapper: Remapper):
        instance = cls()
        if remapper in instance._remappers:
            instance._remappers.remove(remapper)

    @classmethod
    def clear_remappers(cls):
        instance = cls()
        instance._remappers.clear()

    @classmethod
    def get_all_remappers(cls) -> list:
        instance = cls()
        return instance._remappers

    @classmethod
    def match(cls, resource_info: ResourceInfo) -> Remapper | None:
        instance = cls()
        for remapper in instance._remappers:
            if remapper.match(resource_info):
                return remapper

    @classmethod
    def remap(cls, remapper: Remapper, resource_info: ResourceInfo):
        remapper.remap(resource_info)
