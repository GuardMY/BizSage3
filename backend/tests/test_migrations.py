"""Regression coverage for migrations that must tolerate fresh SQLite databases."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def _citation_migration():
    path = Path(__file__).parents[1] / "alembic" / "versions" / "20260716_02_message_citations.py"
    spec = spec_from_file_location("message_citations_migration", path)
    assert spec and spec.loader
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(connection, migration) -> None:
    migration_context = MigrationContext.configure(connection)
    with Operations.context(migration_context):
        migration.upgrade()


def test_message_citations_migration_is_safe_for_empty_database():
    migration = _citation_migration()
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        _run_upgrade(connection, migration)
        assert not sa.inspect(connection).has_table("messages")


def test_message_citations_migration_adds_column_once_when_table_exists():
    migration = _citation_migration()
    engine = sa.create_engine("sqlite://")

    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE messages (id VARCHAR PRIMARY KEY)"))
        _run_upgrade(connection, migration)
        _run_upgrade(connection, migration)

        columns = {column["name"] for column in sa.inspect(connection).get_columns("messages")}
        assert columns == {"id", "citations"}
