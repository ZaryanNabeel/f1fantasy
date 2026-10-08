from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from .. import db
from ..auth.services import admin_required
from . import services as svc

bp = Blueprint("f1", __name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ------------------------------------------------------------------ public pages

@bp.get("/drivers")
def drivers():
    return render_template("f1/drivers.html", drivers=svc.list_drivers(current_app.config["F1_SEASON"]))


@bp.get("/drivers/<int:driver_id>")
def driver_detail(driver_id):
    season = current_app.config["F1_SEASON"]
    driver = db.query(
        """SELECT d.*, t.name AS team_name, t.colour_hex FROM drivers d
           JOIN teams t ON t.id = d.team_id WHERE d.id = %s""", (driver_id,), one=True)
    if not driver:
        abort(404)
    results = db.query(
        """SELECT r.id AS race_id, r.round, r.name AS race_name, rr.session_type, rr.position,
                  rr.grid, rr.points, rr.status, t.name AS team_name
           FROM race_results rr JOIN races r ON r.id = rr.race_id JOIN teams t ON t.id = rr.team_id
           WHERE rr.driver_id = %s AND r.season = %s
           ORDER BY r.round, rr.session_type = 'race'""", (driver_id, season))
    points = sum(r["points"] for r in results)
    return render_template("f1/driver_detail.html", driver=driver, results=results, points=points)


@bp.get("/teams")
def teams():
    return render_template("f1/teams.html", teams=svc.list_teams(current_app.config["F1_SEASON"]))


@bp.get("/teams/<int:team_id>")
def team_detail(team_id):
    season = current_app.config["F1_SEASON"]
    team = db.query("SELECT * FROM teams WHERE id = %s", (team_id,), one=True)
    if not team:
        abort(404)
    points = svc.constructor_points_by_id(season).get(team_id, 0)
    drivers = db.query(
        """SELECT d.*, COALESCE(p.points, 0) AS points FROM drivers d
           LEFT JOIN v_driver_points p ON p.driver_id = d.id AND p.season = %s
           WHERE d.team_id = %s ORDER BY d.active DESC, points DESC""", (season, team_id))
    return render_template("f1/team_detail.html", team=team, drivers=drivers, points=points)


@bp.get("/races")
def races():
    season = current_app.config["F1_SEASON"]
    rows = db.query(
        """SELECT r.*, EXISTS(SELECT 1 FROM race_results rr WHERE rr.race_id = r.id) AS has_results
           FROM races r WHERE r.season = %s ORDER BY r.round""", (season,))
    return render_template("f1/races.html", races=rows)


@bp.get("/races/<int:race_id>")
def race_detail(race_id):
    race = db.query("SELECT * FROM races WHERE id = %s", (race_id,), one=True)
    if not race:
        abort(404)
    rows = db.query(
        """SELECT rr.*, d.first_name, d.last_name, d.code, t.name AS team_name, t.colour_hex
           FROM race_results rr JOIN drivers d ON d.id = rr.driver_id JOIN teams t ON t.id = rr.team_id
           WHERE rr.race_id = %s ORDER BY rr.position IS NULL, rr.position""", (race_id,))
    sessions = {"race": [r for r in rows if r["session_type"] == "race"],
                "sprint": [r for r in rows if r["session_type"] == "sprint"]}
    return render_template("f1/race_detail.html", race=race, sessions=sessions)


# ------------------------------------------------------------------ admin

@admin_bp.get("")
@admin_required
def dashboard():
    counts = db.query(
        """SELECT (SELECT COUNT(*) FROM users) AS users, (SELECT COUNT(*) FROM drivers) AS drivers,
                  (SELECT COUNT(*) FROM teams) AS teams, (SELECT COUNT(*) FROM races) AS races,
                  (SELECT COUNT(*) FROM race_results) AS results,
                  (SELECT COUNT(*) FROM fantasy_teams) AS fantasy_teams""", one=True)
    last_sync = db.query("SELECT * FROM sync_log ORDER BY id DESC LIMIT 1", one=True)
    return render_template("admin/dashboard.html", counts=counts, last_sync=last_sync)


@admin_bp.post("/sync")
@admin_required
def sync():
    from .jolpica import sync_season

    try:
        _, summary = sync_season(current_app.config["F1_SEASON"])
    except Exception as exc:  # network/API failure must not 500 the admin page
        current_app.logger.exception("sync failed")
        flash(f"Sync failed: {exc.__class__.__name__}. Data was not changed.", "error")
    else:
        flash(f"Sync complete: {summary}.", "success")
    return redirect(url_for("admin.dashboard"))


@admin_bp.get("/drivers")
@admin_required
def drivers():
    rows = svc.list_drivers(current_app.config["F1_SEASON"], include_inactive=True)
    return render_template("admin/drivers.html", drivers=rows)


@admin_bp.route("/drivers/new", methods=["GET", "POST"])
@admin_bp.route("/drivers/<int:driver_id>/edit", methods=["GET", "POST"])
@admin_required
def driver_form(driver_id=None):
    driver = None
    if driver_id:
        driver = db.query("SELECT * FROM drivers WHERE id = %s", (driver_id,), one=True)
        if not driver:
            abort(404)
    form, errors = dict(driver or {}), {}
    if request.method == "POST":
        form = request.form.to_dict()
        clean, errors = svc.validate_driver(form, svc.active_team_ids())
        clean["active"] = form["active"] = 1 if form.get("active") else 0
        if not errors:
            errors = svc.driver_uniqueness_errors(clean, driver_id)
        if not errors:
            cols = ["driver_ref", "code", "permanent_number", "first_name", "last_name",
                    "nationality", "team_id", "price", "active"]
            vals = [clean[c] for c in cols]
            if driver_id:
                db.execute(f"UPDATE drivers SET {', '.join(c + '=%s' for c in cols)} WHERE id=%s",
                           (*vals, driver_id))
            else:
                db.execute(f"INSERT INTO drivers ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                           vals)
            flash("Driver saved.", "success")
            return redirect(url_for("admin.drivers"))
    teams = db.query("SELECT id, name FROM teams WHERE active = 1 ORDER BY name")
    return render_template("admin/driver_form.html", form=form, errors=errors, teams=teams,
                           driver=driver), 400 if errors else 200


@admin_bp.post("/drivers/<int:driver_id>/deactivate")
@admin_required
def driver_deactivate(driver_id):
    # always a soft delete: results and fantasy picks keep referencing the row
    db.execute("UPDATE drivers SET active = 0 WHERE id = %s", (driver_id,))
    flash("Driver deactivated.", "info")
    return redirect(url_for("admin.drivers"))


@admin_bp.get("/teams")
@admin_required
def teams():
    return render_template("admin/teams.html",
                           teams=svc.list_teams(current_app.config["F1_SEASON"], include_inactive=True))


@admin_bp.route("/teams/new", methods=["GET", "POST"])
@admin_bp.route("/teams/<int:team_id>/edit", methods=["GET", "POST"])
@admin_required
def team_form(team_id=None):
    team = None
    if team_id:
        team = db.query("SELECT * FROM teams WHERE id = %s", (team_id,), one=True)
        if not team:
            abort(404)
    form, errors = dict(team or {}), {}
    if request.method == "POST":
        form = request.form.to_dict()
        clean, errors = svc.validate_team(form)
        clean["active"] = form["active"] = 1 if form.get("active") else 0
        if not errors and db.query("SELECT 1 FROM teams WHERE constructor_ref=%s AND id<>%s",
                                   (clean["constructor_ref"], team_id or 0), one=True):
            errors["constructor_ref"] = "Reference already used."
        if not errors:
            cols = ["constructor_ref", "name", "nationality", "colour_hex", "price", "active"]
            vals = [clean[c] for c in cols]
            if team_id:
                db.execute(f"UPDATE teams SET {', '.join(c + '=%s' for c in cols)} WHERE id=%s", (*vals, team_id))
            else:
                db.execute(f"INSERT INTO teams ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", vals)
            flash("Team saved.", "success")
            return redirect(url_for("admin.teams"))
    return render_template("admin/team_form.html", form=form, errors=errors, team=team), 400 if errors else 200


@admin_bp.post("/teams/<int:team_id>/deactivate")
@admin_required
def team_deactivate(team_id):
    if db.query("SELECT 1 FROM drivers WHERE team_id = %s AND active = 1", (team_id,), one=True):
        flash("This team still has active drivers. Move or deactivate them first.", "error")
    else:
        db.execute("UPDATE teams SET active = 0 WHERE id = %s", (team_id,))
        flash("Team deactivated.", "info")
    return redirect(url_for("admin.teams"))
