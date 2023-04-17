import api
import config
import rss

rss_list = []

for each in config.rss:
    sub_folder = each["subFolder"] if "subFolder" in each else None
    rss_list.append(rss.Rss(each["url"], each["filter"], sub_folder))

alist = api.Alist(config.domain)
resp = alist.login(config.username, config.password)
manager = rss.Manager(rss_list, download_path=config.downloadPath, alist=alist)
manager.checkUpdate()
