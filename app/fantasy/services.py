"""Fantasy rules and scoring.

`validate_picks`, `budget_used`, `team_total` and `race_breakdown` are pure functions over plain
dicts so they can be unit-tested without a database. The rest are thin DB wrappers.
"""
from collections import Counter
from decimal import Decimal

import pymysql

from .. import db

BUDGET = Decimal("100.0")
TEAM_SIZE = 5
MAX_PER_TEAM = 2


# ------------------------------------------------------------------ pure rules

def budget_used(driver_ids, constructor_id, drivers, teams):
    cost = sum((Decimal(drivers[d]["price"]) for d in set(driver_ids) if d in drivers), Decimal("0"))
    if constructor_id in teams:
        cost += Decimal(teams[constructor_id]["price"])
    return cost


def validate_picks(name, driver_ids, constructor_id, drivers, teams):
    """Check every fantasy rule. drivers/teams map id -> {price, active, team_id/name}.

    Returns a list of human-readable errors; empty list means valid.
    """
    errors = []
    name = (name or "").strip()
    if not 3 <= len(name) <= 40:
        errors.append("Team name must be 3-40 characters.")
    unique = set(driver_ids)
    if len(unique) != len(driver_ids):
        errors.append("Each driver can only be picked once.")
    if len(unique) != TEAM_SIZE:
        errors.append(f"Pick exactly {TEAM_SIZE} drivers (you picked {len(unique)}).")
    if any(d not in drivers or not drivers[d]["active"] for d in unique):
        errors.append("Only active drivers can be picked.")
    team = teams.get(constructor_id)
    if not team or not team["active"]:
        errors.append("Pick exactly 1 active constructor.")
    per_team = Counter(drivers[d]["team_id"] for d in unique if d in drivers)
    for team_id, count in per_team.items():
        if count > MAX_PER_TEAM:
            team_name = teams.get(team_id, {}).get("name", "one team")
            errors.append(f"Max {MAX_PER_TEAM} drivers from the same team ({count} from {team_name}).")
    cost = budget_used(driver_ids, constructor_id, drivers, teams)
    if cost > BUDGET:
        errors.append(f"Budget exceeded: {cost:.1f}M of {BUDGET:.1f}M.")
    return errors


def team_total(driver_ids, constructor_id, driver_points, constructor_points):
    return sum(Decimal(driver_points.get(d, 0)) for d in driver_ids) + Decimal(
        constructor_points.get(constructor_id, 0))


def race_breakdown(result_rows, driver_ids, constructor_id):
    """result_rows: {race_id, round, race_name, driver_id, team_id, points}. One entry per race, by round."""
    driver_ids = set(driver_ids)
    per_race = {}
    for r in result_rows:
        e = per_race.setdefault(r["race_id"], {"race_id": r["race_id"], "round": r["round"],
                                               "race_name": r["race_name"],
                                               "drivers": Decimal("0"), "constructor": Decimal("0")})
        if r["driver_id"] in driver_ids:
            e["drivers"] += Decimal(r["points"])
        if r["team_id"] == constructor_id:
            e["constructor"] += Decimal(r["points"])
    for e in per_race.values():
        e["total"] = e["drivers"] + e["constructor"]
    return sorted(per_race.values(), key=lambda e: e["round"])


def parse_ids(values):
    return [int(v) for v in values if str(v).isdigit()]


# ------------------------------------------------------------------ DB access

def load_catalog():
    drivers = {r["id"]: r for r in db.query(
        """SELECT d.id, d.code, d.first_name, d.last_name, d.price, d.active, d.team_id, t.name AS team_name
           FROM drivers d JOIN teams t ON t.id = d.team_id ORDER BY d.price DESC, d.last_name""")}
    teams = {r["id"]: r for r in db.query(
        "SELECT id, name, price, active, colour_hex FROM teams ORDER BY price DESC, name")}
    return drivers, teams


def get_user_team(user_id, season):
    team = db.query("SELECT * FROM fantasy_teams WHERE user_id = %s AND season = %s", (user_id, season), one=True)
    if team:
        team["driver_ids"] = [r["driver_id"] for r in db.query(
            "SELECT driver_id FROM fantasy_picks WHERE fantasy_team_id = %s", (team["id"],))]
    return team


def save_team(user_id, season, name, driver_ids, constructor_id, existing=None):
    """Create (existing=None) or update a fantasy team. Returns list of errors (empty on success)."""
    drivers, teams = load_catalog()
    name = (name or "").strip()
    errors = validate_picks(name, driver_ids, constructor_id, drivers, teams)
    if existing is None and get_user_team(user_id, season):
        errors.append("You already have a fantasy team this season.")
    if name and db.query("SELECT 1 FROM fantasy_teams WHERE season = %s AND name = %s AND id <> %s",
                         (season, name, existing["id"] if existing else 0), one=True):
        errors.append("That team name is already taken this season.")
    if errors:
        return errors
    try:
        if existing:
            team_id = existing["id"]
            db.execute("UPDATE fantasy_teams SET name = %s, constructor_id = %s WHERE id = %s",
                       (name, constructor_id, team_id), commit=False)
            db.execute("DELETE FROM fantasy_picks WHERE fantasy_team_id = %s", (team_id,), commit=False)
        else:
            team_id = db.execute(
                "INSERT INTO fantasy_teams (user_id, season, name, constructor_id) VALUES (%s, %s, %s, %s)",
                (user_id, season, name, constructor_id), commit=False)
        for d in set(driver_ids):
            db.execute("INSERT INTO fantasy_picks (fantasy_team_id, driver_id) VALUES (%s, %s)",
                       (team_id, d), commit=False)
        db.commit()
    except pymysql.err.IntegrityError:  # concurrent save hit a UNIQUE key
        db.rollback()
        return ["That team name is taken or you already have a team this season."]
    return []


def load_team_view(team_id):
    """Everything the team page needs: picks, constructor, budget, total and per-race breakdown."""
    team = db.query(
        """SELECT ft.*, u.username, t.name AS constructor_name, t.price AS constructor_price,
                  t.colour_hex AS constructor_colour
           FROM fantasy_teams ft JOIN users u ON u.id = ft.user_id JOIN teams t ON t.id = ft.constructor_id
           WHERE ft.id = %s""", (team_id,), one=True)
    if not team:
        return None
    season = team["season"]
    picks = db.query(
        """SELECT d.id, d.code, d.first_name, d.last_name, d.price, d.active, t.name AS team_name,
                  COALESCE(p.points, 0) AS points
           FROM fantasy_picks fp JOIN drivers d ON d.id = fp.driver_id JOIN teams t ON t.id = d.team_id
           LEFT JOIN v_driver_points p ON p.driver_id = d.id AND p.season = %s
           WHERE fp.fantasy_team_id = %s ORDER BY points DESC""", (season, team_id))
    ids = [p["id"] for p in picks]
    c_points = db.query("SELECT points FROM v_constructor_points WHERE team_id = %s AND season = %s",
                        (team["constructor_id"], season), one=True)
    team["constructor_points"] = c_points["points"] if c_points else Decimal("0")
    team["picks"] = picks
    team["budget_used"] = sum((p["price"] for p in picks), Decimal("0")) + team["constructor_price"]
    team["budget_left"] = BUDGET - team["budget_used"]
    team["total"] = team_total(ids, team["constructor_id"], {p["id"]: p["points"] for p in picks},
                               {team["constructor_id"]: team["constructor_points"]})
    placeholders = ", ".join(["%s"] * len(ids)) or "NULL"
    rows = db.query(
        f"""SELECT rr.race_id, r.round, r.name AS race_name, rr.driver_id, rr.team_id, rr.points
            FROM race_results rr JOIN races r ON r.id = rr.race_id
            WHERE r.season = %s AND (rr.driver_id IN ({placeholders}) OR rr.team_id = %s)""",
        (season, *ids, team["constructor_id"]))
    team["breakdown"] = race_breakdown(rows, ids, team["constructor_id"])
    return team


def load_team_summary(user_id, season):
    return db.query(
        "SELECT fantasy_team_id, team_name, total_points FROM v_leaderboard WHERE season = %s AND username = "
        "(SELECT username FROM users WHERE id = %s)", (season, user_id), one=True)


def leaderboard(season, limit=None):
    sql = """SELECT * FROM v_leaderboard WHERE season = %s
             ORDER BY total_points DESC, created_at ASC, fantasy_team_id ASC"""
    rows = db.query(sql + (" LIMIT %s" if limit else ""), (season, limit) if limit else (season,))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows
