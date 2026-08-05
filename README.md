# League History Dashboard

A static site showing our fantasy football league's all-time history, built from
ESPN's fantasy API.

**Design principle:** this is not a second copy of the ESPN app. Live scores,
current rosters and this week's matchups all already exist in ESPN's own app and
are not worth rebuilding. This site exists for the data ESPN collects but never
surfaces — cross-season records, career head-to-head, luck vs. skill, draft
return on investment, and the long-memory stuff a league argues about.

## How it works

```
ESPN v3 API  ->  data/raw/{year}/{view}.json   (archived, committed)
             ->  site/data/*.json              (generated, committed)
             ->  site/                          (static HTML/CSS/JS, no build)
```

`site/` is entirely self-contained, so GitHub Pages publishes that one directory
and nothing needs a build step.

The raw archive is committed on purpose. ESPN's historical data has a habit of
becoming unavailable, and once a season is in `data/raw/` we never depend on
ESPN to hand it back to us again.

A GitHub Action re-runs the pipeline weekly during the season and commits any
changes; GitHub Pages serves `site/`.

## Setup

Private leagues need two auth cookies:

```bash
cp .env.example .env
# then fill in SWID and ESPN_S2
```

Get them from Chrome: sign in at fantasy.espn.com, then DevTools → Application →
Cookies → `https://fantasy.espn.com`. `.env` is gitignored.

The scheduled refresh runs on GitHub's servers and cannot see your `.env`, so the
same two values also go in the repo's **Settings → Secrets and variables →
Actions**, named `SWID` and `ESPN_S2`. Two copies, neither of them committed.

## Pipeline

Check what ESPN will actually return, season by season, before trusting it:

```bash
python3 pipeline/probe.py --league-id YOUR_ID --from 2015 --out probe-results.json
```

Pull and archive every view for every season:

```bash
python3 pipeline/fetch_raw.py
```

Rebuild the site's JSON from the archive (no network):

```bash
python3 pipeline/build_site_data.py
```

Stdlib only — no pip install, no venv.
