---
name: bangumi
description: >
  Bangumi (bgm.tv) API reference for search, subject details, calendar,
  user collections and related subjects. Use anime-search for broader
  search and discovery workflows.
---

# bangumi

Bangumi (bgm.tv) API reference.

Run an action from this Skill directory with:

```bash
python scripts/<action>.py --json '{"argument":"value"}'
```

## Actions

- **search**: Search anime/manga by keyword with filters (type, tag, date, rating).
- **subject_detail**: Get full details for a specific Bangumi subject.
- **latest_episode**: Get the latest aired main-story episode for a subject.
- **weekly_calendar**: View the weekly anime airing schedule.
- **related_subjects**: Find sequels, prequels, and related works.
- **reviews**: Fetch community discussion topics and blog reviews for a subject.
- **user_collections**: List the user's collection by status. **Requires token.**
- **update_collection**: Update collection status, rating, comment, or episode progress. **Requires token.**

`update_collection` is a write operation. Show every proposed field, wait for
a later explicit user confirmation, and only then invoke it with
`confirmed=true`. The script rejects unconfirmed calls.

## Prerequisites

search, subject_detail, calendar, related_subjects, reviews are public APIs — no token needed.

user_collections and update_collection require a Bangumi access token configured in config.toml:
```toml
[bangumi]
access_token = "your_bangumi_token"
```
If missing, these actions return `Error: Bangumi access token not configured`.
Tell the user to set `[bangumi] access_token` in config.toml.

## Data Types

Collection types: 1=wish(想看), 2=done(看过), 3=doing(在看), 4=on_hold(搁置), 5=dropped(抛弃)
Subject types: 1=book, 2=anime, 3=music, 4=game, 6=real

## Latest aired episode

Use **latest_episode** when the user asks which episode of an anime is the
latest/current aired episode. It needs a Bangumi subject ID. If the user gives
only a title, call **search** first and then call **latest_episode** with the
selected `subject_id`.

This action uses Bangumi episode `airdate` and only considers main-story
episodes (`type=0`). Bangumi provides date precision only, so it cannot
distinguish whether today's episode has already reached its exact broadcast
time. The action treats "today" as the current UTC+8 date.
