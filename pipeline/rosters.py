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

How a player got onto the roster:

    Drafted      picked in this team's own draft. Shown with round.pick-in-round
                 (e.g. "1.4" is round 1, pick 4 of that round) -- never the
                 overall pick number, which mixes rounds together and is a
                 worse answer to "where did I get him."
    Free Agent   not in this team's draft picks -- added off waivers, free
                 agency, or by trade. The archive cannot tell those three
                 apart (see draft.py's trade-market findings: real trade
                 participants are recoverable for 2 of 8 seasons' trades), so
                 they are not claimed to be told apart here either.
    Added        drafted AND flagged by ESPN's own `keeper` bit. Worth calling
                 out only because this league's `keeperCount` setting is 0 and
                 that bit has never once been true across 2018-2026 -- so in
                 practice this status never appears. Kept in the code rather
                 than deleted, in case a future season actually uses it.

Deliberately NOT attempted: keeper cost. ESPN's `keeper` flag says a player
WAS kept, not what a team would owe to keep them again -- that is a
league-specific house rule this code has no way to know, so guessing at one
would be exactly the kind of confident wrong answer worth avoiding.

The season picker never offers the current season. Before a draft happens,
ESPN just carries last year's rosters forward untouched -- it is not a
keeper list, it is stale data with nothing decided yet -- so anything from
`current_season` on is left out. Pass `through_year` explicitly (build_site_data
does, capped at current_season - 1) rather than trusting each Season's own
notion of "complete," so the cutoff is one obvious, statable rule instead of
inferred from a handful of status flags.
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
    """{(team id, player id): (round, pick-within-round, was keeper-flagged)}"""
    detail = read(year, "mDraftDetail")
    picks = (detail or {}).get("draftDetail", {}).get("picks") or []
    lookup = {}
    for pick in picks:
        key = (pick.get("teamId"), pick.get("playerId"))
        lookup[key] = (
            pick.get("roundId"),
            pick.get("roundPickNumber"),
            bool(pick.get("keeper")),
        )
    return lookup


def rosters_by_season(history, through_year=None):
    """{year: {manager display name: [players]}}.

    `through_year` excludes any season after it -- see the module docstring
    for why the current season is never a real answer here.
    """
    unmapped = set()
    result = {}

    for year in sorted(history.seasons):
        if through_year is not None and year > through_year:
            continue

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
                    status = "Free Agent"
                    round_, round_pick = None, None
                else:
                    round_, round_pick, kept = pick
                    # kept never fires in this league's archive (see module
                    # docstring) but the label is worth having ready either way.
                    status = "Added" if kept else "Drafted"

                by_manager[manager_name].append(
                    {
                        "name": player.get("fullName") or "?",
                        "position": _position_name(player.get("defaultPositionId"), unmapped),
                        "points": round(_season_total(player, year), 1),
                        "status": status,
                        "round": round_,
                        "roundPick": round_pick,
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
