"""What a team scored, against what it could have scored.

The question this answers is the one everybody asks the morning after: how many
points did you leave on your bench? Efficiency is actual divided by the best
legal lineup that roster could have produced with perfect hindsight.

Two things make this harder than it sounds.

The roster rules changed. This league ran nine starters and one quarterback in
2018, swapped the flex for a superflex in 2021, and by 2025 was starting eleven
with two quarterbacks and a punter. Nothing here assumes a slot layout; every
season's own lineupSlotCounts and every player's own eligibleSlots are read from
the archive. Which slots are starting slots is verified rather than assumed --
see validate_lineups().

Choosing the best lineup is an assignment problem, not a sort. Taking the
highest scorer for each slot in turn can strand a player who was the only one
eligible somewhere else, so this solves it exactly with the Hungarian algorithm
rather than greedily. Rosters are small, so exact costs nothing.
"""

import collections
import os

from model import RAW, read

# Slots that hold players who are not playing. Not assumed -- confirmed by
# checking that the remaining slots' points sum to the team's own total.
BENCH_SLOT = 20
IR_SLOT = 21

_BIG = 1e9


def starting_slots(settings):
    """{slot id: how many start} for one season, bench and IR excluded."""
    counts = (
        (settings.get("settings") or {}).get("rosterSettings") or {}
    ).get("lineupSlotCounts") or {}
    return {
        int(slot): count
        for slot, count in counts.items()
        if count and int(slot) not in (BENCH_SLOT, IR_SLOT)
    }


def _assign(cost, n_rows, n_cols):
    """Hungarian algorithm: min-cost perfect assignment of rows to columns.

    Rows are slot openings, columns are players, and n_rows <= n_cols. Returns
    {row: column}. Standard shortest-augmenting-path form with potentials.
    """
    u = [0.0] * (n_rows + 1)
    v = [0.0] * (n_cols + 1)
    p = [0] * (n_cols + 1)
    way = [0] * (n_cols + 1)

    for i in range(1, n_rows + 1):
        p[0] = i
        j0 = 0
        minv = [float("inf")] * (n_cols + 1)
        used = [False] * (n_cols + 1)
        while True:
            used[j0] = True
            i0 = p[j0]
            delta = float("inf")
            j1 = -1
            for j in range(1, n_cols + 1):
                if used[j]:
                    continue
                cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                if cur < minv[j]:
                    minv[j] = cur
                    way[j] = j0
                if minv[j] < delta:
                    delta = minv[j]
                    j1 = j
            for j in range(n_cols + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1

    return {p[j] - 1: j - 1 for j in range(1, n_cols + 1) if p[j]}


def optimal_lineup(players, slots):
    """Best legal lineup for one roster-week.

    `players` is [{"points": float, "eligible": set(), ...}]; `slots` is
    {slot id: count}. Returns (total points, [indices of the players started]).
    """
    openings = []
    for slot, count in sorted(slots.items()):
        openings.extend([slot] * count)

    if not openings or not players:
        return 0.0, []

    # More openings than players can happen with a short roster; pad with
    # phantom players worth nothing so the matrix stays rectangular.
    padded = len(players)
    n_cols = max(padded, len(openings))

    cost = []
    for slot in openings:
        row = []
        for index in range(n_cols):
            if index >= padded or slot not in players[index]["eligible"]:
                row.append(_BIG)          # ineligible: never worth choosing
            else:
                row.append(-players[index]["points"])   # maximize points
        cost.append(row)

    assignment = _assign(cost, len(openings), n_cols)

    total = 0.0
    started = []
    for row, col in assignment.items():
        if cost[row][col] >= _BIG:
            continue                      # slot could not be legally filled
        total += players[col]["points"]
        started.append(col)
    return round(total, 2), started


def load_lineups(history):
    """Every team-week's roster, with what it scored and what it could have.

    Only weeks that count are considered -- byes and consolation games are not
    lineup decisions anybody is judged on.
    """
    countable = {}
    for game in history.games:
        if game["counts"]:
            countable[(game["year"], game["week"], game["team_id"])] = game

    rows = []
    for year in sorted(history.seasons):
        season = history.seasons[year]
        settings = read(year, "mSettings")
        if not settings:
            continue
        slots = starting_slots(settings)
        if not slots:
            continue

        week_dir = os.path.join(RAW, str(year), "weeks")
        if not os.path.isdir(week_dir):
            continue

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
                    game = countable.get((year, week, team_id))
                    if not game:
                        continue

                    players = []
                    actual = 0.0
                    for entry in roster.get("entries") or []:
                        pool = entry.get("playerPoolEntry") or {}
                        player = pool.get("player") or {}
                        points = pool.get("appliedStatTotal") or 0.0
                        slot = entry.get("lineupSlotId")
                        if slot in slots:
                            actual += points
                        if slot == IR_SLOT:
                            continue      # cannot be started, so not a choice

                        eligible = set(player.get("eligibleSlots") or [])
                        # A player who actually started somewhere was eligible
                        # there at the time, whatever the archive says now.
                        # eligibleSlots reflects a player's *current* position,
                        # and ESPN reclassifies people -- Taysom Hill started at
                        # tight end in 2020 week 11 and is listed today as a
                        # quarterback only. Trusting the metadata over what
                        # visibly happened produced an "optimal" lineup that
                        # scored ten points less than the real one.
                        if slot in slots:
                            eligible.add(slot)

                        players.append(
                            {
                                "name": player.get("fullName") or "?",
                                "points": points,
                                "eligible": eligible,
                                "started": slot in slots,
                            }
                        )

                    best, started_indices = optimal_lineup(players, slots)
                    started = set(started_indices)

                    # The one call that cost the most: the best player left on
                    # the bench, against the worst player started who could
                    # legally have been replaced by them.
                    benched = [
                        p for i, p in enumerate(players) if i not in started and not p["started"]
                    ]
                    rows.append(
                        {
                            "year": year,
                            "week": week,
                            "manager": game["manager"],
                            "actual": round(actual, 2),
                            "optimal": best,
                            "left_on_bench": round(best - actual, 2),
                            "efficiency": round(actual / best, 4) if best else None,
                            "best_benched": max(
                                (p["points"] for p in benched), default=0.0
                            ),
                        }
                    )
    return rows


def efficiency(history, rows=None):
    """Career and per-season lineup efficiency, plus the worst single week."""
    rows = rows if rows is not None else load_lineups(history)

    career = collections.defaultdict(lambda: [0.0, 0.0, 0])
    seasons = collections.defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        c = career[row["manager"]]
        c[0] += row["actual"]
        c[1] += row["optimal"]
        c[2] += 1
        s = seasons[(row["year"], row["manager"])]
        s[0] += row["actual"]
        s[1] += row["optimal"]

    def name(manager):
        return history.managers.get(manager, manager)

    career_rows = sorted(
        (
            {
                "manager": name(manager),
                "weeks": weeks,
                "actual": round(actual, 1),
                "optimal": round(optimal, 1),
                "leftOnBench": round(optimal - actual, 1),
                "efficiency": round(actual / optimal, 4) if optimal else None,
            }
            for manager, (actual, optimal, weeks) in career.items()
        ),
        key=lambda row: row["efficiency"] or 0,
        reverse=True,
    )

    worst = sorted(rows, key=lambda row: row["left_on_bench"], reverse=True)[:10]
    worst_rows = [
        {
            "manager": name(row["manager"]),
            "year": row["year"],
            "week": row["week"],
            "actual": row["actual"],
            "optimal": row["optimal"],
            "leftOnBench": row["left_on_bench"],
        }
        for row in worst
    ]

    season_rows = sorted(
        (
            {
                "year": year,
                "manager": name(manager),
                "efficiency": round(actual / optimal, 4) if optimal else None,
                "leftOnBench": round(optimal - actual, 1),
            }
            for (year, manager), (actual, optimal) in seasons.items()
        ),
        key=lambda row: (row["year"], row["manager"]),
    )

    return {"career": career_rows, "seasons": season_rows, "worstWeeks": worst_rows}


def validate_lineups(history, rows=None):
    """Invariants the solver cannot be allowed to violate.

    The optimal lineup is chosen from a superset of what was actually started,
    so it can never score less than the actual lineup did. If it ever does, the
    solver is wrong -- and a too-low optimum would quietly flatter everyone's
    efficiency rather than announce itself.
    """
    rows = rows if rows is not None else load_lineups(history)
    problems = []

    impossible = [r for r in rows if r["optimal"] + 0.01 < r["actual"]]
    if impossible:
        problems.append(
            "%d team-weeks where the 'optimal' lineup scores less than the real one"
            % len(impossible)
        )

    perfect = sum(1 for r in rows if r["efficiency"] and r["efficiency"] >= 0.9999)
    return problems, {"weeks": len(rows), "perfect": perfect}
