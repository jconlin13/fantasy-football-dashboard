"""Records, head-to-head and luck -- everything computed from the `games` table.

These three live together because they are the same data grouped three ways:
by extreme (records), by pairing (head-to-head), and by week (luck). Phase 5's
lineup and draft analytics read different tables and live elsewhere.

Every number here has to be explainable in one sentence, because the whole
point of this site is settling arguments. A stat nobody can explain just starts
a new argument about the stat.

Only counting games are used -- no byes, and no consolation games, per the
league's rule that only the regular season and games still played for the title
are real. See model.COUNTING_BRACKETS.
"""

import collections

from model import CHAMPIONSHIP, REGULAR


def _counting(history, brackets=None):
    for game in history.games:
        if not game["counts"]:
            continue
        if brackets and game["bracket"] not in brackets:
            continue
        yield game


def _name(history, manager):
    return history.managers.get(manager, manager)


def records_book(history):
    """The extremes. Regular season and playoffs reported separately.

    'Best season' is regular-season win percentage, tie-broken by points, so a
    12-2 team beats an 11-3 team that scored more.
    """
    book = {}

    for label, brackets in (("regular", (REGULAR,)), ("playoff", (CHAMPIONSHIP,))):
        games = list(_counting(history, brackets))
        if not games:
            continue

        def entry(game, value):
            return {
                "manager": _name(history, game["manager"]),
                "opponent": _name(history, game["opponent"]),
                "year": game["year"],
                "week": game["week"],
                "value": round(value, 2),
                "score": "%.1f - %.1f" % (game["points_for"], game["points_against"]),
            }

        wins = [g for g in games if g["won"]]
        losses = [g for g in games if not g["won"]]

        highest = max(games, key=lambda g: g["points_for"])
        lowest = min(games, key=lambda g: g["points_for"])
        blowout = max(games, key=lambda g: g["points_for"] - g["points_against"])
        narrow = min(wins, key=lambda g: g["points_for"] - g["points_against"])
        unlucky = max(losses, key=lambda g: g["points_for"]) if losses else None

        book[label] = {
            "highestWeek": entry(highest, highest["points_for"]),
            "lowestWeek": entry(lowest, lowest["points_for"]),
            "biggestBlowout": entry(
                blowout, blowout["points_for"] - blowout["points_against"]
            ),
            "narrowestWin": entry(
                narrow, narrow["points_for"] - narrow["points_against"]
            ),
            "mostPointsInALoss": entry(unlucky, unlucky["points_for"])
            if unlucky
            else None,
        }

    # Season records, regular season only -- playoff games would let a team with
    # a bye look like it played fewer games than it did.
    seasons = collections.defaultdict(lambda: [0, 0, 0.0])
    for game in _counting(history, (REGULAR,)):
        row = seasons[(game["year"], game["manager"])]
        row[0] += 1 if game["won"] else 0
        row[1] += 1
        row[2] += game["points_for"]

    ranked = sorted(
        (
            {
                "manager": _name(history, manager),
                "year": year,
                "wins": wins,
                "games": played,
                "points": round(points, 1),
                "winPct": round(wins / float(played), 3) if played else 0.0,
            }
            for (year, manager), (wins, played, points) in seasons.items()
        ),
        key=lambda row: (row["winPct"], row["points"]),
        reverse=True,
    )
    book["bestSeason"] = ranked[0] if ranked else None
    book["worstSeason"] = ranked[-1] if ranked else None

    book["streaks"] = longest_streaks(history)
    return book


def longest_streaks(history):
    """Longest career win and loss streaks, carried across seasons.

    A streak is not reset by the offseason on purpose -- losing the last four of
    one year and the first four of the next is an eight-game losing streak, and
    the league will remember it that way.
    """
    by_manager = collections.defaultdict(list)
    for game in _counting(history):
        by_manager[game["manager"]].append(game)

    best_win = {"manager": None, "length": 0}
    best_loss = {"manager": None, "length": 0}

    for manager, games in by_manager.items():
        games.sort(key=lambda g: (g["year"], g["week"]))
        run_win = run_loss = 0
        for game in games:
            if game["won"]:
                run_win += 1
                run_loss = 0
            else:
                run_loss += 1
                run_win = 0
            if run_win > best_win["length"]:
                best_win = {
                    "manager": _name(history, manager),
                    "length": run_win,
                    "through": "%d wk%d" % (game["year"], game["week"]),
                }
            if run_loss > best_loss["length"]:
                best_loss = {
                    "manager": _name(history, manager),
                    "length": run_loss,
                    "through": "%d wk%d" % (game["year"], game["week"]),
                }

    return {"longestWinStreak": best_win, "longestLoseStreak": best_loss}


def head_to_head(history):
    """Career record for every pair of managers who have ever played.

    Playoff meetings are tracked separately -- 'I beat you in the semifinal'
    carries more weight than a week 4 win and should not be averaged into it.
    """
    pairs = collections.defaultdict(
        lambda: {
            "wins": 0,
            "losses": 0,
            "pointsFor": 0.0,
            "pointsAgainst": 0.0,
            "meetings": 0,
            "playoffWins": 0,
            "playoffLosses": 0,
        }
    )

    for game in _counting(history):
        if not game["opponent"]:
            continue
        row = pairs[(game["manager"], game["opponent"])]
        row["meetings"] += 1
        row["pointsFor"] += game["points_for"]
        row["pointsAgainst"] += game["points_against"]
        if game["won"]:
            row["wins"] += 1
        else:
            row["losses"] += 1
        if game["bracket"] == CHAMPIONSHIP:
            if game["won"]:
                row["playoffWins"] += 1
            else:
                row["playoffLosses"] += 1

    matrix = []
    for (manager, opponent), row in pairs.items():
        meetings = row["meetings"]
        matrix.append(
            {
                "manager": _name(history, manager),
                "opponent": _name(history, opponent),
                "wins": row["wins"],
                "losses": row["losses"],
                "meetings": meetings,
                "avgMargin": round(
                    (row["pointsFor"] - row["pointsAgainst"]) / meetings, 2
                ),
                "playoffWins": row["playoffWins"],
                "playoffLosses": row["playoffLosses"],
            }
        )
    return sorted(matrix, key=lambda row: (row["manager"], row["opponent"]))


def luck(history):
    """Expected wins from an all-play record, and how far actual wins strayed.

    For each week, a team's all-play record is its score against every other
    team that played that week. Winning 7 of those 9 comparisons is 0.778 of a
    win earned. Expected wins is those fractions added up across a career.

    Luck = actual wins - expected wins. In one sentence: you would have won this
    many games against an average schedule, and you actually won that many.

    Regular season only. Playoff matchups are set by seeding rather than by the
    schedule, so there is no schedule luck in them to measure.
    """
    weekly = collections.defaultdict(list)
    for game in _counting(history, (REGULAR,)):
        weekly[(game["year"], game["week"])].append(game)

    expected = collections.defaultdict(float)
    actual = collections.defaultdict(int)
    played = collections.defaultdict(int)
    season_expected = collections.defaultdict(float)
    season_actual = collections.defaultdict(int)

    for (year, _week), games in weekly.items():
        if len(games) < 2:
            continue
        scores = [g["points_for"] for g in games]
        for game in games:
            mine = game["points_for"]
            beat = sum(1 for other in scores if mine > other)
            tied = sum(1 for other in scores if mine == other) - 1  # exclude self
            share = (beat + 0.5 * tied) / float(len(scores) - 1)

            manager = game["manager"]
            expected[manager] += share
            actual[manager] += 1 if game["won"] else 0
            played[manager] += 1
            season_expected[(year, manager)] += share
            season_actual[(year, manager)] += 1 if game["won"] else 0

    career = []
    for manager in expected:
        career.append(
            {
                "manager": _name(history, manager),
                "games": played[manager],
                "actualWins": actual[manager],
                "expectedWins": round(expected[manager], 2),
                "luck": round(actual[manager] - expected[manager], 2),
            }
        )

    seasons = []
    for (year, manager), exp in season_expected.items():
        seasons.append(
            {
                "year": year,
                "manager": _name(history, manager),
                "actualWins": season_actual[(year, manager)],
                "expectedWins": round(exp, 2),
                "luck": round(season_actual[(year, manager)] - exp, 2),
            }
        )

    return {
        "career": sorted(career, key=lambda row: row["luck"], reverse=True),
        "seasons": sorted(seasons, key=lambda row: (row["year"], row["manager"])),
    }
