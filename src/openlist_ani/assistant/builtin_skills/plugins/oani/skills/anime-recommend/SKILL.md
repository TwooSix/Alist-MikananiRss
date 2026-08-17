---
name: anime-recommend
description: >
  Use when the user wants anime recommendations, taste profile analysis,
  or asks "what should I watch" / "summarize my taste".
---

# anime-recommend

## Recommend

### Step 1 — Get all data (single call)

From this Skill directory run:

```bash
python scripts/default.py --json '{}'
```

**Script does:** Fetches user collections, builds tiered confidence stats, fetches calendar, computes Bayesian weighted scores — all in one call.

**Script output has two parts:**

**Part 1 — Taste Profile:**
- If up-to-date: returns existing `anime_taste.md` content.
- If new/changed: returns a tiered confidence report + titles list.
  - **Strong (≥50%)** — genre/studio/director in ≥50% of liked titles
  - **Weak (30-50%)** — in 30-50%
  - Below 30%: already filtered out by the script

**Part 2 — Scored Candidates:**
- Calendar listing + Bayesian weighted ranking of all airing titles.
- Each candidate has: raw score, votes, weighted score.
- `weighted` is for your internal ranking. `raw` is what users see.

### Step 2 — Offer to save a new profile

If the output says "PROFILE UPDATE AVAILABLE", show the generated profile and
offer to save it. Do not block recommendations on saving. If the user confirms
in a later message, run `scripts/save_profile.py` with `profile` containing the
exact Markdown and `confirmed=true`:

```markdown
## Liked (Strong)
- genres: 战斗, 奇幻
- studios: MAPPA

## Liked (Weak)
- genres: 搞笑, 恋爱

## Disliked
- genres: 科幻

## Titles
- GIRLS BAND CRY → 10/10, loved: 作画, 音乐, 角色塑造
- 异世界舅舅 → dropped, disliked: 节奏太慢
```

**CRITICAL:** Only transcribe items that appear in the confidence report.
- If "Disliked Genres" section is empty in the report → omit `## Disliked` entirely or leave genres blank.
- Do NOT infer preferences from the titles list. The titles list is context only — the confidence report is the source of truth.
- Do NOT copy genres from the example above — use the actual report output.

Never infer extra preferences while transcribing the profile. If it is already
up-to-date, skip this step.

### Step 3 — Pick and present

From Part 2's weighted ranking, pick top 3-5. If taste profile exists, re-rank:
- Strong genre match → boost
- Weak genre match → mild boost
- Disliked genre match → penalty

**Show raw score to user, NOT weighted score.** Present each pick with: title, raw score, vote count, and why it matches (cite specific preferences). Flag disliked-genre overlaps as caveats. Skip titles already in user's collection.

No profile → present top weighted picks, note it's based on community ratings only.
