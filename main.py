from RSS import RSS, RSSManager
import Config
import Api

rssList = []

for each in Config.rss:
    subFolder = each['subFolder'] if 'subFolder' in each else None
    rssList.append(RSS(each['url'], each['filter'], subFolder))

handler = Api.createApiHandler(Config.domain)
try:
    resp = handler.login(Config.username, Config.password)
except Exception as e:
    print(f'Login Failed: {e}')
    exit(1)
manager = RSSManager(rssList, downloadPath=Config.downloadPath, handler=handler)
manager.checkUpdate()