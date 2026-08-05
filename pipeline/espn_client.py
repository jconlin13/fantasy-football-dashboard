"""Minimal client for ESPN's fantasy football v3 API.

Stdlib only, so this behaves identically on a laptop and in CI with no venv.

ESPN serves the same league through two differently shaped endpoints:

    current season   /apis/v3/games/ffl/seasons/{year}/segments/0/leagues/{id}
                     -> a single JSON object

    past seasons     /apis/v3/games/ffl/leagueHistory/{id}?seasonId={year}
                     -> a JSON array containing one object

Which endpoint answers for which year is not documented and has changed over
time, so nothing here assumes: `fetch_view` tries every known candidate and
reports back which one worked. The probe script records those results so the
rest of the pipeline can stop guessing.
"""

import configparser
import gzip
import json
import os
import time
import urllib.error
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
LEAGUE_INI = os.path.join(ROOT, "config", "league.ini")

# Reads go to the dedicated read host; the older fantasy.espn.com host still
# answers and is kept as a fallback for seasons that 404 on the new one.
HOSTS = (
    "https://lm-api-reads.fantasy.espn.com",
    "https://fantasy.espn.com",
)

# Browser UA: ESPN returns 403 for the default urllib agent.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

# The views the dashboard needs. Requested one at a time -- asking for many at
# once makes ESPN silently drop some, which is invisible until data goes missing.
VIEWS = (
    "mSettings",       # scoring, roster slots, playoff format, season structure
    "mTeam",           # teams, owners, records, final standings
    "mRoster",         # rosters w/ per-player season stats
    "mMatchup",        # every matchup, incl. playoff bracket wiring
    "mMatchupScore",   # per-week scores
    "mDraftDetail",    # every pick, keeper flags, auction bids
    "mTransactions2",  # adds, drops, trades, waiver claims
    "mBoxscore",       # started vs benched -- needed for optimal-lineup analysis
)

# Views that describe a whole season and are fetched once per year.
SEASON_VIEWS = (
    "mSettings",
    "mTeam",
    "mRoster",
    "mMatchup",
    "mMatchupScore",
    "mDraftDetail",
)

# Views that only answer for one week at a time.
#
# Both of these return an empty or lineup-less payload when asked for the season
# as a whole -- mTransactions2 reports zero transactions, and mBoxscore omits
# rosterForCurrentScoringPeriod -- so they must be requested once per scoring
# period. This is not a documented behavior; it was found by probing the league.
WEEKLY_VIEWS = (
    "mBoxscore",
    "mTransactions2",
)


class EspnError(Exception):
    pass


def load_league():
    """Read config/league.ini -> {id, name, first_season, current_season}."""
    parser = configparser.ConfigParser()
    if not parser.read(LEAGUE_INI):
        raise EspnError("missing %s" % LEAGUE_INI)
    section = parser["league"]
    return {
        "id": section.get("id"),
        "name": section.get("name", ""),
        "first_season": section.getint("first_season"),
        "current_season": section.getint("current_season"),
    }


def load_cookies():
    """Read auth cookies from the environment, falling back to a local .env.

    Private leagues need SWID and espn_s2. Public leagues need neither, and
    this returns an empty dict.
    """
    cookies = {}
    env_path = os.path.join(os.path.dirname(__file__), os.pardir, ".env")
    if os.path.exists(env_path):
        with open(env_path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))

    swid = os.environ.get("SWID", "").strip()
    espn_s2 = os.environ.get("ESPN_S2", "").strip()
    if swid:
        # ESPN wants the braces; add them back if they were stripped on copy.
        if not swid.startswith("{"):
            swid = "{" + swid.strip("{}") + "}"
        cookies["SWID"] = swid
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    return cookies


def _candidate_urls(league_id, year, view, scoring_period=None):
    """Every endpoint shape that might answer for this season, best guess first."""
    week = "" if scoring_period is None else "&scoringPeriodId=%d" % scoring_period
    urls = []
    for host in HOSTS:
        urls.append(
            "%s/apis/v3/games/ffl/seasons/%d/segments/0/leagues/%s?view=%s%s"
            % (host, year, league_id, view, week)
        )
        urls.append(
            "%s/apis/v3/games/ffl/leagueHistory/%s?seasonId=%d&view=%s%s"
            % (host, league_id, year, view, week)
        )
    return urls


def _get(url, cookies, timeout=30):
    request = urllib.request.Request(url)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "application/json")
    request.add_header("Accept-Encoding", "gzip")
    if cookies:
        request.add_header(
            "Cookie", "; ".join("%s=%s" % (k, v) for k, v in cookies.items())
        )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        if response.headers.get("Content-Encoding") == "gzip":
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def fetch_view(league_id, year, view, cookies=None, retries=3, scoring_period=None):
    """Fetch one view for one season, optionally for a single scoring period.

    Returns (payload, url_that_worked). Raises EspnError if no candidate URL
    answers. The leagueHistory shape is unwrapped so callers always get an
    object, never a one-element list.
    """
    cookies = cookies or {}
    last_error = None

    for url in _candidate_urls(league_id, year, view, scoring_period):
        for attempt in range(retries):
            try:
                payload = _get(url, cookies)
            except urllib.error.HTTPError as exc:
                last_error = "HTTP %d at %s" % (exc.code, url)
                # 401/403 mean auth, not a bad URL -- other candidates will fail
                # the same way, and retrying will not help.
                if exc.code in (401, 403):
                    break
                if exc.code == 429:
                    time.sleep(2 ** attempt)
                    continue
                break
            except (urllib.error.URLError, TimeoutError) as exc:
                last_error = "%s at %s" % (exc, url)
                time.sleep(2 ** attempt)
                continue
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                # ESPN answers 200 with an HTML error page for seasons that
                # predate the league. That is a dead candidate, not a transport
                # problem -- move to the next URL instead of crashing the run.
                last_error = "non-JSON body at %s (%s)" % (url, exc)
                break

            if isinstance(payload, list):
                if not payload:
                    last_error = "empty array at %s" % url
                    break
                payload = payload[0]
            return payload, url

    raise EspnError(
        "could not fetch view %r for %d (last error: %s)" % (view, year, last_error)
    )
