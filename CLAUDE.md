# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single-file Python script (`morning_summary.py`) that fetches weather, sports,
news, and local-events data and renders it as a standalone HTML fragment (title,
`<style>`, and body markup — no `<html>`/`<head>` wrapper) at `output/briefing.html`.
It deliberately uses only the Python standard library so it runs anywhere without
a `pip install`.

## Running it

```
python3 morning_summary.py
```

Prints the output path on success. No build step, linter, or test suite exists in
this repo.

Optional environment variable:
- `TICKETMASTER_API_KEY` — enables the Local Events section. Without it, that
  section renders a placeholder message instead of failing.

## Running tests

```
python3 -m unittest discover -s tests
```

Tests use only `unittest`/`unittest.mock` (stdlib, matching the script itself)
and never touch the network — `get_weather`/`get_sports`/`get_news`/`get_events`
are tested by patching `morning_summary.fetch`. Run a single test with e.g.
`python3 -m unittest tests.test_morning_summary.FormatGameTests.test_completed_win`.

## Architecture

The script is organized as one `fetch_*`/`get_*` function per data source, all
called from `main()`, followed by a single `render()` that turns their results
into HTML:

- `get_weather()` — geocodes `ZIP_CODE` via zippopotam.us, then queries
  Open-Meteo for current conditions and today's forecast.
- `get_sports()` — pulls each team in `SPORTS_TEAMS` from ESPN's site API
  (`site.api.espn.com`), derives last/next game from the full schedule, and
  computes a W-L record for the schedule accordion.
- `get_news()` — parses RSS via `xml.etree.ElementTree` for each feed in
  `NEWS_FEEDS`.
- `get_events()` — queries the Ticketmaster Discovery API, gated on
  `TICKETMASTER_API_KEY`.

Each function returns a plain dict/list (never raises past its own `try/except`),
with an `"ok"`/`"error"` (or `"error"` key per item) convention so `render()` can
show a per-section error message instead of failing the whole page. To add a
data source, follow this same shape: a getter that never throws, plus a render
branch that checks its `ok`/`error` field.

`fetch()` is the shared HTTP helper. Note the `browser_ua` flag: some RSS hosts
(Finextra, WealthManagement.com) 403 the bare Python UA and need to look like a
browser, while ESPN's API does the opposite and 403s any *custom* UA — this is
why `get_sports()` calls `fetch(url, browser_ua=False)`.

To change what the briefing covers, edit the module-level config constants
rather than the function bodies: `ZIP_CODE`, `SPORTS_TEAMS` (ESPN sport slug +
team ID), `NEWS_FEEDS` (label + RSS URL), `WEATHER_CODES` (Open-Meteo weather
code → label).

All output is styled inline in `render()`'s `<style>` block using CSS custom
properties for a light/dark theme pair (`prefers-color-scheme` plus a
`data-theme` override).

## Deployment

`.github/workflows/publish.yml` regenerates the briefing daily (10:00 UTC cron,
plus `workflow_dispatch` and pushes to `main`) and publishes `output/briefing.html`
as `index.html` to GitHub Pages, at https://for-the-crown.github.io/morning-summary/.
The repo is public because GitHub Pages requires that on the free plan; there's
nothing sensitive in the code, and `TICKETMASTER_API_KEY` is a repo secret, never
committed. To add or update it: `gh secret set TICKETMASTER_API_KEY`.
