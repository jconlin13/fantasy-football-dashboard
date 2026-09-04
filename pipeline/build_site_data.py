"""Turn config and the raw archive into the JSON the site reads.

Never touches the network. Everything it needs is already in the repo, so the
site can be rebuilt from a fresh clone with no cookies and no ESPN.

    python3 pipeline/build_site_data.py

Writes site/data/*.json. Right now that is the splash page's draft.json; the
all-time analysis feeds get added here as they land.
"""

import argparse
import configparser
import datetime
import gzip
import json
import os
import sys

from espn_client import load_league

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
CONFIG = os.path.join(ROOT, "config")
RAW = os.path.join(ROOT, "data", "raw")
SITE_DATA = os.path.join(ROOT, "site", "data")


def write_json(name, payload):
    """Write one site feed. Returns True if the bytes changed.

    Sorted and newline-terminated so a refresh that changes nothing produces no
    diff, and a refresh that changes something produces a readable one.
    """
    path = os.path.join(SITE_DATA, name)
    body = json.dumps(payload, indent=2, sort_keys=True) + "\n"

    if os.path.exists(path):
        with open(path) as handle:
            if handle.read() == body:
                print("  %-20s unchanged" % name)
                return False

    os.makedirs(SITE_DATA, exist_ok=True)
    with open(path, "w") as handle:
        handle.write(body)
    print("  %-20s written" % name)
    return True


def parse_order(parser):
    """[order] lines -- '3 = Jack C., paid' -> ordered picks with a status badge.

    Sorted by pick number rather than file order, so the file can be edited out
    of sequence without the site rendering out of sequence.
    """
    if not parser.has_section("order"):
        return []

    picks = []
    for key, value in parser.items("order"):
        name, _, status = value.partition(",")
        name = name.strip()
        if not name:
            continue
        try:
            pick = int(key)
        except ValueError:
            continue
        picks.append(
            {"pick": pick, "name": name, "status": status.strip().lower() or None}
        )
    return sorted(picks, key=lambda item: item["pick"])


def espn_draft_datetime(year):
    """The draft time ESPN itself holds for this season, or None if unscheduled.

    settings.draftSettings.date is epoch milliseconds. When the commissioner has
    not scheduled the draft yet, ESPN omits the key entirely rather than sending
    a placeholder -- 2026 has no `date`, while every drafted season 2018-2025 has
    a real one. So "key missing" is a trustworthy "not set", and there is no need
    to guess at what a sentinel value might mean.

    Returned as an ISO string with a real UTC offset, because epoch ms is an
    absolute instant and the countdown should not depend on anyone's timezone.
    """
    path = os.path.join(RAW, str(year), "mSettings.json.gz")
    if not os.path.exists(path):
        return None

    with gzip.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))

    stamp = ((payload.get("settings") or {}).get("draftSettings") or {}).get("date")
    if not stamp:
        return None

    moment = datetime.datetime.fromtimestamp(
        stamp / 1000.0, datetime.timezone.utc
    ).astimezone()
    return moment.isoformat()


def espn_league_name(year):
    """The league's name exactly as its commissioner set it in ESPN.

    settings.name -- the same field every other view already carries, so no
    extra request. Read once here rather than hand-typed into config, because
    a name typed in two places (ESPN's own settings and a local config file)
    is two places for it to quietly drift apart. Returns None if that
    season's archive does not exist yet.
    """
    path = os.path.join(RAW, str(year), "mSettings.json.gz")
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rb") as handle:
        payload = json.loads(handle.read().decode("utf-8"))
    name = (payload.get("settings") or {}).get("name")
    return name.strip() if name else None


def venmo_url(dues):
    """Build a Venmo profile link from just a handle -- config/draft.ini holds
    `venmo_username`, not a full URL, because everyone already knows their own
    handle as "@something" (that's how Venmo shows it everywhere) and nobody
    should have to go work out the URL pattern themselves.

    Forgiving of how people actually type it: a leading @ (stripped), or the
    full profile URL pasted in instead of just the handle (the handle is
    pulled back out of it). Empty in, empty out.
    """
    raw = (dues.get("venmo_username", "") if dues else "").strip()
    if not raw:
        return ""
    if "venmo.com/u/" in raw:
        raw = raw.rsplit("venmo.com/u/", 1)[-1]
    raw = raw.strip("/ ").lstrip("@")
    return "https://venmo.com/u/%s" % raw if raw else ""


def build_draft():
    parser = configparser.ConfigParser()
    if not parser.read(os.path.join(CONFIG, "draft.ini")):
        raise SystemExit("missing config/draft.ini")

    draft = parser["draft"] if parser.has_section("draft") else {}
    dues = parser["dues"] if parser.has_section("dues") else {}

    def get(section, key):
        value = section.get(key, "") if section else ""
        value = (value or "").strip()
        # "TBD" is a real answer for the reader but not a value worth linking.
        return value

    # ESPN is the source of truth for when the draft is -- it is the same clock
    # the draft room runs on, and it updates itself the moment you schedule it.
    # The config value is only an override, for announcing a date before it is
    # set in ESPN. Neither one present means the draft genuinely is not
    # scheduled, and the page says so rather than counting down to a guess.
    league = load_league()
    year = league["current_season"]
    from_espn = espn_draft_datetime(year)
    override = get(draft, "datetime")
    when = override or from_espn or ""

    if override and from_espn and override != from_espn:
        print("  note: config datetime overrides ESPN's %s" % from_espn)
    elif from_espn:
        print("  draft time from ESPN: %s" % from_espn)
    elif not override:
        print("  draft not scheduled in ESPN yet -- page will say Not set")

    # Same pattern as the date: ESPN's own league name wins by default, and
    # `label` in draft.ini only overrides it for someone who wants a headline
    # different from what they typed into ESPN's league settings. Nobody has
    # to type their league's name anywhere for the default case to work.
    league_name = espn_league_name(year)
    label_text = get(draft, "label") or league_name or "Fantasy Football"

    # Deliberately no teamId in this URL -- .../team?...&teamId=1 would send
    # every visitor to whichever team happens to own that id, regardless of
    # who is logged in. The plain league URL resolves to whoever is actually
    # signed in. Built from league.ini rather than typed by hand, so it can
    # never drift out of sync with the league id configured there.
    espn_url = "https://fantasy.espn.com/football/league?leagueId=%s&seasonId=%d" % (
        league["id"],
        year,
    )

    return {
        "label": "%s %d" % (label_text, year),
        "leagueName": league_name,
        "kind": get(draft, "kind"),
        "datetime": when,
        "datetimeSource": "config" if override else ("espn" if from_espn else None),
        "location": get(draft, "location"),
        "espnUrl": espn_url,
        "passphraseSha256": get(draft, "passphrase_sha256").lower(),
        "dues": {"amount": get(dues, "amount"), "venmoUrl": venmo_url(dues)},
        "order": parse_order(parser),
    }


def build_analysis():
    """Everything the All-Time Analysis page renders, in one feed.

    One file rather than six: the whole thing is a couple of hundred kilobytes,
    and a single fetch means switching between sections on the page costs
    nothing. Split it if it ever stops being small.
    """
    # Imported here so the splash page can still be rebuilt on a machine with no
    # archive -- config/draft.ini is all draft.json needs.
    import analytics
    import draft as draft_analytics
    import lineups as lineup_analytics
    from model import load_league_history

    history = load_league_history()
    lineup_rows = lineup_analytics.load_lineups(history)
    pick_rows = draft_analytics.draft_returns(history)

    return {
        "generated": datetime.date.today().isoformat(),
        "leagueName": espn_league_name(load_league()["current_season"]),
        "firstSeason": min(history.seasons) if history.seasons else None,
        "lastSeason": max(
            (year for year, season in history.seasons.items() if season.complete),
            default=None,
        ),
        "seasons": analytics.season_summaries(history),
        "managers": analytics.manager_careers(history),
        "records": analytics.records_book(history),
        "headToHead": analytics.head_to_head(history),
        "luck": analytics.luck(history),
        "lineups": lineup_analytics.efficiency(history, lineup_rows),
        "draft": draft_analytics.draft_roi(history, pick_rows),
        "trades": draft_analytics.trade_activity(history),
    }


def build_rosters():
    """Everything the dedicated Rosters page needs: one JSON, keyed by season.

    Kept separate from analysis.json rather than folded in -- it is looked up
    completely differently (by manager, not by stat) and this keeps the main
    analysis feed from carrying every bench player's name on every page load.

    Which seasons appear is decided inside rosters_by_season, gated on ESPN's
    own draftDetail.drafted flag rather than a year cutoff computed here --
    see its docstring for why that matters for 2026 specifically.
    """
    import rosters as roster_analytics
    from model import load_league_history

    history = load_league_history()
    by_year = roster_analytics.rosters_by_season(history)

    return {
        "generated": datetime.date.today().isoformat(),
        "leagueName": espn_league_name(load_league()["current_season"]),
        "seasons": sorted(by_year, reverse=True),
        "rosters": {str(year): managers for year, managers in by_year.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--splash-only",
        action="store_true",
        help="skip the analysis feed (no archive needed)",
    )
    args = parser.parse_args()

    print("building site data")
    changed = write_json("draft.json", build_draft())
    if not args.splash_only:
        changed = write_json("analysis.json", build_analysis()) or changed
        changed = write_json("rosters.json", build_rosters()) or changed
    print("done%s" % ("" if changed else " (nothing changed)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
