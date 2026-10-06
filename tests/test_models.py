"""The ORM models (waypoint/storage/models.py) cover every table in waypoint/storage/schema.py and describe it truthfully."""
import typing
import unittest

from sqlalchemy.orm import configure_mappers

from waypoint.storage import models, schema

PY = {"TEXT": str, "FLOAT": float, "INTEGER": int, "BOOLEAN": bool, "BLOB": bytes}


class ModelTests(unittest.TestCase):
    def test_every_table_has_one_model(self):
        configure_mappers()
        mapped = [m.class_.__table__ for m in models.Base.registry.mappers]
        self.assertEqual(sorted(t.name for t in mapped), sorted(schema.metadata.tables))
        for t in mapped:
            self.assertIs(t, schema.metadata.tables[t.name], "a model must map schema.py's own Table, not a copy")

    def test_annotations_match_the_schema(self):
        for mapper in models.Base.registry.mappers:
            cls, table = mapper.class_, mapper.class_.__table__
            hints = typing.get_type_hints(cls, vars(models))
            for col in table.columns:
                with self.subTest(table=table.name, column=col.name):
                    self.assertIn(col.name, hints, "annotate every column")
                    want = PY[str(col.type)]
                    want = want if (col.primary_key or not col.nullable) else want | None
                    self.assertEqual(typing.get_args(hints[col.name])[0], want)


if __name__ == "__main__":
    unittest.main()
