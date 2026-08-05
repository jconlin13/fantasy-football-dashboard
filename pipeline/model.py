"""The league as plain Python, loaded from the raw archive.

Every analytic reads this module and nothing reads ESPN's JSON directly. The
point is that ESPN's quirks get dealt with exactly once, here, instead of
leaking into eight different metrics that each handle them slightly differently.

No network. Everything comes from data/raw, which is committed.

The central table is `games`: one row per team per week, so a single matchup
produces two rows facing each other. Records, head-to-head and luck are all
just different groupings of that one table.

    from model import load_league_history
    history = load_league_history()
    for game in history.games:
        ...
"""

import collections
import gzip
import json
import os

import identity
from espn_client import load_league

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
RAW = os.path.join(ROOT, "data", "raw")

# What a postseason game was actually for.
REGULAR = "regular"
CHAMPIONSHIP = "championship"   # still alive for the title
THIRD_PLACE = "third_place"     # the two teams knocked out in the semifinal
CONSOLATION = "consolation"     # placement only

# Games that count toward records, head-to-head and luck.
#
# The league's rule: consolation games do not count. The third-place game does
# -- it is played by the two teams that were still alive going into the last
# round, and the league takes it seriously in a way it does not take the fifth-
# and seventh-place games.
COUNTING_BRACKETS = (REGULAR, CHAMPIONSHIP, THIRD_PLACE)

# The postseason brackets, for records that separate playoffs from the season.
PLAYOFF_BRACKETS = (CHAMPIONSHIP, THIRD_PLACE)


def read(year, view, week=None):
    """One archived payload, or None if it was never fetched."""
    if week is None:
        path = os.path.join(RAW, str(year), "%s.json.gz" % view)
    else:
        path = os.path.join(RAW, str(year), "weeks", "%02d" % week, "%s.json.gz" % view)
    if not os.path.exists(path):
        return None
    with gzip.open(path, "rb") as handle:
        return json.loads(handle.read().decode("utf-8"))


def archived_years():
    if not os.path.isdir(RAW):
        return []
    return sorted(int(name) for name in os.listdir(RAW) if name.isdigit())


class Season(object):
    def __init__(self, year, settings, teams_payload, owners, team_overrides=None):
        self.year = year
        team_overrides = team_overrides or {}

        schedule = (settings.get("settings") or {}).get("scheduleSettings") or {}
        status = settings.get("status") or {}
        self.regular_weeks = schedule.get("matchupPeriodCount") or 0
        self.playoff_teams = schedule.get("playoffTeamCount") or 0
        self.final_week = min(
            status.get("finalScoringPeriod") or 0,
            status.get("latestScoringPeriod") or 0,
        )
        self.roster_slots = (
            (settings.get("settings") or {}).get("rosterSettings") or {}
        ).get("lineupSlotCounts") or {}

        # teamId -> canonical manager. A team can list several owner accounts;
        # they all resolve to the same manager once owners.ini has merged them,
        # and the primary owner is the tiebreak if they somehow do not.
        self.manager_of = {}
        self.seed = {}
        self.espn_rank = {}
        self.espn_record = {}

        for team in teams_payload.get("teams") or []:
            tid = team.get("id")
            resolved = []
            for owner in team.get("owners") or []:
                resolved.append(identity.resolve(owner, owners))
            primary = team.get("primaryOwner")
            if primary:
                resolved.insert(0, identity.resolve(primary, owners))
            if resolved:
                self.manager_of[tid] = resolved[0]

            # A stated override beats whatever ESPN recorded -- see
            # identity.load_team_overrides().
            override = team_overrides.get((year, tid))
            if override:
                self.manager_of[tid] = identity.resolve(override, owners)

            self.seed[tid] = team.get("playoffSeed")
            self.espn_rank[tid] = team.get("rankCalculatedFinal")
            overall = (team.get("record") or {}).get("overall") or {}
            self.espn_record[tid] = (
                overall.get("wins") or 0,
                overall.get("losses") or 0,
                overall.get("ties") or 0,
            )

        self.champion = None  # filled in once the bracket is walked

    @property
    def complete(self):
        return self.final_week >= self.regular_weeks > 0


def classify_postseason(season, weeks):
    """Work out which postseason games were played for the title.

    ESPN's own `playoffTierType` is null on every matchup in this league, so the
    championship bracket has to be reconstructed. That is done by walking it
    forward rather than guessing from seeds:

        the teams that made the playoffs start out alive;
        a game between two live teams is a championship game;
        its winner stays alive, its loser is out;
        a team with a bye stays alive without playing.

    Everything else -- games among teams that missed the playoffs, and games
    between teams already knocked out -- is placement only.

    Checked against 2025: this reproduces ESPN's own rankCalculatedFinal for all
    ten teams, and the last team standing is the team ESPN ranks first.

    Returns {(week, home_team, away_team): bracket}.
    """
    alive = set(
        tid
        for tid, seed in season.seed.items()
        if seed and season.playoff_teams and seed <= season.playoff_teams
    )

    brackets = {}
    knocked_out_in = {}  # team -> the week it lost its championship game

    for week in sorted(weeks):
        if week <= season.regular_weeks:
            continue

        survivors = set()
        eliminated = set()
        played = set()

        for matchup in weeks[week]:
            home, away = matchup["home"], matchup["away"]
            if away is None:  # bye: advances without playing
                continue
            played.add(home)
            played.add(away)

            if home in alive and away in alive:
                brackets[(week, home, away)] = CHAMPIONSHIP
                winner, loser = matchup["winner_ids"]
                if winner is not None:
                    survivors.add(winner)
                    eliminated.add(loser)
                    knocked_out_in[loser] = week
                else:  # undecided -- keep both rather than invent an outcome
                    survivors.update((home, away))
            else:
                brackets[(week, home, away)] = CONSOLATION

        # Teams that had a bye this week are still alive.
        alive = (alive - eliminated - played) | survivors

    # The third-place game: in the same week as the final, between the two teams
    # knocked out in the round immediately before it. That is what separates it
    # from the fifth-place game, which is played by teams knocked out a round
    # earlier -- both look identical if you only go by the week.
    championship_weeks = [w for (w, _h, _a), b in brackets.items() if b == CHAMPIONSHIP]
    if championship_weeks:
        final_week = max(championship_weeks)
        semifinal_week = max(
            [w for w in championship_weeks if w < final_week] or [final_week - 1]
        )
        for (week, home, away), bracket in list(brackets.items()):
            if week != final_week or bracket != CONSOLATION:
                continue
            if (
                knocked_out_in.get(home) == semifinal_week
                and knocked_out_in.get(away) == semifinal_week
            ):
                brackets[(week, home, away)] = THIRD_PLACE

    # The title game is the last championship game played; its winner is champ.
    if championship_weeks:
        for (week, home, away), bracket in brackets.items():
            if week == final_week and bracket == CHAMPIONSHIP:
                for matchup in weeks[week]:
                    if matchup["home"] == home and matchup["away"] == away:
                        winner = matchup["winner_ids"][0]
                        if winner is not None:
                            season.champion = season.manager_of.get(winner)
    return brackets


def _matchups(payload):
    """Flatten ESPN's schedule into week -> [matchup dicts]."""
    weeks = collections.defaultdict(list)
    for entry in payload.get("schedule") or []:
        week = entry.get("matchupPeriodId")
        home = entry.get("home") or {}
        away = entry.get("away") or None

        home_id = home.get("teamId")
        away_id = (away or {}).get("teamId")
        home_points = home.get("totalPoints") or 0.0
        away_points = (away or {}).get("totalPoints") or 0.0

        outcome = entry.get("winner")
        if away is None or outcome in (None, "UNDECIDED"):
            winner_ids = (None, None)
        elif outcome == "HOME":
            winner_ids = (home_id, away_id)
        else:
            winner_ids = (away_id, home_id)

        weeks[week].append(
            {
                "week": week,
                "home": home_id,
                "away": away_id,
                "home_points": home_points,
                "away_points": away_points,
                "winner_ids": winner_ids,
            }
        )
    return weeks


class History(object):
    def __init__(self):
        self.managers = {}       # canonical id -> display name
        self.seasons = {}        # year -> Season
        self.games = []          # one row per team-week

    def counting_games(self):
        return [g for g in self.games if g["counts"]]


def load_league_history(years=None):
    owners = identity.load_owners()
    team_overrides = identity.load_team_overrides()
    history = History()

    for year in years or archived_years():
        settings = read(year, "mSettings")
        teams = read(year, "mTeam")
        matchups = read(year, "mMatchup")
        if not (settings and teams and matchups):
            continue

        season = Season(year, settings, teams, owners, team_overrides)
        history.seasons[year] = season

        # Two teams resolving to one manager in a season means an ownership
        # record is wrong, and it would silently sum two teams' results into
        # one row. Loud, because it is invisible in the output otherwise.
        counts = collections.Counter(season.manager_of.values())
        for manager, total in counts.items():
            if total > 1:
                raise ValueError(
                    "%d: %s owns %d teams -- add a [teams] override in owners.ini"
                    % (year, manager, total)
                )

        # Managers accumulate across every season they appear in, and are never
        # removed. Someone who left the league still has to exist, because
        # everyone else's career record against them keeps counting.
        for manager in season.manager_of.values():
            history.managers.setdefault(
                manager, identity.display_name(manager, owners)
            )

        weeks = _matchups(matchups)
        brackets = classify_postseason(season, weeks)

        for week in sorted(weeks):
            for matchup in weeks[week]:
                home, away = matchup["home"], matchup["away"]
                is_bye = away is None
                if week <= season.regular_weeks:
                    bracket = REGULAR
                else:
                    bracket = brackets.get((week, home, away), CONSOLATION)

                sides = [(home, away, matchup["home_points"], matchup["away_points"])]
                if not is_bye:
                    sides.append(
                        (away, home, matchup["away_points"], matchup["home_points"])
                    )

                for team, opponent, points_for, points_against in sides:
                    winner = matchup["winner_ids"][0]
                    history.games.append(
                        {
                            "year": year,
                            "week": week,
                            "team_id": team,
                            "manager": season.manager_of.get(team),
                            "opponent_team_id": opponent,
                            "opponent": season.manager_of.get(opponent),
                            "points_for": round(points_for, 2),
                            "points_against": round(points_against, 2),
                            "won": None if winner is None else (team == winner),
                            "is_bye": is_bye,
                            "is_playoff": week > season.regular_weeks,
                            "bracket": bracket,
                            # A bye is not a game anyone played, and consolation
                            # games are not taken seriously by this league.
                            "counts": (not is_bye)
                            and bracket in COUNTING_BRACKETS
                            and winner is not None,
                        }
                    )

    return history
