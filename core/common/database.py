import os
import sqlite3

from core.common.logger import Log

db_path = "data"
os.makedirs(db_path, exist_ok=True)


class SubscribeDatabase:
    def __init__(self):
        db_name = "subscribe_database.db"
        self.db_name = os.path.join(db_path, db_name)
        self.conn = None
        self.cursor = None

    def connect(self):
        if not os.path.exists(self.db_name):
            self.__create_table()
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()

    def close(self):
        if self.conn:
            self.conn.close()

    def __create_table(self):
        self.conn = sqlite3.connect(self.db_name)
        self.cursor = self.conn.cursor()
        self.cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS anime_data (
                id TEXT PRIMARY KEY,
                title TEXT,
                link TEXT,
                pubDate TEXT,
                animeName TEXT
            )
        """
        )
        self.conn.commit()
        self.conn.close()

    def add_data(self, id, title, link, pubDate, animeName):
        self.connect()
        try:
            self.cursor.execute(
                (
                    "INSERT INTO anime_data (id, title, link, pubDate, animeName)"
                    " VALUES (?, ?, ?, ?, ?)"
                ),
                (id, title, link, pubDate, animeName),
            )
            self.conn.commit()
            Log.debug(
                f"Insert new subscribe data: {id, title, link, pubDate, animeName}"
            )
        except sqlite3.IntegrityError:
            Log.debug(
                f"Subscribe data already exists: {id, title, link, pubDate, animeName}"
            )
        finally:
            self.close()

    def is_exist(self, id):
        self.connect()
        self.cursor.execute("SELECT * FROM anime_data WHERE id=?", (id,))
        data = self.cursor.fetchone()
        self.close()
        if data is not None:
            return True
        else:
            return False


if __name__ == "__main__":
    # 示例数据
    sample_id = "7c7c27175340c457de690243d9d0fabb01101be4"
    sample_title = "Sample Title"
    sample_link = "https://example.com/sample"
    sample_pubDate = "2023-10-09"
    sample_animeName = "Sample Anime"

    # 创建数据库对象
    db = SubscribeDatabase()

    # 添加示例数据
    db.add_data(sample_id, sample_title, sample_link, sample_pubDate, sample_animeName)

    # 查询是否存在相同id的数据
    db.is_exist(sample_id)
