from openlist_ani.assistant.skill_support.bangumi_model import (
    BangumiImages,
    parse_calendar_day,
    parse_legacy_blog,
    parse_legacy_topic,
    parse_subject,
    parse_user_collection_entry,
)


def test_subject_parses_nested_models_and_ignores_api_additions():
    subject = parse_subject(
        {
            "id": 42,
            "name": "Original",
            "name_cn": "中文名",
            "images": {"large": "cover.jpg", "future_size": "ignored"},
            "rating": {"score": 8.7, "total": 1234},
            "collection": None,
            "tags": [{"name": "动画", "count": 10}],
            "future_field": True,
        }
    )

    assert subject.display_name == "中文名"
    assert subject.url == "https://bgm.tv/subject/42"
    assert subject.images.large == "cover.jpg"
    assert subject.rating.score == 8.7
    assert subject.collection.collect == 0
    assert subject.tags[0].name == "动画"


def test_calendar_parses_nested_days_and_uses_defaults_for_nulls():
    day = parse_calendar_day(
        {
            "weekday": {"en": "Mon", "id": 1},
            "items": [{"id": 7, "name": "Anime", "images": None}],
        }
    )

    assert day.weekday.en == "Mon"
    assert day.items[0].display_name == "Anime"
    assert day.items[0].images == BangumiImages()


def test_collection_entry_parses_optional_nested_subject():
    entry = parse_user_collection_entry(
        {
            "subject_id": 9,
            "type": 3,
            "subject": {"id": 9, "name": "Watching"},
        }
    )

    assert entry.collection_type_label == "在看"
    assert entry.subject is not None
    assert entry.subject.name == "Watching"


def test_legacy_review_models_flatten_nested_user_nickname():
    topic = parse_legacy_topic({"id": 1, "user": {"nickname": "Alice"}})
    blog = parse_legacy_blog({"id": 2, "user": {"nickname": "Bob"}})

    assert topic.user_nickname == "Alice"
    assert blog.user_nickname == "Bob"
