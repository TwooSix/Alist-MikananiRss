"""
Only Test in mikanani.me
"""
import Filter
import RSSParser
import pandas as pd
import Api
import os

class RSS():
    def __init__(self, url:str, filter:list[str]=[], subFolder:str=None):
        self.url = url
        self.subFolder = subFolder
        self.name = subFolder if subFolder else url
        self.setFilter(filter)

    def setFilter(self, filterNames:list[str]) -> None:
        """Set regex filter for rss feed"""
        filter = []
        for name in filterNames:
            filter.append(Filter.Filter[name])
        self.filter = filter
        return
    
    def getName(self) -> str:
        return self.name

    def getUrl(self) -> str:
        return self.url

    def getSubFolder(self) -> str:
        return self.subFolder

    def parse(self) -> pd.DataFrame:
        return RSSParser.parse(self.url, self.filter)
    
    def __str__(self) -> str:
        return self.name

class RSSManager():
    def __init__(self, rssList:list[RSS], downloadPath:str, handler:Api.ApiHandler) -> None:
        self.subscriptions = rssList
        self.downloadPath = downloadPath
        self.handler = handler
        try:
            self.save = pd.read_csv('save.csv', index_col='subscriptions')
        except FileNotFoundError:
            self.save = pd.DataFrame(columns=['subscriptions', 'latestDate'])
            self.save.set_index('subscriptions', inplace=True)
        except Exception as e:
            raise Exception('Unkonwn Error when reading save.csv: {e}')

    def __download(self, urls:str, subFolder:str = None) -> None:
        """Download torrent file from url"""
        downloadPath = os.path.join(self.downloadPath, subFolder) if subFolder else self.downloadPath
        self.handler.add_aria2(downloadPath, urls)

    def checkUpdate(self):
        """Check if there is new torrent in rss feed, if so, add it to aria2 task queue"""

        print('Start Update Checking...')
        downloadUrls = []
        for rss in self.subscriptions:
            print(f'Checking {rss}...')
            try:
                rssDataFrame = rss.parse()
            except Exception as e:
                print(f'Error when parsing {rss}: {e}')
                continue
            try:
                latestDate = self.save.at[rss.getUrl(), 'latestDate']
            except KeyError:
                # 第一次订阅，保存数据但不下载
                self.save.at[rss.getUrl(), 'latestDate'] = pd.to_datetime(rssDataFrame['pubDate'].max(), format='mixed', utc=True)
                print(f'New Subscription {rss} found, initial data')
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
                    self.__download([link], rss.getSubFolder())
                    downloadUrls.append(link)
                    print(f'Start to download: {title}')

        # 添加aria2任务到Alist
        if len(downloadUrls) == 0:
            print('No new torrent found')

        # 更新save文件
        self.save.to_csv('save.csv', index=True)
        print('Check finished')
