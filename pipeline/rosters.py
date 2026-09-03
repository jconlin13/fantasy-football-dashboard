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

A season is only shown once its draft has actually happened, checked directly
against mDraftDetail's own `drafted` flag rather than a hardcoded year cutoff.
Before that, ESPN just carries the prior year's rosters forward untouched --
not a keeper list, just stale data with nothing decided yet. This is also
self-updating on purpose: the day the 2026 draft finishes and the archive is
next refreshed, `drafted` flips to true and 2026 appears on this page with no
code change and no one having to remember to update a cutoff.

For the single newest drafted season, two more fields ride along per player
when they're available: next season's ESPN-projected points, and a projected
draft round derived from ESPN's average-draft-position (an industry-wide
number, not specific to this league's eventual draft, rounded up to whichever
round it would land in for a league this size). Both come from whichever of
the ten teams currently rosters that player next season -- there is no
archived view of the wider free-agent pool, so a player not on any of next
season's ten rosters (retired, cut everywhere) simply has neither field,
rather than a guessed one.
"""

import collections
import math

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


def _projected_total(player, year):
    """ESPN's own preseason projection for this exact season, or None.

    Same field family as _season_total but statSourceId=1 (projected rather
    than actual). Same seasonId trap applies, so it is guarded the same way.
    """
    for stat in player.get("stats") or []:
        if (
            stat.get("seasonId") == year
            and stat.get("statSourceId") == 1
            and stat.get("statSplitTypeId") == 0
            and stat.get("scoringPeriodId") == 0
        ):
            return stat.get("appliedTotal")
    return None


def _season_drafted(year):
    detail = read(year, "mDraftDetail")
    return bool((detail or {}).get("draftDetail", {}).get("drafted"))


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


def _next_season_outlook(year):
    """{player id: (projected points or None, projected round or None, projected pick or None)}.

    Built from year+1's own rostered players -- there is no archived view of
    the full free-agent pool, only what the ten teams currently hold, so
    coverage is real but not complete (94% of a full roster carries over,
    checked against 2025 -> 2026). A player found on more than one team's
    roster across the season (traded) keeps the first entry seen; ESPN's
    projection is a property of the player, not the team, so it does not
    matter which one.

    ESPN's averageDraftPosition is a single continuous number across the
    whole overall draft (e.g. 11.85), not round-and-pick -- so round.pick is
    computed the same way an overall pick number becomes one for a real
    draft, round = ceil(overall / team_count), and never just the raw ADP
    printed with a decimal point. That distinction is not cosmetic: an ADP of
    1.33 formatted carelessly reads exactly like round-1-pick-33, which does
    not exist in a 10-team league. Properly split, 1.33 is round 1, and 1.33
    positions into round 1 (no subtraction needed since it is under the team
    count), rounded to the nearest whole pick -> pick 1. A raw ADP of 11.85
    becomes round ceil(11.85/10)=2, position 11.85-10=1.85 into that round,
    nearest pick 2 -> "2.2". The pick half is clamped to [1, team_count] so
    float edge cases at a round boundary can never spill into a pick number
    that does not exist in this league.
    """
    payload = read(year + 1, "mRoster")
    if not payload:
        return {}

    teams = payload.get("teams") or []
    team_count = len(teams) or 10

    outlook = {}
    for team in teams:
        for entry in (team.get("roster") or {}).get("entries") or []:
            player_id = entry.get("playerId")
            if player_id in outlook:
                continue
            player = (entry.get("playerPoolEntry") or {}).get("player") or {}

            projected = _projected_total(player, year + 1)
            if projected is not None:
                projected = round(projected, 1)

            adp = (player.get("ownership") or {}).get("averageDraftPosition")
            projected_round = None
            projected_pick = None
            if adp:
                projected_round = int(math.ceil(adp / team_count))
                position_in_round = adp - (projected_round - 1) * team_count
                projected_pick = max(1, min(team_count, round(position_in_round)))

            outlook[player_id] = (projected, projected_round, projected_pick)
    return outlook


def rosters_by_season(history):
    """{year: {manager display name: [players]}}.

    Which seasons are included is decided entirely by _season_drafted -- see
    the module docstring.
    """
    unmapped = set()
    result = {}

    for year in sorted(history.seasons):
        if not _season_drafted(year):
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
                        "playerId": player_id,
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

    # Next-season outlook only for the single newest drafted season -- the
    # only one anyone is actually deciding keepers from right now. Attaching
    # it to older seasons would mean re-fetching each one's own "next year"
    # roster and presenting a number nobody asked about.
    if result:
        latest = max(result)
        outlook = _next_season_outlook(latest)
        if outlook:
            for players in result[latest].values():
                for player in players:
                    projected, projected_round, projected_pick = outlook.get(
                        player["playerId"], (None, None, None)
                    )
                    player["nextSeasonPoints"] = projected
                    player["nextSeasonRound"] = projected_round
                    player["nextSeasonPick"] = projected_pick

    if unmapped:
        print("  warning: unmapped roster position ids seen: %s" % sorted(unmapped))

    return result
