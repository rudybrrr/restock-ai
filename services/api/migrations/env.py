from alembic import context
from sqlalchemy import create_engine, pool

from src.config import Settings
from src.database import metadata

if context.is_offline_mode():
    context.configure(
        url=Settings().database_url,
        target_metadata=metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(Settings().database_url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
