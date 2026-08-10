---
name: oani
description: >
  OpenList-Ani backend API reference for library queries, download status and
  RSS feeds. Use anime-download for complete download workflows.
---

# oani

Run actions from this Skill directory:

```bash
python scripts/<action>.py --json '{"argument":"value"}'
```

## Scripts

- `query_library.py`: execute a read-only SELECT against the anime resource
  database.
- `list_downloads.py`: list active or recent download tasks.
- `parse_rss.py`: fetch and parse a feed, returning canonical titles and URLs.
- `resolve_magnet.py`: resolve a magnet to its real title and file list.
- `resolve_torrent.py`: resolve a torrent URL to its real title and file list.
- `preflight_download.py`: read-only review of automatic policy conflicts for
  one manual candidate. Always run it before asking for download confirmation,
  preserving the resolver's `collection_hint` value and the returned Assistant
  confirmation ticket. The ticket cannot be used until a later user turn.
- `list_rss.py`: list configured RSS subscriptions and priorities.
- `add_rss.py`: add a feed for future monitoring. Ask for explicit user
  confirmation in a separate turn before running it with `confirmed=true`.
- `create_download.py`: submit one download. Do not run directly from a user
  request; follow the anime-download Skill through duplicate checks, policy
  preflight and a later explicit confirmation, then pass `confirmed=true` and
  the exact preflight `confirmation_ticket`.

The Backend must be running. Scripts use the `[backend]` host and port from
the process configuration. Report connection failures with an instruction to
start `openlist-ani` first.
