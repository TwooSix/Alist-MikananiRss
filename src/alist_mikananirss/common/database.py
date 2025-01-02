import os
from datetime import datetime

import aiosqlite
from loguru import logger

from alist_mikananirss.websites import ResourceInfo

db_dirpath = "data"
os.makedirs(db_dirpath, exist_ok=True)


class SubscribeDatabase:
    def __init__(self, db_name="subscribe_database.db"):
        self.db_filepath = os.path.join(db_dirpath, db_name)
        self.db = None

    @classmethod
    async def create(cls, db_name="subscribe_database.db"):
        self = cls(db_name=db_name)
        await self.initialize()
        return self

    async def initialize(self):
        if not os.path.exists(self.db_filepath):
            await self.connect()
            await self.__create_table()
        else:
            await self.connect()
            await self._upgrade_database()

    async def connect(self):
        if self.db:
            return
        self.db = await aiosqlite.connect(self.db_filepath)

    async def close(self):
        if self.db:
            await self.db.close()
            self.db = None

    async def __create_table(self):
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_data (
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
        await self.db.execute(
            """
            CREATE TABLE IF NOT EXISTS db_version (
                version INTEGER PRIMARY KEY
            )
            """
        )
        await self.db.execute("INSERT INTO db_version (version) VALUES (1)")
        await self.db.commit()

    async def _upgrade_database(self):
        try:
            cursor = await self.db.execute("SELECT version FROM db_version")
            version = await cursor.fetchone()
            version = version[0]
        except aiosqlite.OperationalError:
            await self.db.execute(
                """
                    CREATE TABLE IF NOT EXISTS db_version (
                        version INTEGER PRIMARY KEY
                    )
                """
            )
            version = 0

        if version < 1:
            try:
                await self.db.execute(
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
                await self.db.execute(
                    """
                        INSERT INTO resource_data_new (resource_title, torrent_url, published_date, downloaded_date, anime_name)
                        SELECT title, link, published_date, downloaded_date, anime_name FROM resource_data
                    """
                )
                # 删除旧表
                await self.db.execute("DROP TABLE resource_data")
                # 重命名新表
                await self.db.execute(
                    "ALTER TABLE resource_data_new RENAME TO resource_data"
                )
                # 创建新的索引
                await self.db.execute(
                    """
                        CREATE UNIQUE INDEX idx_title
                        ON resource_data(resource_title)
                    """
                )
                await self.db.execute(
                    "INSERT OR REPLACE INTO db_version (version) VALUES (1)"
                )
                await self.db.commit()
                logger.info("Database upgraded to version 1")
            except Exception as e:
                logger.error(f"Error during database upgrade: {e}")
                await self.db.rollback()

    async def insert(
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
        try:
            await self.db.execute(
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
            await self.db.commit()
            logger.debug(f"Insert new resource: {anime_name}, {resource_title}")
        except aiosqlite.IntegrityError:
            logger.debug(f"Resource already exists: {anime_name}, {resource_title}")
        except Exception as e:
            logger.error(f"Error when inserting resource: {e}")

    async def insert_resource_info(self, resource: ResourceInfo):
        downloaded_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        await self.insert(
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

    async def is_resource_title_exist(self, resource_title: str):
        try:
            cursor = await self.db.execute(
                "SELECT 1 FROM resource_data WHERE resource_title = ? LIMIT 1",
                (resource_title,),
            )
            return await cursor.fetchone() is not None
        except Exception as e:
            logger.error(f"Error checking resource existence: {e}")
            return False

    async def delete_by_id(self, id):
        try:
            await self.db.execute("DELETE FROM resource_data WHERE id=?", (id,))
            await self.db.commit()
            logger.debug(f"Delete resource data: {id}")
        except Exception as e:
            logger.error(f"Error when delete resource data:\n {e}")

    async def delete_by_torrent_url(self, url: str):
        try:
            await self.db.execute(
                "DELETE FROM resource_data WHERE torrent_url=?", (url,)
            )
            await self.db.commit()
            logger.debug(f"Delete resource data: {url}")
        except Exception as e:
            logger.error(f"Error when delete resource data:\n {e}")

    async def delete_by_resource_title(self, title: str):
        try:
            await self.db.execute(
                "DELETE FROM resource_data WHERE resource_title=?", (title,)
            )
            await self.db.commit()
            logger.debug(f"Delete resource data: {title}")
        except Exception as e:
            logger.error(f"Error when delete resource data:\n {e}")
