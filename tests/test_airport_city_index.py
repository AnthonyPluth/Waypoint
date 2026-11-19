import unittest
from collections import Counter, defaultdict

from sqlalchemy import event, select

from waypoint.domain import airports, people, regions, stats  # noqa: F401
from waypoint.storage import db, schema
from tests.shared import DbCase

INDEX = "ix_airports_city_lower"
CITIES = {"london", "paris", "tokyo", "new york", "san jose", "cordoba", "no such city"}


def all_airports(conn):
    return [tuple(r) for r in conn.execute(select(schema.airports.c.city, schema.airports.c.country, schema.airports.c.zone,
                                                  schema.airports.c.latitude, schema.airports.c.longitude)).fetchall()]


class AirportCityIndexTests(DbCase):
    def captured(self, run):
        seen = []

        def record(_conn, _cursor, statement, parameters, _context, _many):
            if "lower(airports.city)" in statement:
                seen.append((statement, parameters))
        engine = db.engine(self.path)
        event.listen(engine, "before_cursor_execute", record)
        try:
            run()
        finally:
            event.remove(engine, "before_cursor_execute", record)
        return seen

    def test_the_database_has_the_expression_index(self):
        sql = ("SELECT indexname FROM pg_indexes WHERE tablename = 'airports' AND schemaname = current_schema()" if db.using_postgres()
               else "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'airports'")
        self.assertIn(INDEX, {r[0] for r in self.c.sa.exec_driver_sql(sql)})

    def test_every_lookup_of_airports_by_lowercased_city_uses_the_index_on_sqlite(self):
        queries = self.captured(lambda: (
            stats.countries_of(self.c, CITIES),
            stats.points_of(self.c, {"london": "GB", "paris": "FR"}),
            regions._city(self.c, "Paris"),
            airports.zone_for_place(self.c, "London", "GB"),
            airports.zone_for_place(self.c, "London", None)))
        self.assertGreaterEqual(len(queries), 5)
        for statement, parameters in queries if not db.using_postgres() else ():
            with self.subTest(statement=" ".join(statement.split())[:90]):
                plan = " ".join(str(r[3]) for r in self.c.sa.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters).fetchall())
                self.assertIn(INDEX, plan)
                self.assertNotIn("SCAN airports", plan)

    def test_countries_of_is_what_scanning_every_airport_in_python_gives_for_every_city_in_the_data(self):
        by_city: dict[str, Counter] = defaultdict(Counter)
        for city, country, *_ in all_airports(self.c):
            by_city[city.lower()][country] += 1
        expected = {}
        for city, counts in by_city.items():
            ranked = counts.most_common(2)
            if len(ranked) == 1 or ranked[0][1] > ranked[1][1]:
                expected[city] = ranked[0][0]
        self.assertGreater(len(expected), 5000)
        self.assertTrue(any(not c.isascii() for c in expected))
        self.assertEqual(stats.countries_of(self.c, set(by_city) | {"no such city"}), expected)
        self.assertEqual(stats.countries_of(self.c, {"london", "paris"}), {c: expected[c] for c in ("london", "paris")})
        self.assertEqual(stats.countries_of(self.c, set()), {})

    def test_a_city_in_any_case_finds_the_same_airports(self):
        lower = regions._city(self.c, "london")
        self.assertIsNotNone(lower)
        for spelled in ("London", "LONDON", "  lOnDoN ", "lonDON"):
            with self.subTest(spelled=spelled):
                self.assertEqual(regions._city(self.c, spelled), lower)
        zone = airports.zone_for_place(self.c, "london", "GB")
        for spelled in ("London", "LONDON", " lOnDoN"):
            with self.subTest(zone=spelled):
                self.assertEqual(airports.zone_for_place(self.c, spelled, "gb"), zone)
        self.assertEqual(zone, "Europe/London")
        self.assertIsNone(regions._city(self.c, "no such city"))


if __name__ == "__main__":
    unittest.main()
