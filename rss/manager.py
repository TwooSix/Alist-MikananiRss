import os

import pandas as pd

import api.alist as alist
import rss


class Manager:
    """rss feed manager"""

    def __init__(
        self,
        rss_list: list[rss.Rss],
        download_path: str,
        alist: alist.Alist,
        notification_bot=None,
    ) -> None:
        """init the rss feed manager

        Args:
            rss_list (list[rss.Rss]): List rss
            download_path (str): Default path to download torrent file
            alist (alist.Alist): Alist's api handler
        """

        self.subscriptions = rss_list
        self.download_path = download_path
        self.alist_handler = alist
        self.notification_bot = notification_bot
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
        self.alist_handler.add_aria2(download_path, urls)

    def notify(self, message: str) -> None:
        """Send notification to user

        Args:
            message (str): message to send
        """

        if self.notification_bot:
            self.notification_bot.send_message(message)

    def check_update(self):
        """Check if there is new torrent in rss feed,
        if so, add it to aria2 task queue
        """

        print("Start Update Checking...")
        status = False
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
                # Download the torrent of new feed
                for idx in new_dataframe.index:
                    title = new_dataframe.iat[idx, 0]
                    link = new_dataframe.iat[idx, 1]
                    try:
                        self.__download([link], each_rss.getSubFolder())
                    except Exception as e:
                        print(f"Error when downloading {title}: {e}")
                        continue
                    self.notify(f"你订阅的番剧 [{each_rss}] 有更新啦:\n{title}")
                    status = True
                    print(f"Start to download: {title}")
                    # Update latestDate
                    self.save.at[each_rss.getUrl(), "latestDate"] = new_dataframe.iat[
                        idx, 2
                    ]
        if not status:
            print("No new torrent found")

        self.save.to_csv("save.csv", index=True)
        print("Check finished")
