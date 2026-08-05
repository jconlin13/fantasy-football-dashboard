"""Check the model against ESPN's own bookkeeping before trusting any metric.

ESPN stores each team's final record and final rank itself. Those are the
cheapest possible second source: if the games table is right, recomputing a
season's records from it has to reproduce what ESPN already wrote down. Ninety
team-seasons get checked this way without anyone having to remember anything.

What ESPN's `record.overall` counts is not documented, so this does not assume
-- it computes both regular-season-only and regular-plus-playoff records and
reports which one matches.

    python3 pipeline/validate_model.py
"""

import collections
import sys

from model import CHAMPIONSHIP, REGULAR, load_league_history


def records_for(history, year, brackets):
    """W-L-T per manager for one season, counting only the given brackets."""
    table = collections.defaultdict(lambda: [0, 0, 0])
    for game in history.games:
        if game["year"] != year or game["is_bye"] or game["won"] is None:
            continue
        if game["bracket"] not in brackets:
            continue
        row = table[game["manager"]]
        if game["won"]:
            row[0] += 1
        elif game["points_for"] == game["points_against"]:
            row[2] += 1
        else:
            row[1] += 1
    return table


def check_analytics_invariants(history):
    """Two things that must be true no matter what the numbers say.

    Both are cheap, and both would catch a whole class of double-counting or
    dropped-game bugs that look perfectly reasonable in the output.
    """
    import analytics

    problems = []

    # Every game has exactly one winner and one loser, so total wins across the
    # league must be exactly half of all team-game rows.
    career = analytics.luck(history)["career"]
    total_games = sum(row["games"] for row in career)
    total_wins = sum(row["actualWins"] for row in career)
    if total_wins * 2 != total_games:
        problems.append(
            "wins (%d) should be exactly half of team-games (%d)"
            % (total_wins, total_games)
        )

    # Expected wins is a redistribution of the same wins, so luck is zero-sum
    # across the league. Any drift means a week was scored against the wrong
    # field of opponents.
    total_luck = sum(row["luck"] for row in career)
    if abs(total_luck) > 0.05:
        problems.append("luck should sum to zero across the league, got %+.2f" % total_luck)

    # The optimal lineup is chosen from a superset of what was started, so it
    # can never score less. A too-low optimum would quietly flatter everyone's
    # efficiency rather than announce itself.
    import lineups

    lineup_problems, lineup_stats = lineups.validate_lineups(history)
    problems.extend(lineup_problems)

    print("analytics invariants: %s" % ("ok" if not problems else "FAILED"))
    for problem in problems:
        print("  - %s" % problem)
    print("  total wins %d of %d team-games, luck sums to %+.2f"
          % (total_wins, total_games, total_luck))
    print("  %d team-week lineups solved, %d of them perfect"
          % (lineup_stats["weeks"], lineup_stats["perfect"]))
    return problems


def main():
    history = load_league_history()
    print("%d managers, %d game rows\n" % (len(history.managers), len(history.games)))

    mismatches = 0
    unchecked = 0

    for year in sorted(history.seasons):
        season = history.seasons[year]
        if not season.complete:
            print("=== %d === not played yet, skipping\n" % year)
            continue

        regular_only = records_for(history, year, (REGULAR,))
        with_playoffs = records_for(history, year, (REGULAR, CHAMPIONSHIP))

        # Which definition does ESPN's stored record agree with?
        agrees_regular = agrees_playoff = 0
        for team_id, manager in season.manager_of.items():
            espn = season.espn_record.get(team_id)
            if not espn or not any(espn):
                continue
            if tuple(regular_only.get(manager, [0, 0, 0])) == espn:
                agrees_regular += 1
            if tuple(with_playoffs.get(manager, [0, 0, 0])) == espn:
                agrees_playoff += 1

        basis = "regular season only" if agrees_regular >= agrees_playoff else "incl. playoffs"
        table = regular_only if agrees_regular >= agrees_playoff else with_playoffs
        matched = max(agrees_regular, agrees_playoff)

        champion = history.managers.get(season.champion, "UNKNOWN")
        print("=== %d ===  champion: %s" % (year, champion))
        print("    ESPN record basis: %s (%d/%d teams agree)"
              % (basis, matched, len(season.manager_of)))

        # Standings ordered by ESPN's own final rank, so the two can be read
        # side by side.
        ordered = sorted(
            season.manager_of.items(),
            key=lambda kv: season.espn_rank.get(kv[0]) or 99,
        )
        for team_id, manager in ordered:
            wins, losses, ties = table.get(manager, [0, 0, 0])
            espn = season.espn_record.get(team_id) or (0, 0, 0)
            rank = season.espn_rank.get(team_id)
            flag = ""
            if not any(espn):
                flag = "  (ESPN stored no record)"
                unchecked += 1
            elif (wins, losses, ties) != espn:
                flag = "  <-- MISMATCH, ESPN says %d-%d-%d" % espn
                mismatches += 1
            print("      %2s. %-12s %2d-%2d-%d%s"
                  % (rank if rank else "?", history.managers.get(manager, manager),
                     wins, losses, ties, flag))
        print("")

    print("-" * 60)
    invariant_problems = check_analytics_invariants(history)
    print("-" * 60)
    if mismatches:
        print("%d mismatches against ESPN's own records -- do not build on this yet"
              % mismatches)
    else:
        print("every checkable team-season matches ESPN's own stored record")
    if unchecked:
        print("%d team-seasons had no stored ESPN record to check against" % unchecked)
    print("\nThe champions above are the real test. Confirm them from memory.")
    return 1 if (mismatches or invariant_problems) else 0


if __name__ == "__main__":
    sys.exit(main())
