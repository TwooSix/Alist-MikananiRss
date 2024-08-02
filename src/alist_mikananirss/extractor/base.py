from .models import AnimeNameInfo, ResourceTitleInfo


class ExtractorBase:
    def __init__(self):
        # 模板类，初始化为空
        pass

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameInfo:
        raise NotImplementedError

    async def analyse_resource_title(self, resource_title: str) -> ResourceTitleInfo:
        raise NotImplementedError
