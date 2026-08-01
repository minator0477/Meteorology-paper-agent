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
2. **`score.py`** — sends `candidates.json` to the Anthropic Messages API in batches (`batch_size`
   from `sources.yml`), with `interests.md` embedded in the system prompt as the scoring rubric.
   Expects a strict JSON array back (`id`, `score` 0-10, `reason`, `theme`); parses defensively and
   skips batches that fail to parse. Writes **every** candidate's verdict (including below-threshold
   ones) to `history/<today>.md` as a Markdown table — this is a free byproduct of the API calls
   already made, not an extra request. Then keeps only papers scoring >= `min_score`, sorted
   descending, and writes `scored.json`.
3. **`report.py`** — posts `scored.json` to a Discord webhook as embeds (color-coded by `theme`,
   max 10 embeds per message, chunked with a 1s delay between messages to respect rate limits).
   On success, appends the reported paper IDs into `state/seen.json` so they aren't re-reported.

Each step is independent and driven purely by the JSON file the previous step produced — there is
no shared in-process state. Re-running `score.py` or `report.py` alone works as long as the
upstream JSON file exists.

## Configuration

- **`sources.yml`** — pipeline config: journal ISSNs, OpenAlex author IDs to watch, `lookback_days`,
  Claude scoring `min_score` threshold, and `batch_size` for the scoring API calls. Author IDs must
  be looked up manually via `https://api.openalex.org/authors?search=<name>` (names alone are
  ambiguous).
- **`interests.md`** — free-text research interest profile injected verbatim into the Claude system
  prompt in `score.py`. This is the actual scoring rubric — edit it (not the Python) to change what
  counts as "interesting." It also documents the fixed set of theme tags
  (`tropical`/`midlatitude`/`seam`/`regional`/`method`/`other`) that `score.py` asks Claude to
  assign and that `report.py` uses for embed color-coding.

## Required environment variables

- `ANTHROPIC_API_KEY` — required by `score.py`.
- `ANTHROPIC_MODEL` — optional, defaults to `claude-sonnet-5` in `score.py` (drop to a smaller/
  cheaper model if candidate volume is high).
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

There is no test suite, linter, or build step configured in this repository.
