from alembic import context
from sqlalchemy import create_engine, pool

from app import models  # noqa: F401  (registers tables)
from app.db import Base

url = context.config.get_main_option("sqlalchemy.url")
engine = create_engine(url, poolclass=pool.NullPool)

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()
