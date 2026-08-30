# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A weekly automated pipeline that watches a set of meteorology/climate journals and authors on
OpenAlex, uses the Claude API to score new papers against a personal research-interest profile,
and posts the interesting ones to a Discord channel via webhook. Intended to run unattended on a
GitHub Actions cron schedule.

## Directory layout

```
.github/workflows/paper-digest.yml   # weekly cron entry point
scripts/fetch.py
scripts/score.py
scripts/report.py
config/sources.yml
config/interests.md
config/keywords.yml                  # keyword lists for score.py's keyword-match stage
state/seen.json                      # committed back by the workflow after each run
history/YYYY-MM-DD.md                # committed back by the workflow after each run
```
`fetch.py` / `score.py` / `report.py` all compute `ROOT = Path(__file__).resolve().parent.parent`,
i.e. they assume they run from `scripts/` one level below the repo root — don't move them without
updating that assumption. `candidates.json` and `scored.json` are intermediate artifacts written to
the repo root by `fetch.py`/`score.py` at runtime (git-ignored, not meant to be committed).

## Pipeline / data flow

Three sequential scripts, each reading the previous step's JSON output:

1. **`fetch.py`** — queries the OpenAlex works API (no auth required) for papers from the journals
   (by ISSN) and authors (by OpenAlex author ID) listed in `sources.yml`, published within
   `lookback_days`. Deduplicates against `state/seen.json` (papers already reported in a previous
   run). Writes `candidates.json`.
2. **`score.py`** — picks candidates in three stages.
   - **Stage 1 (keyword match)** — for each candidate, checks the title (case-insensitive
     substring) against the per-theme keyword lists in `config/keywords.yml`. Any match is picked
     up immediately, tagged with that theme, and unconditionally included in the output (not
     subject to `min_score` — no scoring LLM call happens for these). If a candidate matches
     keywords under multiple themes, the theme is chosen by the order themes appear in
     `keywords.yml` (`seam` first).
   - **Stage 2 (LLM scoring, Haiku)** — only candidates that didn't match any keyword go to the
     Anthropic Messages API (model `ANTHROPIC_MODEL`, default `claude-haiku-4-5` — cheap, since
     this runs over every unmatched candidate), in batches (`batch_size` from `sources.yml`).
     Each candidate is sent as **title + journal only** (no abstract, to keep this stage cheap);
     `interests.md` is embedded in the system prompt as the scoring rubric. Expects a strict JSON
     array back (`id`, `score` 0-10, `reason`, `theme`); parses defensively and skips batches that
     fail to parse. Only these are filtered against `min_score`; the `reason` it returns here is a
     throwaway fallback (see Stage 3).
   - **Stage 3 (recommendation reason, Sonnet)** — every paper kept by Stage 1 or Stage 2 (i.e.
     everything that will actually be posted) goes to a second Claude call (model
     `ANTHROPIC_REASON_MODEL`, default `claude-sonnet-5` — only runs over the much smaller kept
     set, so the higher-quality/cost model is affordable here), this time **including the
     abstract**, asking for a better-written recommendation reason grounded in `interests.md`. On
     success this overwrites `reason` for that paper; on failure (call or JSON parsing) it's
     logged and the paper keeps its Stage 1/2 fallback reason (`キーワード「<matched keyword>」に
     一致` for keyword matches, the Stage 2 throwaway reason for LLM-scored ones) — not fatal.

   Writes **every** candidate's verdict from all stages (including below-threshold Stage 2 ones)
   to `history/<today>.md` as two separate Markdown tables — a "キーワード一致で採用" section
   (Stage 1 matches, with the matched keyword) and an "LLM 採点" section (all Stage 2 candidates,
   with a ✅ column for whoever cleared `min_score`) — the Stage 2 part is a free byproduct of the
   API calls already made, not an extra request. Keeps all Stage 1 matches plus Stage 2 papers
   scoring >= `min_score`, sorted descending by score, tags each with `method: "keyword" | "llm"`
   (plus `matched_keyword` for Stage 1 ones), and writes `scored.json`.
3. **`report.py`** — posts `scored.json` to a Discord webhook as embeds (color-coded by `theme`,
   max 10 embeds per message, chunked with a 1s delay between messages to respect rate limits).
   Each embed's second line reflects `method`: Stage 1 papers show `🔑 キーワード一致「<keyword>」`
   instead of a score (the fixed `KEYWORD_SCORE` isn't a meaningful number to display), Stage 2
   papers show `🤖 LLM採点 score X/10`. The header on the first message in the batch also breaks
   down the count by method (`🔑キーワード一致 N 件 / 🤖LLM採点 M 件`). On success, appends the
   reported paper IDs into `state/seen.json` so they aren't re-reported.

Each step is independent and driven purely by the JSON file the previous step produced — there is
no shared in-process state. Re-running `score.py` or `report.py` alone works as long as the
upstream JSON file exists.

## Configuration

- **`sources.yml`** — pipeline config: journal ISSNs, OpenAlex author IDs to watch, `lookback_days`,
  Claude scoring `min_score` threshold, and `batch_size` for the scoring API calls. Author IDs must
  be looked up manually via `https://api.openalex.org/authors?search=<name>` (names alone are
  ambiguous).
- **`interests.md`** — free-text research interest profile injected verbatim into the Claude system
  prompt in both `score.py`'s Stage 2 (LLM scoring) and Stage 3 (recommendation reason). This is
  the scoring rubric for whatever Stage 1 doesn't already catch — edit it (not the Python) to
  change what counts as "interesting." It also documents the fixed set of theme tags
  (`tropical`/`midlatitude`/`seam`/`regional`/`method`/`other`) that `score.py` asks Claude to
  assign and that `report.py` uses for embed color-coding.
- **`keywords.yml`** — per-theme keyword lists for `score.py`'s Stage 1 (keyword match). A title/
  abstract hit on any keyword bypasses the LLM entirely for that candidate. Edit this to tune which
  obviously-relevant papers get picked up for free before the LLM budget is spent on the rest.

## Required environment variables

- `ANTHROPIC_API_KEY` — required by `score.py`.
- `ANTHROPIC_MODEL` — optional, defaults to `claude-haiku-4-5`. Used for `score.py`'s Stage 2
  scoring call (runs over every keyword-unmatched candidate, so kept cheap).
- `ANTHROPIC_REASON_MODEL` — optional, defaults to `claude-sonnet-5`. Used for `score.py`'s Stage 3
  recommendation-reason call (runs only over the papers actually being kept, so a stronger/pricier
  model is affordable there).
- `DISCORD_WEBHOOK_URL` — required by `report.py`.
- `OPENALEX_MAILTO` — optional, used by `fetch.py` to join OpenAlex's "polite pool" for more
  reliable API access.

## Running locally

```
pip install -r requirements.txt
python scripts/fetch.py    # -> candidates.json
python scripts/score.py    # -> scored.json (requires ANTHROPIC_API_KEY)
python scripts/report.py   # -> posts to Discord, updates state/seen.json (requires DISCORD_WEBHOOK_URL)
```
Run these from the repo root (not from inside `scripts/`), since each script resolves paths via
`Path(__file__).resolve().parent.parent`.

## Testing

```
pip install -r requirements-dev.txt
python -m pytest tests/
```
Tests live in `tests/` and cover the pure/parsing logic in `fetch.py`, `score.py`, and `report.py`
(keyword matching, JSON/abstract parsing, embed building, history-table formatting, the
keyword-match/LLM-scoring split in `score.main()`). All Anthropic/Discord/OpenAlex HTTP calls are
monkeypatched with dummy responses — no real API calls, and no `ANTHROPIC_API_KEY`/
`DISCORD_WEBHOOK_URL` values are needed beyond the dummy ones `tests/conftest.py` sets (those two
env vars are read at import time by `score.py`/`report.py`). File I/O (`CAND_PATH`, `OUT_PATH`,
`HISTORY_DIR`, `SCORED_PATH`, `SEEN_PATH`) is monkeypatched to a pytest `tmp_path` per test so
tests never touch the real `state/`, `history/`, `candidates.json`, or `scored.json`. There is no
linter or build step configured.
