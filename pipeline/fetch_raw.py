"""Archive every view ESPN will serve, for every season, to data/raw.

This is the only script that talks to ESPN for real data. Everything downstream
reads the archive, never the network, so the site can be rebuilt years from now
when ESPN has forgotten the league ever existed.

Two shapes of request, because ESPN has two:

    season views   one call per year        -> data/raw/{year}/{view}.json.gz
    weekly views   one call per week        -> data/raw/{year}/weeks/{nn}/{view}.json.gz

The weekly split is not a preference. mBoxscore returns no lineups and
mTransactions2 returns zero transactions unless the request names a single
scoringPeriodId -- asking for the season as a whole silently returns less data
rather than failing, which is exactly the kind of thing that goes unnoticed for
a year. Verified against the live league on 2026-08-05.

Payloads are pseudonymized before they are written: no SWID and no real name
ever reaches data/raw. See identity.py.

    python3 pipeline/fetch_raw.py                     # everything, resumable
    python3 pipeline/fetch_raw.py --current-season-only
    python3 pipeline/fetch_raw.py --season 2021 --force
"""

import argparse
import gzip
import io
import json
import os
import sys
import time

import identity
from espn_client import (
    SEASON_VIEWS,
    WEEKLY_VIEWS,
    EspnError,
    fetch_view,
    load_cookies,
    load_league,
)

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
RAW = os.path.join(ROOT, "data", "raw")

# ESPN tolerates this comfortably; the whole backfill is only ~320 requests.
REQUEST_SPACING_SECONDS = 1.0


def season_path(year, view):
    return os.path.join(RAW, str(year), "%s.json.gz" % view)


def week_path(year, week, view):
    return os.path.join(RAW, str(year), "weeks", "%02d" % week, "%s.json.gz" % view)


def write_json_gz(path, payload):
    """Write compressed JSON deterministically. Returns True if bytes changed.

    Keys are sorted and the gzip mtime is pinned to 0 so that identical data
    produces identical bytes. Without that, every refresh would rewrite every
    file with a new timestamp and git would see the whole archive change weekly.
    """
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb", mtime=0) as handle:
        handle.write(body)
    data = buffer.getvalue()

    if os.path.exists(path):
        with open(path, "rb") as handle:
            if handle.read() == data:
                return False

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)
    return True


def read_json_gz(path):
    with gzip.open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


class Fetcher:
    def __init__(self, league, cookies, force=False, dry_run=False):
        self.league = league
        self.cookies = cookies
        self.force = force
        self.dry_run = dry_run
        self.harvest = {}
        self.requests = 0
        self.written = 0
        self.skipped = 0
        self.last_request = 0.0

    def _throttle(self):
        elapsed = time.time() - self.last_request
        if elapsed < REQUEST_SPACING_SECONDS:
            time.sleep(REQUEST_SPACING_SECONDS - elapsed)
        self.last_request = time.time()

    def grab(self, year, view, path, scoring_period=None, refetch=False):
        """Fetch one view unless the archive already has it.

        Returns the payload either way, because callers need mSettings to work
        out how many weeks to ask for and should not pay for it twice.
        """
        if os.path.exists(path) and not (self.force or refetch):
            self.skipped += 1
            return read_json_gz(path)

        if self.dry_run:
            print("    would fetch %s" % os.path.relpath(path, ROOT))
            return None

        self._throttle()
        payload, _url = fetch_view(
            self.league["id"], year, view, self.cookies, scoring_period=scoring_period
        )
        self.requests += 1

        clean = identity.sanitize(payload, self.harvest)
        if write_json_gz(path, clean):
            self.written += 1
        return clean


def season_weeks(settings):
    """How many scoring periods this season actually has data for.

    finalScoringPeriod is the last week of the fantasy season (regular season
    plus playoffs). latestScoringPeriod is how far the real world has gotten,
    and it runs past the fantasy season once a year finishes -- so the smaller
    of the two is the last week worth asking about. For a season that has not
    started, latestScoringPeriod is 0 and there is nothing to fetch.
    """
    status = settings.get("status") or {}
    first = status.get("firstScoringPeriod") or 1
    final = status.get("finalScoringPeriod") or 0
    latest = status.get("latestScoringPeriod") or 0
    last = min(final, latest)
    if last < first:
        return []
    return list(range(first, last + 1))


def fetch_season(fetcher, year, is_current):
    print("=== %d ===" % year)

    # The current season is still moving, so its files are always re-fetched;
    # finished seasons are frozen and only re-fetched with --force.
    refetch = is_current

    settings = fetcher.grab(
        year, "mSettings", season_path(year, "mSettings"), refetch=refetch
    )
    if settings is None:  # --dry-run
        print("  (dry run: cannot determine week count without mSettings)")
        return

    for view in SEASON_VIEWS:
        if view == "mSettings":
            continue
        try:
            fetcher.grab(year, view, season_path(year, view), refetch=refetch)
        except EspnError as exc:
            print("  %-16s FAIL %s" % (view, exc))

    weeks = season_weeks(settings)
    if not weeks:
        print("  no scoring periods yet -- season views only")
        return

    print("  weeks %d-%d" % (weeks[0], weeks[-1]))
    for week in weeks:
        for view in WEEKLY_VIEWS:
            try:
                fetcher.grab(
                    year,
                    view,
                    week_path(year, week, view),
                    scoring_period=week,
                    refetch=refetch,
                )
            except EspnError as exc:
                print("  wk%-2d %-16s FAIL %s" % (week, view, exc))


def archive_size():
    total = 0
    for dirpath, _dirs, files in os.walk(RAW):
        for name in files:
            total += os.path.getsize(os.path.join(dirpath, name))
    return total


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--season", type=int, action="append", help="only this season (repeatable)"
    )
    parser.add_argument(
        "--current-season-only",
        action="store_true",
        help="what the weekly refresh runs",
    )
    parser.add_argument(
        "--force", action="store_true", help="re-fetch seasons already archived"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    league = load_league()
    cookies = load_cookies()
    if not cookies:
        print("warning: no SWID/espn_s2 -- private leagues will 401\n")

    current = league["current_season"]
    if args.season:
        years = sorted(args.season)
    elif args.current_season_only:
        years = [current]
    else:
        years = list(range(league["first_season"], current + 1))

    print("league %s (%s), seasons %s\n" % (league["id"], league["name"], years))

    fetcher = Fetcher(league, cookies, force=args.force, dry_run=args.dry_run)
    for year in years:
        try:
            fetch_season(fetcher, year, is_current=(year == current))
        except EspnError as exc:
            print("  season failed: %s" % exc)
        print("")

    if fetcher.harvest:
        identity.save_local_identities(fetcher.harvest)
        added = identity.scaffold_owners(identity.load_local_identities())
        if added:
            print("added %d manager(s) to config/owners.ini: %s" % (len(added), ", ".join(added)))
            print("edit that file to set display names before building the site\n")

    print(
        "%d requests, %d files written, %d already archived, %.1f MB on disk"
        % (
            fetcher.requests,
            fetcher.written,
            fetcher.skipped,
            archive_size() / (1024.0 * 1024.0),
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
