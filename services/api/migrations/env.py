import re

from alembic import context
from sqlalchemy import create_engine, pool, text

from src.config import Settings
from src.database import metadata

_ACTIONABLE_PREDICATE = "status in ('pending_approval','approved')"


def _normalise_index_expression(value: str | None) -> str:
    """Normalise PostgreSQL's reflected spelling of the approved predicate."""
    if value is None:
        return ""
    result = value.lower()
    values = re.findall(r"'([^']+)'", result)
    if (
        "status" not in result
        or not ("any" in result or " in " in result)
        or values != ["pending_approval", "approved"]
    ):
        return ""
    return _ACTIONABLE_PREDICATE


def _is_canonical_actionable_index(connection, name: str) -> bool:
    """Fail closed unless PostgreSQL proves the exact migration-owned index."""
    row = connection.execute(
        text(
            """
            SELECT i.indisunique, pg_get_expr(i.indexprs, i.indrelid),
                   pg_get_expr(i.indpred, i.indrelid)
            FROM pg_index i
            JOIN pg_class idx ON idx.oid = i.indexrelid
            JOIN pg_class tbl ON tbl.oid = i.indrelid
            WHERE tbl.relname = 'plan_versions' AND idx.relname = :name
            """
        ),
        {"name": name},
    ).one_or_none()
    if row is None or not row.indisunique:
        return False
    expected = _normalise_index_expression(_ACTIONABLE_PREDICATE)
    return (
        _normalise_index_expression(row[1]) == expected
        and _normalise_index_expression(row[2]) == expected
    )


def _include_object(connection):
    def include_object(object_, name, type_, reflected, compare_to):
        if not (
            type_ == "index"
            and reflected
            and name == "one_actionable_plan"
            and getattr(object_.table, "name", None) == "plan_versions"
        ):
            return True
        return not _is_canonical_actionable_index(connection, name)

    return include_object

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
        context.configure(
            connection=connection,
            target_metadata=metadata,
            include_object=_include_object(connection),
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
