# League History Dashboard

A static site for our fantasy football league, built from ESPN's fantasy API.

**Design principle:** this is not a second copy of the ESPN app. Live scores,
current rosters and this week's matchups all already exist in ESPN's own app and
are not worth rebuilding. This site exists for the data ESPN collects but never
surfaces — cross-season records, career head-to-head, luck vs. skill, draft
return on investment, and the long-memory stuff a league argues about.

Two surfaces: a **draft-day splash page** (countdown, draft order, dues) and the
**all-time analysis** behind it. See [ROADMAP.md](ROADMAP.md) for what is built
and what is coming.

## How it works

```
ESPN v3 API  ->  data/raw/{year}/{view}.json.gz   (archived, committed)
             ->  site/data/*.json                 (generated, committed)
             ->  site/                            (static HTML/CSS/JS, no build)
```

`site/` is entirely self-contained, so GitHub Pages publishes that one directory
and nothing needs a build step.

The raw archive is committed on purpose. ESPN's historical data has a habit of
becoming unavailable, and once a season is in `data/raw/` we never depend on
ESPN to hand it back to us again. It is gzipped — the same data uncompressed is
about 150 MB.

A GitHub Action re-runs the pipeline weekly during the season and commits any
changes; GitHub Pages serves `site/`.

## Privacy

The repo is public, so nothing personal goes in it. ESPN identifies managers by
SWID and ships their real names alongside; `pipeline/identity.py` replaces every
SWID with a deterministic `mgr_<hash>` id and strips the name fields **before**
anything is written to `data/raw/`.

Real names stay in `config/identities.local.json`, which is gitignored and never
leaves your laptop. The only names that reach git are the display strings you
write by hand in `config/owners.ini` — those are rendered on the site, so keep
them to whatever you're happy showing publicly.

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

## Configuration

| File | What it holds |
|---|---|
| `config/league.ini` | League id and season range. One place, so the fetcher, the site build and CI can't disagree. |
| `config/owners.ini` | Public display names, and `merge_into` links when one team's history spans several ESPN accounts. Read its header — two identity rules live there. |
| `config/draft.ini` | Everything on the splash page except the draft date, which comes from ESPN. |
| `.env` | ESPN auth cookies. Gitignored. |

## Pipeline

Stdlib only — no pip install, no venv.

Check what ESPN will actually return, season by season, before trusting it:

```bash
python3 pipeline/probe.py --league-id YOUR_ID --from 2015 --out probe-results.json
```

Pull and archive every view for every season. Resumable — files already archived
are skipped, so re-running is cheap and a failed backfill picks up where it left
off:

```bash
python3 pipeline/fetch_raw.py
```

Rebuild the site's JSON from the archive and config (no network):

```bash
python3 pipeline/build_site_data.py
```

Set the passphrase for the Launch Draft button (prompts hidden, prints a hash to
paste into `config/draft.ini`):

```bash
python3 pipeline/hash_passphrase.py
```

## Local preview

The site fetches its JSON, so `file://` will not work. Serve it:

```bash
python3 -m http.server 8017 --directory site
```

Then open http://localhost:8017.
