---
name: anime-search
description: >
  Use when the user wants to search anime, check airing schedules, look up
  details, or find related works. Use anime-download for download requests.
---

# anime-search

Use the sibling Bangumi and Mikan Skill scripts. Resolve paths relative to
this Skill directory and pass arguments with `--json`.

## Search by keyword

1. Run `python ../bangumi/scripts/search.py --json '{"keyword":"<query>"}'`.
2. Present name, score, rank and date without guessing ambiguous results.
3. For details, run `../bangumi/scripts/subject_detail.py` with `subject_id`.
4. For sequels, run `../bangumi/scripts/related_subjects.py` with `subject_id`.

## Weekly airing schedule

Run `python ../bangumi/scripts/weekly_calendar.py --json '{}'` and group the result
by day of week.

## Fansub availability

1. Run `../mikan/scripts/search.py` with the anime name.
2. Run `../mikan/scripts/subgroups.py` with the selected `bangumi_id`.
3. Present groups and release counts; let the user choose when ambiguous.
