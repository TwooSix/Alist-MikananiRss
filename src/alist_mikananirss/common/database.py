import os
from datetime import datetime

import aiosqlite
from loguru import logger

from alist_mikananirss.websites import ResourceInfo

db_path = "data"
os.makedirs(db_path, exist_ok=True)


class SubscribeDatabase:
    def __init__(self, db_name="subscribe_database.db"):
        self.db_name = os.path.join(db_path, db_name)
        self.db = None

    async def initialize(self):
        if not os.path.exists(self.db_name):
            await self.__create_table()
        else:
            await self._upgrade_database()

    async def connect(self):
        self.db = await aiosqlite.connect(self.db_name)

    async def close(self):
        if self.db:
            await self.db.close()

    async def __create_table(self):
        async with aiosqlite.connect(self.db_name) as db:
            await db.execute(
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
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS db_version (
                    version INTEGER PRIMARY KEY
                )
                """
            )
            await db.execute("INSERT INTO db_version (version) VALUES (1)")
            await db.commit()

    async def _upgrade_database(self):
        async with aiosqlite.connect(self.db_name) as db:
            try:
                cursor = await db.execute("SELECT version FROM db_version")
                version = await cursor.fetchone()
                version = version[0]
            except aiosqlite.OperationalError:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS db_version (
                        version INTEGER PRIMARY KEY
                    )
                """
                )
                version = 0

            if version < 1:
                try:
                    await db.execute(
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
                    await db.execute(
                        """
                        INSERT INTO resource_data_new (resource_title, torrent_url, published_date, downloaded_date, anime_name)
                        SELECT title, link, published_date, downloaded_date, anime_name FROM resource_data
                    """
                    )
                    # 删除旧表
                    await db.execute("DROP TABLE resource_data")
                    # 重命名新表
                    await db.execute(
                        "ALTER TABLE resource_data_new RENAME TO resource_data"
                    )
                    # 创建新的索引
                    await db.execute(
                        """
                        CREATE UNIQUE INDEX idx_title
                        ON resource_data(resource_title)
                    """
                    )
                    await db.execute(
                        "INSERT OR REPLACE INTO db_version (version) VALUES (1)"
                    )
                    await db.commit()
                    logger.info("Database upgraded to version 1")
                except Exception as e:
                    logger.error(f"Error during database upgrade: {e}")
                    await db.rollback()

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
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
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
                await db.commit()
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
        async with aiosqlite.connect(self.db_name) as db:
            try:
                cursor = await db.execute(
                    "SELECT 1 FROM resource_data WHERE resource_title = ? LIMIT 1",
                    (resource_title,),
                )
                return await cursor.fetchone() is not None
            except Exception as e:
                logger.error(f"Error checking resource existence: {e}")
                return False

    async def delete_by_id(self, id):
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute("DELETE FROM resource_data WHERE id=?", (id,))
                await db.commit()
                logger.debug(f"Delete resource data: {id}")
            except Exception as e:
                logger.error(f"Error when delete resource data:\n {e}")

    async def delete_by_torrent_url(self, url: str):
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
                    "DELETE FROM resource_data WHERE torrent_url=?", (url,)
                )
                await db.commit()
                logger.debug(f"Delete resource data: {url}")
            except Exception as e:
                logger.error(f"Error when delete resource data:\n {e}")

    async def delete_by_resource_title(self, title: str):
        async with aiosqlite.connect(self.db_name) as db:
            try:
                await db.execute(
                    "DELETE FROM resource_data WHERE resource_title=?", (title,)
                )
                await db.commit()
                logger.debug(f"Delete resource data: {title}")
            except Exception as e:
                logger.error(f"Error when delete resource data:\n {e}")
