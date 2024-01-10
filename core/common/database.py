import os
import sqlite3

from loguru import logger

db_path = "data"
os.makedirs(db_path, exist_ok=True)


class SubscribeDatabase:
    def __init__(self):
        db_name = "subscribe_database.db"
        self.db_name = os.path.join(db_path, db_name)
        self.conn = None
        self.cursor = None
        self.__check()

    def connect(self):
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()

    def insert(self, id, title, link, published_date, anime_name, downloaded_date):
        self.connect()
        try:
            self.cursor.execute(
                "INSERT INTO resource_data (id, title, link, published_date,"
                " anime_name, downloaded_date) VALUES (?, ?, ?, ?, ?, ?)",
                (id, title, link, published_date, anime_name, downloaded_date),
            )
            self.conn.commit()
            logger.debug(
                "Insert new resource data:"
                f" {id, title, link, published_date, anime_name, downloaded_date}"
            )
        except sqlite3.IntegrityError:
            logger.debug(
                "resource data already exists:"
                f" {id, title, link, published_date, anime_name, downloaded_date}"
            )
        except Exception as e:
            logger.error(f"Error when insert resource data:\n {e}")
        finally:
            self.close()

    def is_exist(self, id):
        self.connect()
        try:
            self.cursor.execute("SELECT * FROM resource_data WHERE id=?", (id,))
        except Exception as e:
            logger.error(e)
        data = self.cursor.fetchone()
        self.close()
        if data is not None:
            return True
        else:
            return False

    def close(self):
        if self.conn:
            self.conn.close()

    def __check(self):
        if not os.path.exists(self.db_name):
            self.__create_table()

    def __create_table(self):
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS resource_data (
                id TEXT PRIMARY KEY,
                title TEXT,
                link TEXT,
                published_date TEXT,
                downloaded_date TEXT,
                anime_name TEXT
            )
            """
        )
        self.conn.commit()
        self.conn.close()
