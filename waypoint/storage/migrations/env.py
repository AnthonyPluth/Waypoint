from alembic import context
from alembic.operations import ops

from waypoint.storage import db, schema

config = context.config
target_metadata = schema.metadata


def same_type(_ctx, _db_col, _model_col, db_type, model_type):
    kinds = {"REAL": "float", "FLOAT": "float", "DOUBLE_PRECISION": "float", "DOUBLE": "float",
             "BIGINT": "int", "INTEGER": "int", "TEXT": "text"}
    a, b = kinds.get(type(db_type).__name__.upper()), kinds.get(type(model_type).__name__.upper())
    return None if a is None or b is None else a != b


def skip_pk_nullability(_ctx, _revision, directives) -> None:
    for script in directives:
        for group in script.upgrade_ops.ops:
            if isinstance(group, ops.ModifyTableOps):
                group.ops = [o for o in group.ops if not (isinstance(o, ops.AlterColumnOp) and o.modify_nullable is not None
                                                          and o.modify_type is None and o.column_name in
                                                          {c.name for c in target_metadata.tables[group.table_name].primary_key})]
        script.upgrade_ops.ops = [g for g in script.upgrade_ops.ops if not (isinstance(g, ops.ModifyTableOps) and not g.ops)]


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=same_type,
                      process_revision_directives=skip_pk_nullability,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


connection = config.attributes.get("connection")
if connection is not None:
    run(connection)
elif context.is_offline_mode():
    context.configure(url=db.engine_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with db.engine().connect() as connection:
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            connection.commit()
        run(connection)
        connection.commit()
