"""Bring the database schema up to date: python -m app.migrate"""

from .config import get_settings
from .db import run_migrations

if __name__ == "__main__":
    run_migrations(get_settings().database_url)
    print("Database schema is up to date.")
