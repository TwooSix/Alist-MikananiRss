from RSS import RSS, RSSManager

rssList = [
    RSS('https://mikanani.me/RSS/Bangumi?bangumiId=2970&subgroupid=357', ['简体', '1080', '非合集']),
    RSS('https://mikanani.me/RSS/Bangumi?bangumiId=2995&subgroupid=477', ['简体', '1080', '非合集']),
    RSS('https://mikanani.me/RSS/Bangumi?bangumiId=2996&subgroupid=382', ['简体', '1080', '非合集']),
    RSS('https://mikanani.me/RSS/Bangumi?bangumiId=3005&subgroupid=583', ['繁体', '1080', '非合集'])
]

manager = RSSManager(rssList, downloadPath='AliYun/Anime')

manager.checkUpdate()