"""Who had who -- the roster each manager closed a season with.

Built for one reason: this is a keeper league, and the group chat asks "wait
who even had him" every August. The archive already has the answer in
mRoster's end-of-season snapshot; this just resolves it to manager names and
labels how each player got there.

Position ids are read from the data, not hardcoded from memory -- {1,2,3,4,5,16}
appear in every season 2018-2025, and 7 (punter) only from 2025 on, matching the
year this league's roster added a punter slot. An id outside the known map is
reported rather than silently mislabeled.

`points` is the player's whole real-world season total -- the same number
on any ESPN player card -- not "points scored while this manager owned
them." A player added midseason still shows their full-season number. That is
a deliberate, simpler definition; a fantasy-team-scoped total is a different
stat (see draft.py's `returned`, which is exactly that) and mixing the two on
one page would need two different labels to stay honest.

Deliberately NOT attempted: keeper cost. ESPN's `keeper` flag on a draft pick
says whether a player WAS kept into that draft, not what a team would owe to
keep them again -- that is a league-specific rule (round penalty, salary,
etc.) this code has no way to know, so guessing at one would be exactly the
kind of confident wrong answer worth avoiding. What is shown instead is
provenance: whether this season's roster spot was Drafted, Kept (drafted with
ESPN's own keeper flag set), or Added (waiver, free agency, or a trade).
"""

import collections

from model import read

POSITION_NAMES = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 7: "P", 16: "D/ST"}
POSITION_ORDER = ["QB", "RB", "WR", "TE", "K", "P", "D/ST"]


def _position_name(position_id, unmapped):
    name = POSITION_NAMES.get(position_id)
    if name is None:
        unmapped.add(position_id)
        name = "POS%s" % position_id
    return name


def _season_total(player, year):
    """A player's actual points for exactly this season -- not any other one.

    Found the hard way: `stats` holds one entry per season a player has any
    history for, and more than one of them can carry statSourceId=0,
    statSplitTypeId=0, scoringPeriodId=0 (ESPN's "actual season total" marker)
    -- one per season, each tagged with its own seasonId. Matching on those
    three fields alone and taking the first hit returned Jalen Hurts' 2025
    total for his 2026 roster slot, before a single 2026 snap had been played.
    seasonId has to be part of the match, not just those three.
    """
    for stat in player.get("stats") or []:
        if (
            stat.get("seasonId") == year
            and stat.get("statSourceId") == 0
            and stat.get("statSplitTypeId") == 0
            and stat.get("scoringPeriodId") == 0
        ):
            return stat.get("appliedTotal") or 0.0
    return 0.0


def _draft_lookup(year):
    """{(team id, player id): (round, overall, was a flagged keeper)}"""
    detail = read(year, "mDraftDetail")
    picks = (detail or {}).get("draftDetail", {}).get("picks") or []
    lookup = {}
    for pick in picks:
        key = (pick.get("teamId"), pick.get("playerId"))
        lookup[key] = (pick.get("roundId"), pick.get("overallPickNumber"), bool(pick.get("keeper")))
    return lookup


def rosters_by_season(history):
    """{year: {manager display name: [players]}} for every archived season."""
    unmapped = set()
    result = {}

    for year in sorted(history.seasons):
        payload = read(year, "mRoster")
        if not payload:
            continue
        season = history.seasons[year]
        draft = _draft_lookup(year)

        by_manager = collections.defaultdict(list)
        for team in payload.get("teams") or []:
            team_id = team.get("id")
            manager = season.manager_of.get(team_id)
            if manager is None:
                continue
            manager_name = history.managers.get(manager, manager)

            for entry in (team.get("roster") or {}).get("entries") or []:
                pool = entry.get("playerPoolEntry") or {}
                player = pool.get("player") or {}
                player_id = entry.get("playerId")

                pick = draft.get((team_id, player_id))
                if pick is None:
                    status = "Added"
                    round_, overall = None, None
                else:
                    round_, overall, kept = pick
                    status = "Kept" if kept else "Drafted"

                by_manager[manager_name].append(
                    {
                        "name": player.get("fullName") or "?",
                        "position": _position_name(player.get("defaultPositionId"), unmapped),
                        "points": round(_season_total(player, year), 1),
                        "status": status,
                        "round": round_,
                    }
                )

        for manager_name, players in by_manager.items():
            players.sort(
                key=lambda p: (
                    POSITION_ORDER.index(p["position"])
                    if p["position"] in POSITION_ORDER
                    else len(POSITION_ORDER),
                    -p["points"],
                )
            )

        if by_manager:
            result[year] = dict(by_manager)

    if unmapped:
        print("  warning: unmapped roster position ids seen: %s" % sorted(unmapped))

    return result
