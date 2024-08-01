from .models import AnimeNameInfo, ResourceNameInfo


class ExtractorBase:
    def __init__(self):
        # 模板类，初始化为空
        pass

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameInfo:
        raise NotImplementedError

    async def analyse_resource_name(self, resource_name: str) -> ResourceNameInfo:
        raise NotImplementedError
