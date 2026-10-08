"""Driver/team validation (pure) and read queries for public pages."""
import re
from decimal import Decimal, InvalidOperation

from .. import db

CODE_RE = re.compile(r"^[A-Z]{3}$")
REF_RE = re.compile(r"^[a-z0-9_]{2,50}$")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")
PRICE_MIN, PRICE_MAX = Decimal("4.0"), Decimal("35.0")


def parse_price(raw):
    """Return Decimal price or None if not 4.0-35.0 in steps of 0.5."""
    try:
        price = Decimal(str(raw).strip())
    except (InvalidOperation, ValueError):
        return None
    if not price.is_finite() or not PRICE_MIN <= price <= PRICE_MAX or (price * 2) % 1 != 0:
        return None
    return price


def validate_driver(data, active_team_ids):
    """data: dict of raw form strings. Returns (clean, errors). Uniqueness checked separately."""
    errors, clean = {}, {}
    clean["driver_ref"] = data.get("driver_ref", "").strip().lower()
    if not REF_RE.match(clean["driver_ref"]):
        errors["driver_ref"] = "Reference must be 2-50 lowercase letters, digits or underscores."
    clean["code"] = data.get("code", "").strip()
    if not CODE_RE.match(clean["code"]):
        errors["code"] = "Code must be exactly 3 uppercase letters."
    num = data.get("permanent_number", "").strip()
    clean["permanent_number"] = None
    if num:
        if num.isdigit() and 1 <= int(num) <= 99:
            clean["permanent_number"] = int(num)
        else:
            errors["permanent_number"] = "Number must be between 1 and 99."
    for f in ("first_name", "last_name"):
        clean[f] = data.get(f, "").strip()
        if not 1 <= len(clean[f]) <= 50:
            errors[f] = "Required, max 50 characters."
    clean["nationality"] = data.get("nationality", "").strip()[:50] or None
    clean["price"] = parse_price(data.get("price", ""))
    if clean["price"] is None:
        errors["price"] = "Price must be 4.0-35.0 in steps of 0.5."
    team = data.get("team_id", "")
    clean["team_id"] = int(team) if str(team).isdigit() else None
    if clean["team_id"] not in active_team_ids:
        errors["team_id"] = "Driver must belong to an existing active team."
    return clean, errors


def validate_team(data):
    errors, clean = {}, {}
    clean["constructor_ref"] = data.get("constructor_ref", "").strip().lower()
    if not REF_RE.match(clean["constructor_ref"]):
        errors["constructor_ref"] = "Reference must be 2-50 lowercase letters, digits or underscores."
    clean["name"] = data.get("name", "").strip()
    if not 1 <= len(clean["name"]) <= 100:
        errors["name"] = "Required, max 100 characters."
    clean["nationality"] = data.get("nationality", "").strip()[:50] or None
    clean["colour_hex"] = data.get("colour_hex", "").strip() or None
    if clean["colour_hex"] and not HEX_RE.match(clean["colour_hex"]):
        errors["colour_hex"] = "Colour must look like #FF8000."
    clean["price"] = parse_price(data.get("price", ""))
    if clean["price"] is None:
        errors["price"] = "Price must be 4.0-35.0 in steps of 0.5."
    return clean, errors


def driver_uniqueness_errors(clean, exclude_id=None):
    exclude_id = exclude_id or 0
    errors = {}
    if db.query("SELECT 1 FROM drivers WHERE driver_ref=%s AND id<>%s", (clean["driver_ref"], exclude_id), one=True):
        errors["driver_ref"] = "Reference already used."
    if db.query("SELECT 1 FROM drivers WHERE code=%s AND id<>%s", (clean["code"], exclude_id), one=True):
        errors["code"] = "Code already used by another driver."
    if clean["permanent_number"] and db.query(
        "SELECT 1 FROM drivers WHERE permanent_number=%s AND active=1 AND id<>%s",
        (clean["permanent_number"], exclude_id),
        one=True,
    ):
        errors["permanent_number"] = "Number already used by an active driver."
    return errors


def active_team_ids():
    return {r["id"] for r in db.query("SELECT id FROM teams WHERE active=1")}


def driver_points_by_id(season):
    return {r["driver_id"]: r["points"] for r in db.query(
        "SELECT driver_id, points FROM v_driver_points WHERE season=%s", (season,))}


def constructor_points_by_id(season):
    return {r["team_id"]: r["points"] for r in db.query(
        "SELECT team_id, points FROM v_constructor_points WHERE season=%s", (season,))}


def list_drivers(season, include_inactive=False):
    return db.query(
        """SELECT d.*, t.name AS team_name, t.colour_hex, COALESCE(p.points, 0) AS points
           FROM drivers d JOIN teams t ON t.id = d.team_id
           LEFT JOIN v_driver_points p ON p.driver_id = d.id AND p.season = %s
           WHERE d.active = 1 OR %s
           ORDER BY points DESC, d.last_name""",
        (season, include_inactive),
    )


def list_teams(season, include_inactive=False):
    return db.query(
        """SELECT t.*, COALESCE(p.points, 0) AS points
           FROM teams t LEFT JOIN v_constructor_points p ON p.team_id = t.id AND p.season = %s
           WHERE t.active = 1 OR %s
           ORDER BY points DESC, t.name""",
        (season, include_inactive),
    )
