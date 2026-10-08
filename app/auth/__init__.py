import pymysql
from flask import Blueprint, current_app, flash, g, redirect, render_template, request, session, url_for

from .services import (
    LOGIN_ERROR,
    authenticate,
    create_user,
    is_safe_next,
    login_required,
    uniqueness_errors,
    validate_registration,
)

bp = Blueprint("auth", __name__)


@bp.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("main.index"))
    form, errors = {}, {}
    if request.method == "POST":
        form = {k: request.form.get(k, "").strip() for k in ("username", "email")}
        password, confirm = request.form.get("password", ""), request.form.get("confirm", "")
        errors = validate_registration(form["username"], form["email"], password, confirm)
        if not errors:
            errors = uniqueness_errors(form["username"], form["email"])
        if not errors:
            try:
                user_id = create_user(form["username"], form["email"], password)
            except pymysql.err.IntegrityError:  # lost a race with a concurrent registration
                errors = {"username": "That username or email is already taken."}
            else:
                session.clear()
                session["user_id"] = user_id
                flash("Welcome! Your account has been created.", "success")
                return redirect(url_for("fantasy.my_team"))
    return render_template("auth/register.html", form=form, errors=errors), 400 if errors else 200


@bp.route("/login", methods=["GET", "POST"])
def login():
    next_url = request.values.get("next", "")
    if g.user:
        return redirect(next_url if is_safe_next(next_url) else url_for("main.index"))
    error, username = None, ""
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        user_id = authenticate(username, request.form.get("password", ""))
        if user_id:
            session.clear()
            session["user_id"] = user_id
            return redirect(next_url if is_safe_next(next_url) else url_for("main.index"))
        error = LOGIN_ERROR
    return (
        render_template("auth/login.html", error=error, username=username, next=next_url),
        401 if error else 200,
    )


@bp.post("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("main.index"))


@bp.get("/profile")
@login_required
def profile():
    from ..fantasy.services import load_team_summary

    team = load_team_summary(g.user["id"], current_app.config["F1_SEASON"])
    return render_template("auth/profile.html", team=team)
