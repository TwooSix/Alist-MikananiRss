"""Declarative models for Bangumi API responses."""

from __future__ import annotations

from enum import IntEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SubjectType(IntEnum):
    """Bangumi subject type.

    Values:
        BOOK: 1
        ANIME: 2
        MUSIC: 3
        GAME: 4
        REAL: 6
    """

    BOOK = 1
    ANIME = 2
    MUSIC = 3
    GAME = 4
    REAL = 6


class CollectionType(IntEnum):
    """User collection status type.

    Values:
        WISH: Want to watch (想看)
        DONE: Completed (看过)
        DOING: Watching (在看)
        ON_HOLD: On hold (搁置)
        DROPPED: Dropped (抛弃)
    """

    WISH = 1
    DONE = 2
    DOING = 3
    ON_HOLD = 4
    DROPPED = 5


COLLECTION_TYPE_LABELS: dict[int, str] = {
    1: "想看",
    2: "看过",
    3: "在看",
    4: "搁置",
    5: "抛弃",
}


class BangumiModel(BaseModel):
    """Tolerant base for external API payloads.

    Bangumi occasionally adds response fields or returns ``null`` for fields
    that normally contain a scalar/object. Unknown fields are ignored and null
    values fall back to the declared defaults.
    """

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _use_defaults_for_nulls(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {key: item for key, item in value.items() if item is not None}


class BangumiTag(BangumiModel):
    """A tag attached to a Bangumi subject."""

    name: str = ""
    count: int = 0


class BangumiRating(BangumiModel):
    """Rating information for a Bangumi subject."""

    rank: int = 0
    total: int = 0
    score: float = 0.0
    count: dict[str, int] = Field(default_factory=dict)


class BangumiImages(BangumiModel):
    """Image URLs for a Bangumi subject."""

    large: str = ""
    common: str = ""
    medium: str = ""
    small: str = ""
    grid: str = ""


class BangumiCollection(BangumiModel):
    """Collection summary counts for a Bangumi subject."""

    wish: int = 0
    collect: int = 0
    doing: int = 0
    on_hold: int = 0
    dropped: int = 0


class SlimSubject(BangumiModel):
    """Slim representation of a subject, embedded in user collections."""

    id: int = 0
    type: int = 2
    name: str = ""
    name_cn: str = ""
    short_summary: str = ""
    date: str = ""
    score: float = 0.0
    rank: int = 0
    collection_total: int = 0
    images: BangumiImages = Field(default_factory=BangumiImages)
    tags: list[BangumiTag] = Field(default_factory=list)
    eps: int = 0
    volumes: int = 0


class BangumiSubject(BangumiModel):
    """Full Bangumi subject (anime/book/game/music/real) detail."""

    id: int = 0
    type: int = 2
    name: str = ""
    name_cn: str = ""
    summary: str = ""
    date: str = ""
    platform: str = ""
    nsfw: bool = False
    locked: bool = False
    eps: int = 0
    total_episodes: int = 0
    volumes: int = 0
    images: BangumiImages = Field(default_factory=BangumiImages)
    rating: BangumiRating = Field(default_factory=BangumiRating)
    collection: BangumiCollection = Field(default_factory=BangumiCollection)
    tags: list[BangumiTag] = Field(default_factory=list)
    meta_tags: list[str] = Field(default_factory=list)
    infobox: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def display_name(self) -> str:
        """Return Chinese name if available, else original name."""
        return self.name_cn or self.name

    @property
    def url(self) -> str:
        """Bangumi subject page URL."""
        return f"https://bgm.tv/subject/{self.id}"


class CalendarItem(BangumiModel):
    """A single anime entry in the daily calendar (Legacy_SubjectSmall)."""

    id: int = 0
    name: str = ""
    name_cn: str = ""
    summary: str = ""
    air_date: str = ""
    air_weekday: int = 0
    url: str = ""
    eps: int = 0
    eps_count: int = 0
    images: BangumiImages = Field(default_factory=BangumiImages)
    rating: BangumiRating = Field(default_factory=BangumiRating)
    rank: int = 0
    collection: BangumiCollection = Field(default_factory=BangumiCollection)

    @property
    def display_name(self) -> str:
        """Return Chinese name if available, else original name."""
        return self.name_cn or self.name


class Weekday(BangumiModel):
    """Weekday information from the calendar API."""

    en: str = ""
    cn: str = ""
    ja: str = ""
    id: int = 0


class CalendarDay(BangumiModel):
    """One day in the weekly calendar, containing the weekday and its anime list."""

    weekday: Weekday = Field(default_factory=Weekday)
    items: list[CalendarItem] = Field(default_factory=list)


class BangumiUser(BangumiModel):
    """Bangumi user information from /v0/me."""

    id: int = 0
    username: str = ""
    nickname: str = ""
    user_group: int = 0
    sign: str = ""


class BangumiTopic(BangumiModel):
    """A discussion topic from the legacy subject API."""

    id: int = 0
    title: str = ""
    main_id: int = 0
    timestamp: int = 0
    lastpost: int = 0
    replies: int = 0
    user_nickname: str = ""
    url: str = ""

    @model_validator(mode="before")
    @classmethod
    def _flatten_user(cls, value: Any) -> Any:
        return _with_user_nickname(value)


class BangumiBlog(BangumiModel):
    """A blog/review entry from the legacy subject API."""

    id: int = 0
    title: str = ""
    summary: str = ""
    image: str = ""
    replies: int = 0
    timestamp: int = 0
    dateline: str = ""
    user_nickname: str = ""
    url: str = ""

    @model_validator(mode="before")
    @classmethod
    def _flatten_user(cls, value: Any) -> Any:
        return _with_user_nickname(value)


class RelatedSubject(BangumiModel):
    """A subject related to another subject (from /v0/subjects/{id}/subjects)."""

    relation: str = ""
    subject: SlimSubject = Field(default_factory=SlimSubject)


class UserCollectionEntry(BangumiModel):
    """A single entry in the user's collection list."""

    subject_id: int = 0
    subject_type: int = 2
    rate: int = 0
    type: int = 0  # CollectionType value
    comment: str = ""
    tags: list[str] = Field(default_factory=list)
    ep_status: int = 0
    vol_status: int = 0
    updated_at: str = ""
    private: bool = False
    subject: SlimSubject | None = None

    @property
    def collection_type_label(self) -> str:
        """Human-readable collection type label in Chinese."""
        return COLLECTION_TYPE_LABELS.get(self.type, "未知")


def _with_user_nickname(value: Any) -> Any:
    """Flatten the legacy API's nested user nickname."""
    if not isinstance(value, dict):
        return value
    result = dict(value)
    user = result.get("user")
    if isinstance(user, dict):
        result.setdefault("user_nickname", user.get("nickname", ""))
    return result


# Compatibility parsing functions keep callers independent of Pydantic.


def parse_images(data: dict | None) -> BangumiImages:
    return BangumiImages.model_validate(data or {})


def parse_rating(data: dict | None) -> BangumiRating:
    return BangumiRating.model_validate(data or {})


def parse_collection(data: dict | None) -> BangumiCollection:
    return BangumiCollection.model_validate(data or {})


def parse_tags(data: list | None) -> list[BangumiTag]:
    return [BangumiTag.model_validate(item) for item in (data or [])]


def parse_calendar_item(data: dict) -> CalendarItem:
    return CalendarItem.model_validate(data)


def parse_calendar_day(data: dict) -> CalendarDay:
    return CalendarDay.model_validate(data)


def parse_subject(data: dict) -> BangumiSubject:
    return BangumiSubject.model_validate(data)


def parse_slim_subject(data: dict) -> SlimSubject:
    return SlimSubject.model_validate(data or {})


def parse_related_subject(data: dict) -> RelatedSubject:
    return RelatedSubject.model_validate(data)


def parse_user_collection_entry(data: dict) -> UserCollectionEntry:
    return UserCollectionEntry.model_validate(data)


def parse_user(data: dict) -> BangumiUser:
    return BangumiUser.model_validate(data)


def parse_legacy_topic(data: dict) -> BangumiTopic:
    return BangumiTopic.model_validate(data)


def parse_legacy_blog(data: dict) -> BangumiBlog:
    return BangumiBlog.model_validate(data)
