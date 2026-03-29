from __future__ import with_statement

from logging.config import fileConfig

from alembic import context
from flask import current_app

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def get_engine():
    db_ext = current_app.extensions["migrate"].db
    try:
        return db_ext.engine
    except AttributeError:
        return db_ext.get_engine()


def get_engine_url():
    engine = get_engine()
    try:
        return engine.url.render_as_string(hide_password=False).replace("%", "%%")
    except AttributeError:
        return str(engine.url).replace("%", "%%")


def get_metadata():
    db_ext = current_app.extensions["migrate"].db
    if hasattr(db_ext, "metadatas"):
        return db_ext.metadatas[None]
    return db_ext.metadata


config.set_main_option("sqlalchemy.url", get_engine_url())
target_metadata = get_metadata()


def process_revision_directives(migration_context, revision, directives):
    if getattr(config.cmd_opts, "autogenerate", False):
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            print("No changes in schema detected.")


def run_migrations_offline():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    conf_args = dict(current_app.extensions["migrate"].configure_args)
    conf_args.setdefault("compare_type", True)
    conf_args.setdefault("render_as_batch", True)
    connectable = get_engine()

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
            **conf_args,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
