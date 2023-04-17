import os

import pandas as pd

import api.alist as alist
import rss


class Manager:
    """rss feed manager"""

    def __init__(
        self, rss_list: list[rss.Rss], download_path: str, alist: alist.Alist
    ) -> None:
        """init the rss feed manager

        Args:
            rss_list (list[rss.Rss]): List rss
            download_path (str): Default path to download torrent file
            alist (alist.Alist): Alist's api handler
        """

        self.subscriptions = rss_list
        self.download_path = download_path
        self.handler = alist
        try:
            self.save = pd.read_csv("save.csv", index_col="subscriptions")
        except FileNotFoundError:
            self.save = pd.DataFrame(columns=["subscriptions", "latestDate"])
            self.save.set_index("subscriptions", inplace=True)
        except Exception as e:
            print(f"Unkonwn Error when reading save.csv: {e}")
            exit(1)

    def __download(self, urls: str, subFolder: str = None) -> None:
        """Download torrent file to subfolder via alist's aria2

        Args:
            urls (list[str]): list of torrent url
            subFolder (str): download to subfloder. Defaults to None.
        """

        download_path = (
            os.path.join(self.download_path, subFolder)
            if subFolder
            else self.download_path
        )
        self.handler.add_aria2(download_path, urls)

    def checkUpdate(self):
        """Check if there is new torrent in rss feed,
        if so, add it to aria2 task queue
        """

        print("Start Update Checking...")
        download_urls = []
        for each_rss in self.subscriptions:
            print(f"Checking {each_rss}...")
            try:
                rss_dataframe = each_rss.parse()
            except Exception as e:
                print(f"Error when parsing {each_rss}: {e}")
                continue

            try:
                latest_date = self.save.at[each_rss.getUrl(), "latestDate"]
            except KeyError:
                # First time to subscribe, add to save dataframe and not download
                self.save.at[each_rss.getUrl(), "latestDate"] = pd.to_datetime(
                    rss_dataframe["pubDate"].max(), format="mixed", utc=True
                )
                print(f"New Subscription {each_rss} found, initial data")
                continue
            # Check if there is an update in feed
            new_dataframe = rss_dataframe[rss_dataframe["pubDate"] > latest_date]
            if new_dataframe.shape[0] > 0:
                # Update latestDate
                self.save.at[each_rss.getUrl(), "latestDate"] = new_dataframe[
                    "pubDate"
                ].max()
                # Download the torrent of new feed
                for idx in new_dataframe.index:
                    title = new_dataframe.iat[idx, 0]
                    link = new_dataframe.iat[idx, 1]
                    self.__download([link], each_rss.getSubFolder())
                    download_urls.append(link)
                    print(f"Start to download: {title}")

        if len(download_urls) == 0:
            print("No new torrent found")

        self.save.to_csv("save.csv", index=True)
        print("Check finished")
