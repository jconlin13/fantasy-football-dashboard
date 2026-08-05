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
    year = load_league()["current_season"]
    from_espn = espn_draft_datetime(year)
    override = get(draft, "datetime")
    when = override or from_espn or ""

    if override and from_espn and override != from_espn:
        print("  note: config datetime overrides ESPN's %s" % from_espn)
    elif from_espn:
        print("  draft time from ESPN: %s" % from_espn)
    elif not override:
        print("  draft not scheduled in ESPN yet -- page will say Not set")

    return {
        "label": get(draft, "label") or "Draft Day",
        "kind": get(draft, "kind"),
        "datetime": when,
        "datetimeSource": "config" if override else ("espn" if from_espn else None),
        "location": get(draft, "location"),
        "espnUrl": get(draft, "espn_url"),
        "passphraseSha256": get(draft, "passphrase_sha256").lower(),
        "dues": {"amount": get(dues, "amount"), "venmoUrl": get(dues, "venmo_url")},
        "order": parse_order(parser),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()

    print("building site data")
    changed = write_json("draft.json", build_draft())
    print("done%s" % ("" if changed else " (nothing changed)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
