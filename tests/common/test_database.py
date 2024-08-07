import os

import pytest
from alist_mikananirss.common.database import SubscribeDatabase, db_path
from alist_mikananirss.websites import ResourceInfo


@pytest.fixture
def test_db():
    db = SubscribeDatabase("test_subscribe_database.db")
    yield db
    # delete test database every time
    os.remove(os.path.join(db_path, "test_subscribe_database.db"))


def test_create_table(test_db):
    assert os.path.exists(test_db.db_name)

    test_db.connect()
    test_db.cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
    tables = test_db.cursor.fetchall()
    assert ("resource_data",) in tables
    assert ("db_version",) in tables
    test_db.close()


def test_insert_and_check_existence(test_db):
    resource = ResourceInfo(
        resource_title="Test Anime",
        torrent_url="http://example.com/test.torrent",
        published_date="2023-05-20T12:00:00",
        anime_name="Test Anime",
        season=1,
        episode=1,
        fansub="TestSub",
        quality="1080p",
        language="Japanese",
    )

    test_db.insert_resource_info(resource)

    assert test_db.is_resource_title_exist("Test Anime")


def test_delete_by_id(test_db):
    test_db.insert(
        "Test Delete",
        "http://example.com/delete.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    test_db.connect()
    test_db.cursor.execute(
        "SELECT id FROM resource_data WHERE resource_title=?", ("Test Delete",)
    )
    id_to_delete = test_db.cursor.fetchone()[0]
    test_db.close()

    test_db.delete_by_id(id_to_delete)

    assert not test_db.is_resource_title_exist("Test Delete")


def test_delete_by_torrent_url(test_db):
    url = "http://example.com/delete_url.torrent"
    test_db.insert(
        "Test Delete URL",
        url,
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    test_db.delete_by_torrent_url(url)

    assert not test_db.is_resource_title_exist("Test Delete URL")


def test_delete_by_resource_title(test_db):
    title = "Test Delete Title"
    test_db.insert(
        title,
        "http://example.com/delete_title.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    test_db.delete_by_resource_title(title)

    assert not test_db.is_resource_title_exist(title)


def test_upgrade_database(test_db):
    test_db.connect()
    test_db.cursor.execute("DROP TABLE IF EXISTS resource_data")
    test_db.cursor.execute("DROP TABLE IF EXISTS db_version")
    test_db.cursor.execute(
        """
        CREATE TABLE resource_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            link TEXT UNIQUE,
            published_date TEXT,
            downloaded_date TEXT,
            anime_name TEXT
        )
    """
    )
    test_db.conn.commit()
    test_db.close()

    test_db._upgrade_database()

    test_db.connect()
    test_db.cursor.execute("SELECT version FROM db_version")
    version = test_db.cursor.fetchone()[0]
    assert version == 1

    test_db.cursor.execute("PRAGMA table_info(resource_data)")
    columns = [info[1] for info in test_db.cursor.fetchall()]
    expected_columns = [
        "id",
        "resource_title",
        "torrent_url",
        "published_date",
        "downloaded_date",
        "anime_name",
        "season",
        "episode",
        "fansub",
        "quality",
        "language",
    ]
    assert all(column in columns for column in expected_columns)
    test_db.close()


def test_insert_duplicate(test_db):
    test_db.insert(
        "Duplicate Test",
        "http://example.com/duplicate.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    test_db.insert(
        "Duplicate Test",
        "http://example.com/duplicate.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    test_db.connect()
    test_db.cursor.execute(
        "SELECT COUNT(*) FROM resource_data WHERE resource_title=?", ("Duplicate Test",)
    )
    count = test_db.cursor.fetchone()[0]
    test_db.close()
    assert count == 1
