"""Add whatever columns a later version of the models introduced.

`create_all` makes tables that do not exist and then stops — it will not touch
one that does. So a database made before a column was added keeps working right
up to the first query that names the new column, and then fails on every
request. This runs at boot, reads what is really there, and adds what is not.

Only ever ADDs, and only with a default. It never drops, renames or retypes
anything: a migration that can lose data is not something that should run
unattended on somebody's laptop at start-up.
"""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from .db import Base


def _sql_type(column) -> str:
    """The column's type as this dialect spells it, plus its default.

    SQLAlchemy applies Python-side defaults on insert, so an existing row would
    otherwise be handed NULL in a NOT NULL column. The literal default is put
    in the DDL instead, which fills the rows already there.
    """
    type_sql = column.type.compile()
    default = ""
    if column.default is not None and not column.default.is_callable:
        value = column.default.arg
        default = (f" DEFAULT '{value}'" if isinstance(value, str)
                   else f" DEFAULT {int(value)}" if isinstance(value, bool)
                   else f" DEFAULT {value}")
    return type_sql + default


def sync_columns(engine: Engine) -> list[str]:
    """Add every mapped column the database is missing. Returns what it added.

    Reflection and DDL run on ONE connection, on purpose. Reading the columns
    through a second connection means reading them from outside the transaction
    the ALTERs are running in, and what that sees partway through is up to the
    database — on SQLite it is the state from before the transaction opened,
    which is how you end up adding a column you have already added.
    """
    added: list[str] = []

    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        for table in Base.metadata.sorted_tables:
            if table.name not in tables:
                continue  # create_all will have just made it, in full
            present = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in present:
                    continue
                connection.execute(text(
                    f"ALTER TABLE {table.name} "
                    f"ADD COLUMN {column.name} {_sql_type(column)}"
                ))
                added.append(f"{table.name}.{column.name}")
    return added
