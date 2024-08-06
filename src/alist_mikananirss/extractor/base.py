from .models import AnimeNameExtractResult, ResourceTitleExtractResult


class ExtractorBase:
    def __init__(self):
        # 模板类，初始化为空
        pass

    async def analyse_anime_name(self, anime_name: str) -> AnimeNameExtractResult:
        """Analyse the anime name to get resource info.

        Args:
            anime_name (str)

        Returns:
            AnimeNameExtractResult: The extracted info in anime name.
        """
        raise NotImplementedError

    async def analyse_resource_title(
        self, resource_title: str
    ) -> ResourceTitleExtractResult:
        """Analyse the resource title to get resource info.

        Args:
            resource_title (str)

        Returns:
            ResourceTitleExtractResult: The extracted info in resource title.
        """
        raise NotImplementedError
