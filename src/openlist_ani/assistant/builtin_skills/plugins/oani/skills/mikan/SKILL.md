---
name: mikan
description: >
  Mikan (mikanani.me) API reference for search, subgroups, releases and
  subscriptions. Use anime-download for complete download workflows.
---

# mikan

Mikan (mikanani.me) anime torrent site API reference.

Run an action from this Skill directory with:

```bash
python scripts/<action>.py --json '{"argument":"value"}'
```

## Actions

- **search**: Search anime by keyword. Returns bangumi IDs, names, URLs.
- **subgroups**: List fansub groups and release counts for a bangumi.
- **releases**: Fetch releases for a fansub group. Returns titles and magnet links.
- **subscribe**: Subscribe to a bangumi for automatic RSS updates. **Requires login.**
- **unsubscribe**: Unsubscribe from a bangumi. **Requires login.**

`subscribe` and `unsubscribe` are write operations. Show the exact bangumi,
subtitle group and language first, wait for a later explicit user confirmation,
then invoke the script with `confirmed=true`. The script rejects calls without
that flag.

## Prerequisites

search, subgroups, releases are public — no login needed.

subscribe and unsubscribe require Mikan credentials in config.toml:
```toml
[mikan]
username = "your_username"
password = "your_password"
```
If missing, these actions return `Error: Mikan credentials not configured`.
Tell the user to set `[mikan] username` and `password` in config.toml.

## Releases ≠ Episodes

`releases` returns individual release entries. One episode often has
multiple releases (different languages, resolutions, v2 fixes).
Never assume 1 release = 1 episode.
