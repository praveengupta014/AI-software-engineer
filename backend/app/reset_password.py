"""Set a new password from the command line: uv run python -m app.reset_password

Add --generate to have a password created and printed, for copying into the sign-in form.

Stop the server first. Running this needs access to the machine and its data folder, which
is the proof of ownership when nobody can sign in. The new password is typed at a hidden
prompt, so it stays out of shell history.
"""

import getpass
import secrets
import sys

from sqlalchemy import delete, select

from . import audit
from .auth import hash_password
from .config import get_settings
from .db import init_db, read_session, write_tx
from .models import Session, User

MIN_LENGTH = 8
# No look-alike characters (0/o, 1/l/i), so a generated password is easy to read back.
_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


def reset(name: str, password: str) -> None:
    password_hash = hash_password(password)
    with write_tx() as s:
        user = s.scalar(select(User).where(User.name == name))
        if user is None:
            raise ValueError(f"No account named {name}")
        user.password_hash = password_hash
        s.execute(delete(Session).where(Session.user_name == name))
        audit.record(
            s, actor_type="system", actor="command-line", action="auth.password_reset",
            subject_type="user", subject_id=name,
        )


def generate_password() -> str:
    return "-".join("".join(secrets.choice(_ALPHABET) for _ in range(4)) for _ in range(4))


def _choose_user(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    for number, name in enumerate(names, 1):
        print(f"  {number}. {name}")
    choice = input("Which account? Enter its number: ").strip()
    if not choice.isdecimal() or not 1 <= int(choice) <= len(names):
        raise ValueError("That is not one of the numbers listed")
    return names[int(choice) - 1]


def main(argv: list[str] | None = None) -> int:
    generate = "--generate" in (sys.argv[1:] if argv is None else argv)
    settings = get_settings()
    if settings.is_sqlite and not (settings.data_dir / "foreman.db").exists():
        print(f"No data found in {settings.data_dir.resolve()}. Run this from the backend folder.")
        return 1
    init_db(settings.database_url, migrate=settings.is_sqlite)
    with read_session() as s:
        names = list(s.scalars(select(User.name).order_by(User.created_at)))
    if not names:
        print("No accounts exist yet. Open the app to finish setup.")
        return 1
    try:
        name = _choose_user(names)
        if generate:
            password = generate_password()
            reset(name, password)
            print("\nPassword updated. Sign in with exactly these two values:\n")
            print(f"  Account name:  {name}")
            print(f"  Password:      {password}\n")
            return 0
        print(f"Setting a new password for: {name}")
        password = getpass.getpass("New password (hidden, at least 8 characters): ")
        if len(password) < MIN_LENGTH:
            raise ValueError("The password must be at least 8 characters")
        if password != getpass.getpass("Type it again: "):
            raise ValueError("The two passwords did not match")
        reset(name, password)
    except ValueError as exc:
        print(f"{exc}. Nothing was changed.")
        return 1
    print(f"Password updated. Sign in with the name {name}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
