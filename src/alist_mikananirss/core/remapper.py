from loguru import logger

from alist_mikananirss.websites import ResourceInfo


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

    def __init__(self, from_: dict, to_: dict):
        self.from_ = from_
        self.to_ = to_

    def match(self, resource_info: ResourceInfo):
        for k, v in self.from_.items():
            if k == "anime_name" and resource_info.anime_name != v:
                return False
            elif k == "season" and resource_info.season != v:
                return False
            elif k == "fansub" and resource_info.fansub != v:
                return False
        return True

    def remap(self, resource_info: ResourceInfo):
        for k, v in self.to_.items():
            if k == "anime_name":
                logger.info(
                    f'Remap {resource_info.resource_title}\'s anime_name from "{resource_info.anime_name}" to "{v}"'
                )
                resource_info.anime_name = v
            elif k == "season":
                logger.info(
                    f'Remap {resource_info.resource_title}\'s season from "{resource_info.season}" to "{v}"'
                )
                resource_info.season = v
            elif k == "episode_offset":
                logger.info(
                    f'Remap {resource_info.resource_title}\'s episode_offset from "{resource_info.episode}" to "{v}"'
                )
                resource_info.episode += v


class RemapperManager:
    """A class for managing Remapper objects

    Example:
        >>> RemapperManager.add_remapper(cfg["from"], cfg["to"])
        >>> remapper = RemapperManager.match(resource_info)
        >>> if remapper:
        >>>   RemapperManager.remap(remapper, resource_info)
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._remappers = []
        return cls._instance

    @classmethod
    def add_remapper(cls, from_: dict, to_: dict) -> Remapper:
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
