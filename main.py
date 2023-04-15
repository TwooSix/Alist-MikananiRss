from RSS import RSS, RSSManager
import Config

rssList = []

for each in Config.rss:
    subFolder = each['subFolder'] if 'subFolder' in each else None
    rssList.append(RSS(each['url'], each['filter'], subFolder))

manager = RSSManager(rssList, downloadPath=Config.downloadPath)

manager.checkUpdate()