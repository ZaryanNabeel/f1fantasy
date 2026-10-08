from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from ..auth.services import login_required
from . import services as svc

bp = Blueprint("fantasy", __name__)


@bp.get("/leaderboard")
def leaderboard():
    return render_template("fantasy/leaderboard.html", rows=svc.leaderboard(current_app.config["F1_SEASON"]))


@bp.get("/fantasy/<int:team_id>")
def view_team(team_id):
    team = svc.load_team_view(team_id)
    if not team:
        abort(404)
    return render_template("fantasy/team.html", team=team, own=g.user and g.user["id"] == team["user_id"])


@bp.get("/my-team")
@login_required
def my_team():
    existing = svc.get_user_team(g.user["id"], current_app.config["F1_SEASON"])
    team = svc.load_team_view(existing["id"]) if existing else None
    return render_template("fantasy/team.html", team=team, own=True)


@bp.route("/my-team/edit", methods=["GET", "POST"])
@login_required
def edit_team():
    season = current_app.config["F1_SEASON"]
    existing = svc.get_user_team(g.user["id"], season)
    if existing:
        form = {"name": existing["name"], "driver_ids": existing["driver_ids"],
                "constructor_id": existing["constructor_id"]}
    else:
        form = {"name": "", "driver_ids": [], "constructor_id": None}
    errors = []
    if request.method == "POST":
        constructor = svc.parse_ids([request.form.get("constructor_id", "")])
        form = {"name": request.form.get("name", "").strip(),
                "driver_ids": svc.parse_ids(request.form.getlist("drivers")),
                "constructor_id": constructor[0] if constructor else None}
        errors = svc.save_team(g.user["id"], season, form["name"], form["driver_ids"],
                               form["constructor_id"], existing)
        if not errors:
            flash("Team saved!", "success")
            return redirect(url_for("fantasy.my_team"))
    drivers, teams = svc.load_catalog()
    return render_template(
        "fantasy/edit.html", form=form, errors=errors, existing=existing, budget=svc.BUDGET,
        drivers=[d for d in drivers.values() if d["active"] or d["id"] in form["driver_ids"]],
        teams=[t for t in teams.values() if t["active"] or t["id"] == form["constructor_id"]],
    ), 400 if errors else 200
