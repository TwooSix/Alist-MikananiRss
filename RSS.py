"""
Only for mikanani.me
"""
import Filter
import RSSParser
import pandas as pd
import Api

class RSS():
    def __init__(self, url:str, filter:list[str]=[]):
        self.url = url
        self.setFilter(filter)

    def setFilter(self, filterNames:list[str]) -> None:
        """Set regex filter for rss feed"""
        filter = []
        for name in filterNames:
            filter.append(Filter.Filter[name])
        self.filter = filter
        return
    
    def getUrl(self) -> str:
        return self.url

    def parse(self) -> pd.DataFrame:
        return RSSParser.parse(self.url, self.filter)
    
    def __str__(self) -> str:
        return self.url

class RSSManager():
    def __init__(self, rssList:list[RSS], downloadPath:str) -> None:
        self.subscriptions = rssList
        self.downloadPath = downloadPath
        try:
            self.save = pd.read_csv('save.csv', index_col='subscriptions')
        except FileNotFoundError:
            self.save = pd.DataFrame(columns=['subscriptions', 'latestDate'])
            self.save.set_index('subscriptions', inplace=True)
        except Exception as e:
            raise Exception('Unkonwn Error when reading save.csv: {e}')

    def checkUpdate(self):
        """Check if there is new torrent in rss feed, if so, add it to aria2 task queue"""

        print('Start Update Checking...')
        downloadUrls = []
        for rss in self.subscriptions:
            print(f'Checking {rss}...')
            rssDataFrame = rss.parse()
            try:
                latestDate = self.save.at[rss.getUrl(), 'latestDate']
            except KeyError:
                # 第一次订阅，保存数据但不下载
                self.save.at[rss.getUrl(), 'latestDate'] = pd.to_datetime(rssDataFrame['pubDate'].max())
                print(f'New Subscription {rss} found, initial latestDate')
                continue
            # 检查是否有更新
            newDataFrame = rssDataFrame[rssDataFrame['pubDate'] > latestDate]
            if newDataFrame.shape[0] > 0:
                # 更新最新日期存档
                self.save.at[rss.getUrl(), 'latestDate'] = newDataFrame['pubDate'].max()
                # 添加新种子到下载列表
                for idx in newDataFrame.index:
                    title = newDataFrame.iat[idx, 0]
                    link = newDataFrame.iat[idx, 1]
                    downloadUrls.append(link)
                    print(f'New torrent found: {title}')
        # 添加aria2任务到Alist
        if len(downloadUrls) > 0:
            Api.add_aria2(self.downloadPath, downloadUrls)
            print(f'{len(downloadUrls)} new torrent(s) added to aria2 task queue')
        else:
            print('No new torrent found')
        # 更新save文件
        self.save.to_csv('save.csv', index=True)
        print('Check finished')
