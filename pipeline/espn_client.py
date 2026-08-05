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

import gzip
import json
import os
import time
import urllib.error
import urllib.request

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


class EspnError(Exception):
    pass


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


def _candidate_urls(league_id, year, view):
    """Every endpoint shape that might answer for this season, best guess first."""
    urls = []
    for host in HOSTS:
        urls.append(
            "%s/apis/v3/games/ffl/seasons/%d/segments/0/leagues/%s?view=%s"
            % (host, year, league_id, view)
        )
        urls.append(
            "%s/apis/v3/games/ffl/leagueHistory/%s?seasonId=%d&view=%s"
            % (host, league_id, year, view)
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


def fetch_view(league_id, year, view, cookies=None, retries=3):
    """Fetch one view for one season.

    Returns (payload, url_that_worked). Raises EspnError if no candidate URL
    answers. The leagueHistory shape is unwrapped so callers always get an
    object, never a one-element list.
    """
    cookies = cookies or {}
    last_error = None

    for url in _candidate_urls(league_id, year, view):
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

            if isinstance(payload, list):
                if not payload:
                    last_error = "empty array at %s" % url
                    break
                payload = payload[0]
            return payload, url

    raise EspnError(
        "could not fetch view %r for %d (last error: %s)" % (view, year, last_error)
    )
