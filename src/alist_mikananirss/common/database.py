import os
import sqlite3
from datetime import datetime

from loguru import logger

from alist_mikananirss.websites import ResourceInfo

db_path = "data"
os.makedirs(db_path, exist_ok=True)


class SubscribeDatabase:
    def __init__(self, db_name="subscribe_database.db"):
        self.db_name = os.path.join(db_path, db_name)
        self.conn = None
        self.cursor = None
        self.__check()

    def connect(self):
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()

    def close(self):
        if self.conn:
            self.conn.close()

    def __check(self):
        if not os.path.exists(self.db_name):
            self.__create_table()
        else:
            self._upgrade_database()

    def __create_table(self):
        self.connect()
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_data (
                id TEXT PRIMARY KEY,
                title TEXT,
                link TEXT,
                published_date TEXT,
                downloaded_date TEXT,
                anime_name TEXT,
                season INTEGER,
                episode INTEGER,
                fansub TEXT,
                quality TEXT,
                language TEXT
            )
            """
        )
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS db_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        self.cursor.execute("INSERT INTO db_version (version) VALUES (1)")
        self.conn.commit()
        self.close()

    def _upgrade_database(self):
        self.connect()
        try:
            self.cursor.execute("SELECT version FROM db_version")
            version = self.cursor.fetchone()[0]
        except sqlite3.OperationalError:
            self.cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS db_version (
                    version INTEGER PRIMARY KEY
                )
            """
            )
            version = 0

        if version < 1:
            try:
                self.cursor.execute(
                    """
                    CREATE TABLE resource_data_new (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        resource_title TEXT NOT NULL,
                        torrent_url TEXT UNIQUE,
                        published_date TEXT,
                        downloaded_date TEXT,
                        anime_name TEXT,
                        season INTEGER,
                        episode INTEGER,
                        fansub TEXT,
                        quality TEXT,
                        language TEXT
                    )
                """
                )
                # 迁移数据
                self.cursor.execute(
                    """
                    INSERT INTO resource_data_new (resource_title, torrent_url, published_date, downloaded_date, anime_name)
                    SELECT title, link, published_date, downloaded_date, anime_name FROM resource_data
                """
                )
                # 删除旧表
                self.cursor.execute("DROP TABLE resource_data")
                # 重命名新表
                self.cursor.execute(
                    "ALTER TABLE resource_data_new RENAME TO resource_data"
                )
                # 创建新的索引
                self.cursor.execute(
                    """
                    CREATE UNIQUE INDEX idx_title
                    ON resource_data(resource_title)
                """
                )
                self.cursor.execute(
                    "INSERT OR REPLACE INTO db_version (version) VALUES (1)"
                )
                self.conn.commit()
                logger.info("Database upgraded to version 1")
            except Exception as e:
                logger.error(f"Error during database upgrade: {e}")
                self.conn.rollback()
        self.close()

    def insert(
        self,
        resource_title,
        torrent_url,
        published_date,
        downloaded_date,
        anime_name,
        season=None,
        episode=None,
        fansub=None,
        quality=None,
        language=None,
    ):
        self.connect()
        try:
            self.cursor.execute(
                """
                INSERT INTO resource_data 
                (resource_title, torrent_url, published_date, downloaded_date, anime_name, season, episode, fansub, quality, language)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    resource_title,
                    torrent_url,
                    published_date,
                    downloaded_date,
                    anime_name,
                    season,
                    episode,
                    fansub,
                    quality,
                    language,
                ),
            )
            self.conn.commit()
            logger.debug(f"Insert new resource: {anime_name}, {resource_title}")
        except sqlite3.IntegrityError:
            logger.debug(f"Resource already exists: {anime_name}, {resource_title}")
        except Exception as e:
            logger.error(f"Error when inserting resource: {e}")
        finally:
            self.close()

    def insert_resource_info(self, resource: ResourceInfo):
        downloaded_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        self.insert(
            resource.resource_title,
            resource.torrent_url,
            resource.published_date,
            downloaded_date,
            resource.anime_name,
            season=resource.season,
            episode=resource.episode,
            fansub=resource.fansub,
            quality=resource.quality,
            language=resource.language,
        )

    def is_resource_title_exist(self, resource_title: str):
        self.connect()
        try:
            self.cursor.execute(
                "SELECT 1 FROM resource_data WHERE resource_title = ? LIMIT 1",
                (resource_title,),
            )
            return self.cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking resource existence: {e}")
            return False
        finally:
            self.close()

    def delete_by_id(self, id):
        self.connect()
        try:
            self.cursor.execute("DELETE FROM resource_data WHERE id=?", (id,))
            self.conn.commit()
            logger.debug(f"Delete resource data: {id}")
        except Exception as e:
            logger.error(f"Error when delete resource data:\n {e}")
        finally:
            self.close()
