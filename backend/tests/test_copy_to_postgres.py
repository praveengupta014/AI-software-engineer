import sys

import pytest

from app import copy_to_postgres
from tests.conftest import TEST_DATABASE_URL, reset_postgres

pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="needs TEST_DATABASE_URL")


def test_copy_keeps_data_and_a_verifiable_chain(tmp_path, monkeypatch):
    """Builds a real SQLite install, then moves it."""
    import subprocess

    source = tmp_path / "old"
    script = """
from app.config import get_settings
from app.db import init_db, write_tx
from app import audit
from app.models import Requirement, User
init_db(get_settings().database_url)
with write_tx() as s:
    s.add(User(name="Asha", password_hash="salt$hash"))
    s.add(Requirement(title="T", body="B", repo="o/r", base_branch="main", created_by="Asha"))
    for i in range(5):
        audit.record(s, actor_type="human", actor="Asha", action="x", subject_type="t",
                     subject_id=str(i), data={"n": i, "zeta": 1, "alpha": ["é"]})
"""
    env = {"COUNTERSIGN_DATA_DIR": str(source), "PATH": "/usr/bin:/bin"}
    source.mkdir()
    subprocess.run([sys.executable, "-c", script], check=True, env=env)

    reset_postgres(TEST_DATABASE_URL)
    target = tmp_path / "new"
    monkeypatch.setenv("COUNTERSIGN_DATA_DIR", str(target))
    monkeypatch.setenv("COUNTERSIGN_DATABASE_URL", TEST_DATABASE_URL)
    from app.config import get_settings

    get_settings.cache_clear()
    monkeypatch.setattr(sys, "argv", ["copy", str(source)])
    assert copy_to_postgres.main() == 0

    # The second run must refuse rather than duplicate anything.
    with pytest.raises(SystemExit, match="not empty"):
        copy_to_postgres.main()
    get_settings.cache_clear()
