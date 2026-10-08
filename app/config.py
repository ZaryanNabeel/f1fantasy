import os

if os.environ.get("FLASK_ENV", "development") != "production":
    from dotenv import load_dotenv

    load_dotenv()


def _env(name, rds_name, default=None):
    """DB_* wins; on Beanstalk fall back to RDS_* when DB_HOST is unset."""
    if not os.environ.get("DB_HOST") and os.environ.get("RDS_HOSTNAME"):
        return os.environ.get(rds_name, default)
    return os.environ.get(name, default)


def load_config():
    env = os.environ.get("FLASK_ENV", "development")
    secret = os.environ.get("SECRET_KEY")
    if env == "production" and not secret:
        raise RuntimeError("SECRET_KEY must be set in production")
    return {
        "ENV_NAME": env,
        "SECRET_KEY": secret or "dev-only-insecure-key",
        "DB_HOST": _env("DB_HOST", "RDS_HOSTNAME", "127.0.0.1"),
        "DB_PORT": int(_env("DB_PORT", "RDS_PORT", "3306")),
        "DB_NAME": _env("DB_NAME", "RDS_DB_NAME", "f1fantasy"),
        "DB_USER": _env("DB_USER", "RDS_USERNAME", "f1app"),
        "DB_PASSWORD": _env("DB_PASSWORD", "RDS_PASSWORD", ""),
        "F1_SEASON": int(os.environ.get("F1_SEASON", "2026")),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
    }
