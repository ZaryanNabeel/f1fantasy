from flask import Flask, g, jsonify, render_template, session
from flask_wtf.csrf import CSRFProtect

from . import db
from .config import load_config

csrf = CSRFProtect()


def create_app(config=None):
    app = Flask(__name__)
    app.config.update(load_config())
    if config:
        app.config.update(config)

    db.init_app(app)
    csrf.init_app(app)

    from .auth import bp as auth_bp
    from .f1data import admin_bp, bp as f1_bp
    from .fantasy import bp as fantasy_bp
    from .main import bp as main_bp

    for bp in (main_bp, auth_bp, f1_bp, admin_bp, fantasy_bp):
        app.register_blueprint(bp)

    @app.before_request
    def load_user():
        g.user = None
        uid = session.get("user_id")
        if uid is not None:
            from .auth.services import get_user

            g.user = get_user(uid)
            if g.user is None:
                session.clear()

    @app.get("/health")
    def health():
        try:
            db.query("SELECT 1", one=True)
        except Exception:
            return jsonify(status="error", db="down"), 503
        return jsonify(status="ok", db="ok")

    @app.context_processor
    def inject_season():
        return {"season": app.config["F1_SEASON"]}

    for code in (403, 404, 500):
        app.register_error_handler(
            code, lambda e, code=code: (render_template(f"errors/{code}.html"), code)
        )

    from .cli import register_cli

    register_cli(app)
    return app
