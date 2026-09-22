"""A database made before a column existed has to keep working."""
from sqlalchemy import inspect, text

from app.db import engine
from app.schema import sync_columns


def test_a_missing_column_is_added_back_with_its_default(client):
    # Drop a column the models declare, the way an older database would lack it.
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE applications DROP COLUMN email"))
    assert "email" not in {c["name"] for c in inspect(engine).get_columns("applications")}

    added = sync_columns(engine)
    assert "applications.email" in added
    assert "email" in {c["name"] for c in inspect(engine).get_columns("applications")}


def test_running_it_twice_adds_nothing_the_second_time(client):
    sync_columns(engine)
    assert sync_columns(engine) == []


def test_an_upgrade_gets_the_import_column_and_reads_null_as_typed(client):
    """The column the Google Sheet mirror filters on, arriving on a live database.

    A workspace that has been running since before the mirror existed has rows
    with nowhere to say where they came from. They get the column with NULL in
    it, which is exactly what a line somebody typed looks like — so an upgrade
    does not retrospectively class every application as an import and hide the
    lot.
    """
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE applications DROP COLUMN import_id"))
    assert "import_id" not in {
        c["name"] for c in inspect(engine).get_columns("applications")}

    assert "applications.import_id" in sync_columns(engine)

    with engine.begin() as connection:
        rows = connection.execute(text(
            "SELECT count(*) FROM applications WHERE import_id IS NOT NULL")).scalar()
    assert rows == 0
