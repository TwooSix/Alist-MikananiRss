---
name: anime-download
description: >
  Must be used whenever the user asks to download anime from an RSS URL,
  magnet, torrent URL, or description. Performs title resolution, duplicate
  checks and explicit confirmation before creating downloads.
---

# anime-download

Follow these five steps in order. Run sibling Skill scripts with `python` and
pass arguments through `--json`. Never create a download outside step 5.

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
or rewrite it from the user's description. Preserve the resolver's exact
`Collection hint` value for the remaining steps; it is `true` when resolved
metadata contains multiple video files. RSS and search results without resolved
file metadata use `collection_hint=false`; the Backend still recognizes common
collection markers in their canonical titles.

## 2. Check the local library

Run `../oani/scripts/query_library.py` with one read-only SELECT covering all
candidate titles or anime names. Exclude candidates already downloaded at the
same season, episode and version unless the user explicitly requests a retry.

## 3. Preflight automatic policies

Run `../oani/scripts/preflight_download.py` once per remaining candidate with
the exact `download_url`, canonical `title`, and preserved `collection_hint`.
This is read-only and does not create a task.

- If preflight is blocked, report the hard error and do not offer an override.
- If it returns policy conflicts, preserve every exact conflict key and show
  every reason and matched value to the user. Explain that continuing this
  manual request bypasses the listed RSS filter, priority or strict rules. A
  collection conflict also covers automatic policy selection for main episode
  files discovered inside that collection. Preserve the opaque
  `policy_review_token`; it binds the confirmation to the exact URL, title,
  `collection_hint`, and conflict keys.
- Preserve the exact `Assistant confirmation ticket` returned by preflight.
  The runtime binds it to this user session and request, and will reject it
  until a later user turn; never retry it in the preflight turn.
- If a preflight warning says inspection was incomplete, show that warning;
  never claim that all policies were evaluated.

## 4. Ask for explicit confirmation

Show a compact numbered list containing title, fansub, quality, language and
download URL. State which candidates were rejected as duplicates and include
all preflight policy conflicts. Ask the user to confirm the exact remaining
items and the listed overrides. End the response with
`[[CONFIRMATION_REQUIRED]]`. Do not treat the original download request as
confirmation and do not continue in the same turn.

## 5. Create confirmed downloads

Only after a later user message explicitly confirms, run
`../oani/scripts/create_download.py` once per confirmed item with the exact
`download_url`, canonical `title`, preserved `collection_hint`, and
`confirmed=true`, plus the exact `confirmation_ticket` returned by preflight.

- When preflight returned no conflicts, pass `override_policy=false`.
- When the user confirmed conflicts, pass `override_policy=true` and
  `acknowledged_conflicts` containing the exact conflict keys shown by
  preflight for that candidate, plus the exact `policy_review_token` returned
  by that preflight.
- If create reports a new or changed policy conflict that was not covered by
  the confirmed keys, do not retry in the same turn. Show the new conflicts and ask again with
  `[[CONFIRMATION_REQUIRED]]`.

Report each Backend result and do not retry any other failed submission
without asking.

## Related operations

- Monitor a feed: show the URL and ask for confirmation, then run
  `../oani/scripts/add_rss.py` with `confirmed=true` only after a later
  explicit confirmation message.
- Show download tasks: run `../oani/scripts/list_downloads.py`.
- Show configured feeds: run `../oani/scripts/list_rss.py`.
