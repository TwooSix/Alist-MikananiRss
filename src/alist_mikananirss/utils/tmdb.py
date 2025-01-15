import aiohttp
from async_lru import alru_cache


class TMDBClient:
    def __init__(self, api_key: str = "32b19d6a05b512190a056fa4e747cbbc"):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"

    @alru_cache(maxsize=1024)
    async def search_tv(self, query: str):
        endpoint = f"{self.base_url}/search/tv"

        async with aiohttp.ClientSession() as session:
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
