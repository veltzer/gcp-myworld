"""
What Alembic runs for every command: the migrations are applied to the
database myworld.models.database_url() names (DATABASE_URL, or the local
sqlite file), and compared with the tables the models declare.
"""

import logging.config

from alembic import context
from sqlalchemy import create_engine

from myworld.models import Base, database_url

if context.config.config_file_name is not None:
    logging.config.fileConfig(context.config.config_file_name)


def run() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            # sqlite cannot alter a table in place: a change there copies the table
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run()
