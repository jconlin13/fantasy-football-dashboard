"""What draft picks actually returned, and the league's non-existent trade market.

DRAFT RETURN is defined as: the points a drafted player scored for the team that
drafted them, for as long as they stayed on that roster. In one sentence -- what
that pick actually gave you.

That definition was chosen over "the player's season total" deliberately. Season
totals are only recoverable for about 75% of drafted players (ESPN keeps them on
end-of-season rosters, so anyone dropped and left unowned has none), and filling
the gap with a second, different measure would silently mix two definitions in
one column. Points-while-rostered is available for essentially every pick, and
it is honest about what it includes: drop a bust in week 3 and you keep the two
weeks you got. Trade a star away and the return stops there too, which is a real
limitation and is stated rather than hidden.

Each pick is compared against the average return for that same draft slot across
every season, so a good number means beating what the slot usually gives rather
than simply picking early.

WHAT THIS IS NOT: a measure of who drafts well. It was checked, and it does not
survive the check. Ranking managers by return is very nearly the same as ranking
them by how long they keep their picks -- the manager who holds picks longest
(14.6 weeks on average) is near the top and the one who holds them shortest
(10.9) is dead last. Someone who aggressively churns their roster for waiver
pickups scores badly here even when their picks were fine, because their return
stops the moment they drop the player.

So this is reported as `avgWeeksHeld` alongside the return, and labelled as what
it is: what your own draft picks gave you, which blends pick quality with how
long you kept them. Isolating draft skill would mean using each player's full
season total regardless of who rostered them, and ESPN only retains those for
about 75% of drafted players -- everyone dropped and left unowned has none,
which is disproportionately the busts. That trade-off is the commissioner's call
rather than something to paper over with a mixed definition.
"""

import collections
import os

from model import RAW, read

# ESPN uses team id 0 for "nobody" -- free agency, or the other side of a drop.
NO_TEAM = 0


def _weekly_rosters(year):
    """{(week, player id): team id} -- who held each player each week."""
    held = {}
    week_dir = os.path.join(RAW, str(year), "weeks")
    if not os.path.isdir(week_dir):
        return held

    for week_name in sorted(os.listdir(week_dir)):
        if not week_name.isdigit():
            continue
        week = int(week_name)
        payload = read(year, "mBoxscore", week=week)
        if not payload:
            continue
        for matchup in payload.get("schedule") or []:
            for side in ("home", "away"):
                team = matchup.get(side) or {}
                roster = team.get("rosterForCurrentScoringPeriod")
                team_id = team.get("teamId")
                if not roster or team_id is None:
                    continue
                for entry in roster.get("entries") or []:
                    points = (entry.get("playerPoolEntry") or {}).get(
                        "appliedStatTotal"
                    ) or 0.0
                    held[(week, entry.get("playerId"))] = (team_id, points)
    return held


def draft_returns(history):
    """One row per pick, with what it returned to the team that made it."""
    rows = []

    for year in sorted(history.seasons):
        season = history.seasons[year]
        detail = read(year, "mDraftDetail")
        if not detail:
            continue
        picks = (detail.get("draftDetail") or {}).get("picks") or []
        if not picks or not (detail.get("draftDetail") or {}).get("drafted"):
            continue      # draft not held yet

        held = _weekly_rosters(year)
        by_player = collections.defaultdict(list)
        for (week, player_id), (team_id, points) in held.items():
            by_player[player_id].append((week, team_id, points))

        for pick in picks:
            player_id = pick.get("playerId")
            team_id = pick.get("teamId")
            manager = season.manager_of.get(team_id)
            if manager is None:
                continue

            returned = sum(
                points
                for _week, holder, points in by_player.get(player_id, [])
                if holder == team_id
            )
            weeks_held = sum(
                1
                for _week, holder, _points in by_player.get(player_id, [])
                if holder == team_id
            )

            rows.append(
                {
                    "year": year,
                    "manager": manager,
                    "overall": pick.get("overallPickNumber"),
                    "round": pick.get("roundId"),
                    "playerId": player_id,
                    "keeper": bool(pick.get("keeper")),
                    "returned": round(returned, 2),
                    "weeksHeld": weeks_held,
                }
            )
    return rows


def draft_roi(history, rows=None):
    """Return by pick, measured against what that draft slot usually gives.

    A slot's baseline is the average return of that overall pick number across
    every season, so beating it means drafting well rather than drafting early.
    """
    rows = rows if rows is not None else draft_returns(history)
    if not rows:
        return {"bySlot": [], "byManager": [], "bestPicks": [], "worstPicks": []}

    slot_returns = collections.defaultdict(list)
    for row in rows:
        slot_returns[row["overall"]].append(row["returned"])
    baseline = {
        slot: sum(values) / float(len(values)) for slot, values in slot_returns.items()
    }

    for row in rows:
        row["baseline"] = round(baseline[row["overall"]], 2)
        row["vsSlot"] = round(row["returned"] - baseline[row["overall"]], 2)

    def name(manager):
        return history.managers.get(manager, manager)

    by_manager = collections.defaultdict(lambda: [0.0, 0, 0])
    for row in rows:
        entry = by_manager[row["manager"]]
        entry[0] += row["vsSlot"]
        entry[1] += 1
        entry[2] += row["weeksHeld"]

    # avgWeeksHeld ships next to the return on purpose. The two track each other
    # closely, and a reader who cannot see that will read this as draft skill.
    manager_rows = sorted(
        (
            {
                "manager": name(manager),
                "picks": count,
                "totalVsSlot": round(total, 1),
                "avgVsSlot": round(total / count, 2) if count else 0.0,
                "avgWeeksHeld": round(weeks / float(count), 2) if count else 0.0,
            }
            for manager, (total, count, weeks) in by_manager.items()
        ),
        key=lambda row: row["avgVsSlot"],
        reverse=True,
    )

    ranked = sorted(rows, key=lambda row: row["vsSlot"], reverse=True)
    def describe(row):
        return {
            "manager": name(row["manager"]),
            "year": row["year"],
            "overall": row["overall"],
            "round": row["round"],
            "returned": row["returned"],
            "baseline": row["baseline"],
            "vsSlot": row["vsSlot"],
        }

    slot_rows = sorted(
        (
            {"overall": slot, "avgReturn": round(value, 2), "picks": len(slot_returns[slot])}
            for slot, value in baseline.items()
        ),
        key=lambda row: row["overall"],
    )

    return {
        "bySlot": slot_rows,
        "byManager": manager_rows,
        "bestPicks": [describe(row) for row in ranked[:10]],
        "worstPicks": [describe(row) for row in ranked[-10:]][::-1],
    }


def trade_activity(history):
    """The league's trade market, such as it is.

    There is no trade-retrospective feature here, and that is a finding rather
    than an omission: across eight seasons ESPN records 55 trade proposals, 9
    acceptances, 8 vetoes -- and carries the actual players involved for only
    two of them. Everything else has an empty item list. There is nothing to
    reconstruct.

    What is left is a genuinely good league stat: this league loves proposing
    trades and almost never completes one.
    """
    counts = collections.Counter()
    per_season = collections.defaultdict(collections.Counter)

    for year in sorted(history.seasons):
        week_dir = os.path.join(RAW, str(year), "weeks")
        if not os.path.isdir(week_dir):
            continue
        for week_name in sorted(os.listdir(week_dir)):
            if not week_name.isdigit():
                continue
            payload = read(year, "mTransactions2", week=int(week_name))
            if not payload:
                continue
            for transaction in payload.get("transactions") or []:
                kind = transaction.get("type") or ""
                if not kind.startswith("TRADE"):
                    continue
                counts[kind] += 1
                per_season[year][kind] += 1

    return {
        "totals": dict(counts),
        "bySeason": {year: dict(kinds) for year, kinds in per_season.items()},
    }
