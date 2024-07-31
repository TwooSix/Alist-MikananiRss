from dataclasses import dataclass


@dataclass
class ResourceInfo:
    rid: str
    anime_name: str
    resource_title: str
    torrent_url: str
    published_date: str

    season: int = None
    episode: float = None
    fansub: str = ""
    quality: str = ""
    language: str = ""

    def __hash__(self):
        return hash(self.resource_title)


@dataclass
class FeedEntry:
    rid: str  # 数据库的主键，用于辨识当前资源，可自己生成，也可从资源主页链接中提取
    resource_title: str
    torrent_url: str
    published_date: str
    homepage_url: str = ""

    def __hash__(self):
        return hash(self.resource_title)
