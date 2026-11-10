"""Move an existing SQLite install into PostgreSQL, keeping the audit chain intact.

    python -m app.copy_to_postgres /path/to/old/data

COUNTERSIGN_DATABASE_URL must point at an empty, migrated database. The source is only read: it
is copied to a temporary folder first, because its newest rows may still be in the WAL file.
"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, func, select

from . import audit, models, vault  # noqa: F401  (models registers tables)
from .config import get_settings
from .db import Base, init_db, run_migrations

_SECRET_KEYS = (
    "audit_key", "anthropic_api_key", "github_token", "github_app_id",
    "github_app_private_key", "github_webhook_secret",
)


def copy_rows(source_url: str, target_url: str) -> dict[str, int]:
    source, target = create_engine(source_url), create_engine(target_url)
    counts: dict[str, int] = {}
    with source.connect() as reader, target.begin() as writer:
        for table in Base.metadata.sorted_tables:
            if writer.scalar(select(func.count()).select_from(table)):
                raise SystemExit(f"Target table {table.name} is not empty. Nothing was copied.")
        for table in Base.metadata.sorted_tables:
            rows = [dict(r._mapping) for r in reader.execute(select(table))]
            if rows:
                writer.execute(table.insert(), rows)
            counts[table.name] = len(rows)
    return counts


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    source_dir = Path(sys.argv[1])
    source_db = source_dir / "foreman.db"
    if not source_db.exists():
        print(f"No foreman.db in {source_dir}")
        return 1
    settings = get_settings()
    if settings.is_sqlite:
        print("Set COUNTERSIGN_DATABASE_URL to the PostgreSQL database first.")
        return 1
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    secrets_file = source_dir / "secrets.json"
    if secrets_file.exists():
        stored = json.loads(secrets_file.read_text())
        # The chain can only be verified with the key it was signed with.
        vault.update(**{k: stored[k] for k in _SECRET_KEYS if k in stored})

    with tempfile.TemporaryDirectory() as tmp:
        for f in source_dir.glob("foreman.db*"):
            shutil.copy(f, tmp)
        source_url = f"sqlite:///{tmp}/foreman.db"
        run_migrations(source_url)
        run_migrations(settings.database_url)
        counts = copy_rows(source_url, settings.database_url)

    init_db(settings.database_url, migrate=False)
    result = audit.verify_chain()
    for table, count in counts.items():
        print(f"  {table}: {count}")
    if not result["ok"]:
        print(f"Copied, but the audit chain does not verify: {result['reason']}")
        return 1
    print(f"Done. Audit chain verified across {result['checked']} events.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
