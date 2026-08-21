# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A weekly automated pipeline that watches a set of meteorology/climate journals and authors on
OpenAlex, scores new papers locally against a personal research-interest profile using sentence
embeddings, and posts the interesting ones to a Discord channel. Discord 👍/👎 reactions on past
posts are collected weekly and fed back into the scoring vectors (a Rocchio-style update), so the
scoring drifts toward what the user actually reacts positively to over time. Intended to run
unattended on a GitHub Actions cron schedule.

## Directory layout

```
.github/workflows/paper-digest.yml   # weekly cron entry point
scripts/fetch.py
scripts/score.py
scripts/report.py
scripts/collect_feedback.py
scripts/embedding_util.py            # shared model-loading helper + THEMES constant
config/sources.yml
config/interests.md
state/seen.json                      # committed back by the workflow after each run
state/reported_papers.json           # committed back; rolling window awaiting feedback
state/theme_vectors.json             # committed back; accumulated feedback vectors
history/YYYY-MM-DD.md                # committed back by the workflow after each run
```
`fetch.py` / `score.py` / `report.py` / `collect_feedback.py` all compute
`ROOT = Path(__file__).resolve().parent.parent`, i.e. they assume they run from `scripts/` one
level below the repo root — don't move them without updating that assumption. `candidates.json`
and `scored.json` are intermediate artifacts written to the repo root by `fetch.py`/`score.py` at
runtime (git-ignored, not meant to be committed).

## Pipeline / data flow

Four sequential scripts run in this order each week (`collect_feedback.py` runs *first*, so this
week's reaction feedback is folded into `theme_vectors.json` before this week's `score.py` runs):

0. **`collect_feedback.py`** — reads `state/reported_papers.json` (papers posted by `report.py` in
   previous runs, each with the Discord `message_id` it was posted as). For every entry still
   within `feedback.window_days` (`sources.yml`), calls the Discord Bot REST API to count 👍/👎
   reactors on that message; majority verdict wins, ties/no-reactions are ignored. Liked/disliked
   papers (skipping `theme: other`, which has no vector) are re-embedded and accumulated into a
   running per-theme sum vector in `state/theme_vectors.json` (`+=` liked, `-=` disliked — a
   Rocchio-style update). Entries whose window has expired are dropped from
   `reported_papers.json` regardless of outcome. No-ops cleanly if `reported_papers.json` doesn't
   exist yet (first-ever run).
1. **`fetch.py`** — queries the OpenAlex works API (no auth required) for papers from the journals
   (by ISSN) and authors (by OpenAlex author ID) listed in `sources.yml`, published within
   `lookback_days`. Deduplicates against `state/seen.json` (papers already reported in a previous
   run). Writes `candidates.json`.
2. **`score.py`** — scores `candidates.json` locally with sentence-embeddings, no LLM call. Parses
   `interests.md` into per-theme representative texts (one `## <theme>` section per tag in
   `tropical`/`midlatitude`/`seam`/`regional`/`method`), embeds them once with a `sentence-
   transformers` model (multilingual, since `interests.md` is Japanese and paper title/abstract are
   English — see `embedding.model` in `sources.yml`). If `state/theme_vectors.json` has accumulated
   feedback for a theme (and its `model` field matches the current `embedding.model`), that
   normalized delta is blended into the base vector at `embedding.feedback_weight` before scoring —
   otherwise scoring is identical to using `interests.md` alone. Then embeds each candidate's
   title+abstract and takes the cosine similarity to its best-matching (post-feedback) theme
   vector. That similarity is linearly mapped to a 0-10 score via
   `embedding.similarity_low`/`similarity_high` in `sources.yml` (below `similarity_low` → score 0
   and `theme: other`). Writes **every** candidate's verdict (including below-threshold ones) to
   `history/<today>.md` as a Markdown table — a free byproduct of the embedding pass, not an extra
   request. Then keeps only papers scoring >= `min_score`, sorted descending, and writes
   `scored.json`.
3. **`report.py`** — posts `scored.json` to Discord, **one embed per message** (not batched — a
   Discord reaction applies to a whole message, so each paper needs its own message for
   `collect_feedback.py` to attribute a reaction to the right paper). Posts via the webhook with
   `?wait=true` to get the created message's `id` back, then uses the Discord Bot token to
   pre-seed 👍/👎 reactions on it so the user only has to click (failures here are logged, not
   fatal). Before posting, the top `RECOMMEND_TOP_N` (5) papers by score have their `reason` field
   overwritten by a single Claude API call (`RECOMMEND_MODEL`, currently `claude-sonnet-5`) that
   takes each paper's title+abstract and writes a ~100-150 character Japanese recommendation
   reason explaining why it matches the researcher's interests — richer than the mechanical
   "embedding similarity to theme X" reason `score.py` writes for every candidate. Requires
   `ANTHROPIC_API_KEY`; if unset or the call/parse fails, silently falls back to the `score.py`
   reason (logged, not fatal) for those papers. On success, appends the reported paper IDs into
   `state/seen.json` (so they aren't re-reported) and appends `{id, message_id, theme, score,
   title, abstract, reported_date}` for each to `state/reported_papers.json` for
   `collect_feedback.py` to pick up later.

Re-running `score.py` or `report.py` alone works as long as the upstream JSON file exists, but
`collect_feedback.py` and `report.py` share state through `state/reported_papers.json` — running
`report.py` twice on the same `scored.json` will double-post and double-append entries.

## Configuration

- **`sources.yml`** — pipeline config: journal ISSNs, OpenAlex author IDs to watch, `lookback_days`,
  scoring `min_score` threshold, `batch_size` (embedding encode batch size), an `embedding:` block
  (`model`, `similarity_low`, `similarity_high` for score calibration, `feedback_weight` for how
  strongly `collect_feedback.py`'s learned vectors nudge the base theme vectors), and a `feedback:`
  block (`window_days`, how long a posted paper stays eligible for reactions). Author IDs must be
  looked up manually via `https://api.openalex.org/authors?search=<name>` (names alone are
  ambiguous).
- **`interests.md`** — free-text research interest profile, structured as one `## <theme>` section
  per theme tag. Each section's body is embedded as that theme's representative vector in
  `score.py` — this is the actual scoring rubric now, so edit the section text (keyword-dense,
  bilingual JA/EN helps) to change what counts as "interesting." The theme tags
  (`tropical`/`midlatitude`/`seam`/`regional`/`method`, plus `other` as the automatic fallback when
  no theme scores above `similarity_low`) are what `report.py` uses for embed color-coding.

## Required environment variables

- `DISCORD_WEBHOOK_URL` — required by `report.py`, for posting.
- `DISCORD_BOT_TOKEN` — required by `collect_feedback.py`; used by `report.py` to pre-seed 👍/👎
  reactions (soft-optional there — `report.py` just skips pre-seeding if unset).
- `DISCORD_CHANNEL_ID` — the channel `report.py` posts to and `collect_feedback.py` reads
  reactions from; same soft-optional/required split as `DISCORD_BOT_TOKEN`.
- `ANTHROPIC_API_KEY` — used by `report.py` to generate LLM recommendation reasons for the top 5
  papers (soft-optional — skipped, falling back to the mechanical embedding-similarity reason, if
  unset).
- `OPENALEX_MAILTO` — optional, used by `fetch.py` to join OpenAlex's "polite pool" for more
  reliable API access.

`score.py` runs entirely locally (no API key) — it downloads a `sentence-transformers` model on
first run (cached under `~/.cache/huggingface` afterward; the CI workflow caches this directory
across runs).

## One-time Discord bot setup (required for the feedback loop)

The existing `DISCORD_WEBHOOK_URL` can post messages but can't read reactions — reading reactions
needs a real bot. To enable `collect_feedback.py`:

1. Create a Discord Application + Bot in the [Developer Portal](https://discord.com/developers/applications),
   copy the bot token.
2. Invite the bot to the server with `View Channel`, `Read Message History`, and `Add Reactions`
   permissions, scoped to (at least) the channel the webhook posts to.
3. Enable Developer Mode in Discord, right-click the target channel → Copy Channel ID.
4. Add `DISCORD_BOT_TOKEN` and `DISCORD_CHANNEL_ID` as GitHub repo secrets (alongside the existing
   `DISCORD_WEBHOOK_URL`).

Until these are set, `report.py` still posts fine (just without pre-seeded reactions) but
`collect_feedback.py` will fail — it requires both env vars.

## Running locally

```
pip install -r requirements.txt
python scripts/collect_feedback.py  # -> updates state/theme_vectors.json (requires DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID)
python scripts/fetch.py    # -> candidates.json
python scripts/score.py    # -> scored.json (local embeddings, no API key needed)
python scripts/report.py   # -> posts to Discord, updates state/seen.json + state/reported_papers.json (requires DISCORD_WEBHOOK_URL)
```
Run these from the repo root (not from inside `scripts/`), since each script resolves paths via
`Path(__file__).resolve().parent.parent`.

There is no test suite, linter, or build step configured in this repository.
