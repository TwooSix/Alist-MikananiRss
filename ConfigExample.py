domain = 'www.example.com'

username = 'username'

password = 'password'

downloadPath = 'AliYun/Anime'

rss = [
    {
        'url': 'https://mikanani.me/RSS/Bangumi?bangumiId=2970&subgroupid=357',
        'filter': ['简体', '1080', '非合集'],
        # 不填写SubFolder则默认下载至downloadPath
    },
    {
        'url': 'https://mikanani.me/RSS/Bangumi?bangumiId=2996&subgroupid=382',
        'filter': ['简体', '1080', '非合集'],
        'subFolder': '地狱乐'
    },
    {
        'url': 'https://mikanani.me/RSS/Bangumi?bangumiId=3005&subgroupid=583',
        'filter': ['繁体', '1080', '非合集'],
        'subFolder': '公爵的契约未婚妻'
    },
]