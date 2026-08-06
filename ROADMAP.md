# Roadmap

What this site is, what has been built, and what is left. Last revised 2026-08-05.

## Checklist

- [x] **Phase 0** — Foundation: ESPN client, pseudonymization, probe
- [x] **Phase 1** — Archive 2018–2026 to `data/raw` (320 files, 11 MB, 0 PII)
- [x] **Phase 2** — Splash page: countdown, draft details, dues, order
- [x] **Phase 3** — Canonical model, 80/80 team-seasons match ESPN, champions confirmed
- [x] **Phase 4** — Records, head-to-head, luck vs. skill
  - [x] Third-place game counts; other consolation games do not
- [x] **Phase 5** — Lineups, draft, trades
  - [x] Starting-slot identification verified against team totals (60/60)
  - [x] Optimal-lineup solver + efficiency (exact assignment, 1,186 team-weeks, 0 violations)
  - [x] Draft-pick return (labelled honestly — it tracks roster churn, not draft skill)
  - [x] Trade market summary (full retrospectives not possible — see below)
- [x] **Phase 6** — All-Time Analysis page (7 tabbed sections, mobile-verified)
- [ ] **Phase 7** — Automation, GitHub Pages, launch
  - [x] Fetcher exits non-zero on failure (was exiting 0 and deploying stale data)
  - [x] Validation gate in CI before any deploy
  - [x] Separate deploy workflow, needs no ESPN secrets
  - [ ] `SWID` / `ESPN_S2` in Actions secrets — **needs you**
  - [ ] Pages deployment failing — reaches `in_progress` then fails with no reason given.
        Check Settings → Pages is set to **GitHub Actions**, not "Deploy from a branch";
        the API reports `build_type: workflow` but still carries a branch source.
- [ ] **Phase 8** — Backlog

**Open questions for the commissioner:** whether to swap draft return for a season-total
measure that isolates draft skill but only covers ~75% of picks.
**Awaiting from the commissioner:** `SWID` and `ESPN_S2` in Settings → Secrets and
variables → Actions (the weekly refresh cannot run without them); splash page values (location, dues, Venmo link,
draft order once announced, passphrase or a decision to skip the gate).

## Scope

The governing rule: live scores and standings already exist in the ESPN app, so this site
is *"a layer of otherwise unaccessible data that's cool to look at, not a regurgitation of
data people will already be seeing."* Feature ideas that amount to mirroring a screen ESPN
already ships get turned down.

The site has **two surfaces**:

1. **Splash / home page** — draft date, countdown, draft order with who's paid, a Launch
   Draft button, a Pay Dues button. Modeled on the top of
   [440andfriends.com](https://www.440andfriends.com): rounded cards on a light field, heavy
   display type, one accent color, stacking cleanly on a phone.
2. **All-Time Analysis** — the real project. Records, head-to-head, luck vs. skill, lineup
   efficiency, draft ROI, trades.

The splash page's value **expires on draft day**; the analysis section's only grows. So the
splash shipped first even though the analysis is the main push.

## Ground truth

Verified by probing the live ESPN API on 2026-08-05, not inferred. Several of these
determined the design.

| Fact | Detail |
|---|---|
| **History starts 2018** | 2017 and earlier return an HTML error page, not JSON. Eight complete seasons (2018–2025) plus 2026. That is the entire archive. |
| Endpoint shape | Every season 2018–2026 answers on the modern `seasons/{year}/segments/0/leagues/{id}` path; the `leagueHistory` fallback is never needed for this league. |
| Season structure | 13 regular-season weeks (2018–2020) → 14 (2021–2026); 16–17 total scoring periods; 6 playoff teams throughout. Read per season, never hardcoded. |
| **Transactions need `scoringPeriodId`** | Bare `mTransactions2` returns **0 transactions in every season**. With `&scoringPeriodId=3` it returns 20. Asking for the season as a whole silently returns less data rather than failing. |
| **Lineups need `scoringPeriodId`** | Bare `mBoxscore` returns no lineups at all; with a scoring period it returns every one. Started-vs-benched exists **only** per week. |
| Week counts | `status.finalScoringPeriod` capped by `status.latestScoringPeriod`. For an unstarted season the latter is 0 — nothing to fetch yet. |
| Draft date | `settings.draftSettings.date` is epoch ms, and the key is **absent** until the draft is scheduled. Missing is a trustworthy "not set". |
| Size | Weekly boxscore ≈ 955 KB raw / 83 KB gzipped. Measured: ~1.0 MB per season gzipped, 11 MB total. |

---

## Phase 0 — Foundation ✅

- `pipeline/espn_client.py` — stdlib-only client, multi-host/multi-shape URL fallback, gzip,
  browser UA, 429 backoff. Reuse it; don't write a second HTTP path.
- `pipeline/identity.py` — SHA-256 pseudonymization of SWIDs, PII stripping via a generic
  tree walk, gitignored local name map, `owners.ini` scaffolding, `resolve()`. **The identity
  layer for the whole project** — every analytic joins on `resolve()`.
- `pipeline/probe.py`, the CI workflow, `.gitignore`.

## Phase 1 — Archive the history ✅

Every byte ESPN will give us is on disk and committed, so ESPN can never take the league's
history away.

- `config/league.ini` — league id, name, first/current season, in one place so the fetcher,
  the build and CI can't disagree.
- `pipeline/fetch_raw.py` — season views once a year; `mBoxscore` and `mTransactions2` once a
  week. Sanitizes every payload through `identity.sanitize()` before writing.
- Deterministic writes (sorted keys, gzip `mtime=0`) so a refresh that changes nothing
  produces no diff. Without it, every weekly run would rewrite all 320 files.
- Resumable: existing files are skipped, finished seasons are frozen, the current season is
  always re-fetched because it is still moving.
- `espn_client` now treats a non-JSON body as a dead candidate URL instead of letting
  `JSONDecodeError` escape `fetch_view`, and accepts `scoring_period`.

**Verified:** re-run makes 0 requests and 0 writes. 320 files, 11 MB. A scan of every
archived file finds 0 SWIDs and 0 name fields, with 4,288 `mgr_*` ids in their place.

## Phase 2 — Splash page ✅

**Two data sources, split on purpose.** The draft date comes from **ESPN** — schedule it on
the league page and the next refresh counts down to the same clock the draft room runs on.
Everything else (location, dues, Venmo link, draft order with paid flags) is hand-edited in
`config/draft.ini`. Cards with no data hide themselves, so the page shortens rather than
showing empty boxes; with no draft scheduled it reads "Not set" and drops the countdown.

**The draft order is deliberately not pulled from ESPN.** ESPN exposes a 180-pick sequence
for the upcoming season with team ids attached, but while the draft is unscheduled and
`orderType` is `MANUAL` that sequence is its default placeholder. Publishing it would
announce an order that isn't real.

**On the Launch Draft gate.** The site is static, so the check runs in the visitor's browser
and is a speed bump, not security. `draft.ini` holds only a SHA-256, generated by
`pipeline/hash_passphrase.py` from a hidden prompt; blank means no gate. Encrypting the ESPN
link was considered and dropped — the draft URL is built from the league id, which is public
in `league.ini`, so there is nothing to hide. **ESPN's own login is the real boundary.**

**Verified** at 375px and desktop, no console errors.

## Phase 3 — Canonical league model ✅

One normalized model that every analytic reads, so ESPN's quirks don't leak into eight
different metrics.

✅ `config/owners.ini` resolved: **15 ESPN accounts → 11 managers** (the 10 currently active
plus one who played only 2018). Four merges, each verified against exact first- and
last-name matches in the local identity map rather than guessed from display names.

**Two identity rules the analytics must honor**, also written into the `owners.ini` header:

1. **Merge on teams, not on people.** A team is one opponent for its whole history, however
   many people managed it. Two league members genuinely co-managed one team for five
   seasons; the league never held two records against it, so the co-manager merges into the
   owner whose team it has always been.
2. **Managers who left still count.** A manager who had their own team and no longer plays
   is neither merged nor filtered — everyone else's career record against them is real and
   has to keep adding up. Never drop a manager for being absent from the current season.

Rule 2 is a live trap: building the manager list from the current season's teams is the
natural implementation and would silently erase every departed manager.

✅ `pipeline/model.py` — `managers`, `seasons`, and `games`: one row per team per week, two
rows facing each other per matchup. Records, head-to-head and luck are all just different
groupings of that one table.

**Consolation games do not count; the third-place game does.** Fifth- and seventh-place
games are placement only, but the third-place game is contested by the two teams still alive
going into the last round and the league takes it seriously. Those look identical if you
only go by the week they are played, so they are told apart by *when each team was knocked
out*: the third-place game is the one in the final week between two teams eliminated in the
round immediately before it. That finds exactly one such game in each of the eight seasons,
and 2025's (3rd vs 4th) matches ESPN's final ranks. ESPN's own `playoffTierType` is null on every
matchup here, so the championship bracket is reconstructed by walking it forward: playoff
teams start alive, a game between two live teams is a championship game, its loser is out,
a bye keeps you alive. Replaying 2025 reproduces ESPN's `rankCalculatedFinal` for all ten
teams in order.

**A third identity rule, learned the hard way:** ESPN records who held the *account*, which
is not always who the *team* was. In 2018 the commissioner drafted on another manager's
behalf using his own email, so ESPN shows one account owning two teams — indistinguishable
in the payload from genuinely running two. The `[teams]` section of `owners.ini` states the
truth per season, and `model.py` now raises rather than continues if two teams in a season
resolve to one manager, because that silently sums two teams' results into one row.

**Verified:** `pipeline/validate_model.py` checks computed records against ESPN's own stored
`record.overall` — **80 of 80 team-seasons match.** It does not assume what ESPN counts; it
computes both definitions and reports which agrees (the answer is regular season only,
consistently). Matching ESPN's records proves the arithmetic, not that the right team is
named champion — so the eight champions the bracket walk derives were confirmed separately
from memory by the commissioner. Both gates passed.

## Phase 4 — Records, head-to-head, luck ✅ (computed; not yet on the site)

Definitions matter more than code here — these are the numbers the league will argue about.
All three live in `pipeline/analytics.py` rather than the `analytics/` package this roadmap
originally sketched: they are the same `games` table grouped three ways, and splitting them
across files would have separated things that share every helper. Phase 5 reads different
tables and gets its own module.

**Two invariants are now enforced by `validate_model.py`**, because both would catch
double-counting or dropped games that look entirely reasonable in the output:

- League-wide wins must be exactly half of all team-game rows (545 of 1090).
- Luck must sum to zero across the league, since expected wins only redistribute the same
  wins. Currently +0.00.

- **Records book** — highest/lowest week, biggest blowout, narrowest win, longest streaks,
  best/worst season, most points in a loss. Regular season and playoffs kept separate.
- **Career head-to-head** — manager × manager matrix: record, average margin, longest streak,
  playoff meetings called out separately.
- **Luck vs. skill** — per team-week, the all-play record (points vs. every other team that
  week). Expected wins = sum of weekly all-play win percentages. **Luck = actual − expected.**
  In one sentence: *"you'd have won N games against an average schedule; you won M."*

**Exit criteria:** every number reproducible by hand from `games`; every metric ships with a
one-line plain-English definition beside it.

## Phase 5 — Lineups, draft, trades

- **Optimal-lineup efficiency** — best legal lineup from that week's roster, using the
  season's actual `lineupSlotCounts`. Slot eligibility and starter counts changed across
  eight years, so read them, never assume. Efficiency = actual ÷ optimal.
- **Draft ROI** — season points per pick vs. the average for that draft slot, by round and
  manager.
- **Trade retrospectives** — points produced by each side *after* the trade date.

**Risk:** optimal-lineup is the most involved analytic and the most exposed to rule drift.
If time gets tight, land it last — the per-week data is already archived, so shipping it
later costs only time.

**Exit criteria:** spot-check three known weeks by hand against ESPN's own box scores.

## Phase 6 — Analysis section

- `pipeline/build_site_data.py` writes `site/data/*.json` from the model. No network, so it
  is reproducible and reviewable in a diff.
- Pages: Records Book, Head-to-Head matrix, Luck vs. Skill, Lineup Efficiency, Draft &
  Trades, and a Manager page pulling one person's whole career onto a single screen.
- **Readability is a requirement, not a polish item.** Carry the splash page's visual
  language — cards, generous spacing, one accent color, big numbers with small labels — so
  the two surfaces feel like one site. Every stat carries its one-sentence definition; a
  number nobody can explain gets argued *about* instead of *with*.

**Exit criteria:** every page renders real data at phone width.

## Phase 7 — Automation and launch

- `refresh.yml`: make the fetch step fail loudly rather than silently deploying stale data.
- Enable GitHub Pages, publish, confirm the URL.
- Trigger the workflow end-to-end manually **before** Week 1, so its first real run isn't
  its first run ever.
- Consider committing `probe-results.json` — currently gitignored, and it is the only record
  of what ESPN actually returns per season.

**Exit criteria:** a `workflow_dispatch` run pulls the current week, rebuilds, commits and
deploys with no manual step.

## Phase 8 — Backlog

Playoff-odds simulation; "what if you had every other schedule" season shuffling; keeper
value tracking; power-ranking history; positional tendencies; an annual recap page. All
additive.

---

## Verification

- **Privacy gate, every phase:** scan the committed tree for SWID patterns and real last
  names. Only `mgr_*` ids and `owners.ini` display names may appear.
- **Local preview.** The site fetches its JSON, and `crypto.subtle` (the passphrase gate)
  only exists in a secure context, so `file://` will not work. Serve it:

  ```bash
  python3 -m http.server 8017 --directory site
  ```

**Governing test:** a number on this site is correct when you can check it the obvious way —
look it up in the ESPN app, or ask the guy it's about — and it matches. Anything that can't
survive that check doesn't ship.
