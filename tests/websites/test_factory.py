from alist_mikananirss.websites import (
    AcgRip,
    DefaultWebsite,
    Dmhy,
    Mikan,
    WebsiteFactory,
)


def test_website_factory():
    assert isinstance(
        WebsiteFactory.get_website_parser(
            "https://mikanani.me/RSS/Bangumi?bangumiId=3519&subgroupid=382"
        ),
        Mikan,
    )
    assert isinstance(WebsiteFactory.get_website_parser("https://acg.rip/.xml"), AcgRip)
    assert isinstance(
        WebsiteFactory.get_website_parser("https://share.dmhy.org/topics/rss/rss.xml"),
        Dmhy,
    )
    assert isinstance(
        WebsiteFactory.get_website_parser("https://nyaa.si/?page=rss"), DefaultWebsite
    )
