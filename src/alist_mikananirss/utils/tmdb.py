import aiohttp
from async_lru import alru_cache


class TMDBClient:
    def __init__(
        self,
        api_key: str = "32b19d6a05b512190a056fa4e747cbbc",
        api_base_url: str = "https://api.tmdb.org/3",
    ):
        self.api_key = api_key
        self.base_url = api_base_url

    @alru_cache(maxsize=128)
    async def search_tv(self, query: str):
        endpoint = f"{self.base_url}/search/tv"

        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(
                endpoint,
                params={
                    "api_key": self.api_key,
                    "query": query,
                    "language": "zh-CN",
                },
            ) as response:
                data = await response.json()
                results = []
                for result in data["results"]:
                    tmp = {"title": result["name"], "id": result["id"]}
                    # filter out trash results
                    if result["popularity"] > 0:
                        results.append(tmp)
                return results
