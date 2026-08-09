---
name: anime-download
description: >
  Must be used whenever the user asks to download anime from an RSS URL,
  magnet, torrent URL, or description. Performs title resolution, duplicate
  checks and explicit confirmation before creating downloads.
---

# anime-download

Follow these four steps in order. Run sibling Skill scripts with `python` and
pass arguments through `--json`. Never create a download outside step 4.

## 1. Resolve real candidates

- RSS URL: run `../oani/scripts/parse_rss.py` with `url`; show the returned
  entries and let the user select when more than one matches.
- Magnet: run `../oani/scripts/resolve_magnet.py` with `magnet`.
- Torrent URL: run `../oani/scripts/resolve_torrent.py` with `url`.
- Description or anime name:
  1. Run `../mikan/scripts/search.py` with `keyword`.
  2. Run `../mikan/scripts/subgroups.py` with the selected `bangumi_id`.
  3. Run `../mikan/scripts/releases.py` with the selected IDs.

The canonical `title` must be copied verbatim from script output. Never derive
or rewrite it from the user's description.

## 2. Check the local library

Run `../oani/scripts/query_library.py` with one read-only SELECT covering all
candidate titles or anime names. Exclude candidates already downloaded at the
same season, episode and version unless the user explicitly requests a retry.

## 3. Ask for explicit confirmation

Show a compact numbered list containing title, fansub, quality, language and
download URL. State which candidates were rejected as duplicates. Ask the user
to confirm the exact remaining items. Do not treat the original download
request as confirmation and do not continue in the same turn.

## 4. Create confirmed downloads

Only after a later user message explicitly confirms, run
`../oani/scripts/create_download.py` once per confirmed item with the exact
`download_url`, canonical `title`, and `confirmed=true`. Report each Backend
result and do not retry a failed submission without asking.

## Related operations

- Monitor a feed: show the URL and ask for confirmation, then run
  `../oani/scripts/add_rss.py` with `confirmed=true` only after a later
  explicit confirmation message.
- Show download tasks: run `../oani/scripts/list_downloads.py`.
- Show configured feeds: run `../oani/scripts/list_rss.py`.
