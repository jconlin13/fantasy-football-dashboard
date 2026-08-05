"""Find out what ESPN will actually give us before building anything on top of it.

Walks backwards from the current season asking for each view, and prints a
grid of what came back. Data availability degrades unpredictably as you go
back -- older seasons routinely drop draft detail, transactions and boxscores
-- so this is the ground truth the rest of the pipeline is written against.

    python3 pipeline/probe.py --league-id 123456 --from 2012
"""

import argparse
import json

from espn_client import EspnError, VIEWS, fetch_view, load_cookies


def summarize(view, payload):
    """One line describing whether a view actually carries usable data."""
    if view == "mSettings":
        settings = payload.get("settings") or {}
        schedule = settings.get("scheduleSettings") or {}
        return "name=%r teams=%s reg_weeks=%s playoff_teams=%s" % (
            settings.get("name"),
            len(payload.get("teams") or []) or payload.get("size"),
            schedule.get("matchupPeriodCount"),
            schedule.get("playoffTeamCount"),
        )
    if view == "mTeam":
        teams = payload.get("teams") or []
        named = sum(1 for t in teams if t.get("owners"))
        return "%d teams, %d with owner ids" % (len(teams), named)
    if view == "mDraftDetail":
        draft = payload.get("draftDetail") or {}
        picks = draft.get("picks") or []
        return "%d picks, completed=%s" % (len(picks), draft.get("drafted"))
    if view == "mTransactions2":
        tx = payload.get("transactions") or []
        return "%d transactions" % len(tx)
    if view in ("mMatchup", "mMatchupScore", "mBoxscore"):
        schedule = payload.get("schedule") or []
        scored = sum(
            1
            for m in schedule
            if (m.get("home") or {}).get("totalPoints")
        )
        lineups = sum(
            1
            for m in schedule
            if ((m.get("home") or {}).get("rosterForCurrentScoringPeriod"))
        )
        return "%d matchups, %d scored, %d with lineups" % (
            len(schedule),
            scored,
            lineups,
        )
    if view == "mRoster":
        teams = payload.get("teams") or []
        with_roster = sum(1 for t in teams if (t.get("roster") or {}).get("entries"))
        return "%d/%d teams have rosters" % (with_roster, len(teams))
    return "ok (%d top-level keys)" % len(payload)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league-id", required=True)
    parser.add_argument(
        "--from",
        dest="start_year",
        type=int,
        required=True,
        help="earliest season to probe",
    )
    parser.add_argument("--to", dest="end_year", type=int, default=2025)
    parser.add_argument("--out", default=None, help="write results as JSON here")
    args = parser.parse_args()

    cookies = load_cookies()
    print(
        "auth: %s\n"
        % ("SWID + espn_s2 present" if cookies else "none (public league only)")
    )

    results = {}
    for year in range(args.end_year, args.start_year - 1, -1):
        print("=== %d ===" % year)
        year_result = {}
        for view in VIEWS:
            try:
                payload, url = fetch_view(args.league_id, year, view, cookies)
            except EspnError as exc:
                print("  %-16s FAIL  %s" % (view, exc))
                year_result[view] = {"ok": False, "error": str(exc)}
                continue
            note = summarize(view, payload)
            shape = "history" if "leagueHistory" in url else "seasons"
            print("  %-16s ok    [%s] %s" % (view, shape, note))
            year_result[view] = {"ok": True, "shape": shape, "note": note, "url": url}
        results[year] = year_result
        print("")

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(results, fh, indent=2)
        print("wrote %s" % args.out)


if __name__ == "__main__":
    main()
