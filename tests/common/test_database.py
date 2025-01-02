import os
import uuid

import pytest
import pytest_asyncio

from alist_mikananirss.common.database import SubscribeDatabase, db_dirpath
from alist_mikananirss.websites import ResourceInfo


@pytest_asyncio.fixture
async def test_db():
    # 为每个测试创建唯一的数据库文件名
    unique_db_name = f"test_db_{uuid.uuid4()}.db"
    db = await SubscribeDatabase.create(unique_db_name)
    db_filepath = os.path.join(db_dirpath, unique_db_name)

    yield db

    # 清理工作
    await db.close()
    if os.path.exists(db_filepath):
        try:
            os.remove(db_filepath)
        except PermissionError:
            import time

            time.sleep(0.1)
            os.remove(db_filepath)


@pytest.mark.asyncio
async def test_create_table(test_db):
    cursor = await test_db.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table';"
    )
    tables = await cursor.fetchall()
    assert ("resource_data",) in tables
    assert ("db_version",) in tables
    await test_db.close()


@pytest.mark.asyncio
async def test_insert_and_check_existence(test_db):
    resource = ResourceInfo(
        resource_title="Test Anime",
        torrent_url="https://example.com/test.torrent",
        published_date="2023-05-20T12:00:00",
        anime_name="Test Anime",
        season=1,
        episode=1,
        fansub="TestSub",
        quality="1080p",
        language="Japanese",
    )

    await test_db.insert_resource_info(resource)

    assert await test_db.is_resource_title_exist("Test Anime")


@pytest.mark.asyncio
async def test_delete_by_id(test_db):
    await test_db.insert(
        "Test Delete",
        "https://example.com/delete.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    await test_db.connect()
    cursor = await test_db.db.execute(
        "SELECT id FROM resource_data WHERE resource_title=?", ("Test Delete",)
    )
    id_to_delete = await cursor.fetchone()
    id_to_delete = id_to_delete[0]
    await test_db.close()

    await test_db.delete_by_id(id_to_delete)

    assert not await test_db.is_resource_title_exist("Test Delete")


@pytest.mark.asyncio
async def test_delete_by_torrent_url(test_db):
    url = "https://example.com/delete_url.torrent"
    await test_db.insert(
        "Test Delete URL",
        url,
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    await test_db.delete_by_torrent_url(url)

    assert not await test_db.is_resource_title_exist("Test Delete URL")


@pytest.mark.asyncio
async def test_delete_by_resource_title(test_db):
    title = "Test Delete Title"
    await test_db.insert(
        title,
        "https://example.com/delete_title.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    await test_db.delete_by_resource_title(title)

    assert not await test_db.is_resource_title_exist(title)


@pytest.mark.asyncio
async def test_upgrade_database(test_db):
    await test_db.connect()
    await test_db.db.execute("DROP TABLE IF EXISTS resource_data")
    await test_db.db.execute("DROP TABLE IF EXISTS db_version")
    await test_db.db.execute(
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
    await test_db.db.commit()
    await test_db._upgrade_database()
    cursor = await test_db.db.execute("SELECT version FROM db_version")
    version = await cursor.fetchone()
    version = version[0]
    assert version == 1

    cursor = await test_db.db.execute("PRAGMA table_info(resource_data)")
    columns = [info[1] for info in await cursor.fetchall()]
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
    await test_db.close()


@pytest.mark.asyncio
async def test_insert_duplicate(test_db):
    await test_db.insert(
        "Duplicate Test",
        "https://example.com/duplicate.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    await test_db.insert(
        "Duplicate Test",
        "https://example.com/duplicate.torrent",
        "2023-05-20T12:00:00",
        "2023-05-20T12:01:00",
        "Test Anime",
    )

    await test_db.connect()
    cursor = await test_db.db.execute(
        "SELECT COUNT(*) FROM resource_data WHERE resource_title=?", ("Duplicate Test",)
    )
    count = await cursor.fetchone()
    count = count[0]
    await test_db.close()
    assert count == 1
