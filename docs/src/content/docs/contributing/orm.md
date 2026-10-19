---
title: Queries with SQLAlchemy
description: Writing queries as SQLAlchemy statements over the ORM models.
sidebar:
  order: 2
---

Waypoint’s database code, tests included, builds its queries as SQLAlchemy statements from the ORM models in `waypoint/storage/models.py`. `Connection.execute()` doesn’t take SQL text (it raises `TypeError`). This guide covers what to use and what to watch, with examples from `waypoint/storage/db.py`, `waypoint/storage/backup.py` and the API handlers in `waypoint/server/api/`.

Where the models are still few (users, sessions, settings), the examples show the same patterns on a hypothetical `trips` table and `segments` (a trip’s flights, hotels and cars). They aren’t in the schema yet.

When you rewrite an existing query, the rule is **no change in behaviour**: same rows, same order, same dict keys in API responses, same commit points.

## The pieces

| What | Where | Notes |
|---|---|---|
| Schema (the one source of truth) | `waypoint/storage/schema.py` | Core `Table`s; Alembic migrations keep the database matching it. |
| Models | `waypoint/storage/models.py` | One class per table, mapping schema.py’s own `Table` (`__table__ = schema.settings`), so no migration. `User`, `AuthSession`, `AuthPending`, `Setting`, and more as the travel features land. |
| Connection | `db.connect()`, `db.session()` | `conn.execute()` takes a statement; SQL text raises `TypeError`. `conn.sa` is the SQLAlchemy connection underneath. |
| ORM Session | `conn.orm` | A `sqlalchemy.orm.Session` on the same connection and transaction. |
| Helpers | `waypoint/storage/db.py` | `upsert`, `insert_ignore`, `dialect_insert`, `rows`, `as_dict`, `Result.scalar()/scalars()` |
| Guard | `tests/test_orm_guard.py` | Fails on SQL text passed to `execute()`, or a `text()` not listed in `RAW_SQL`, anywhere in `waypoint/` or `tests/`. |

## Two ways to run a statement

**1. `conn.execute(statement)`: the default.** Build a Core-style statement from the model attributes and run it on the connection. The result is a `db.Result`: rows read by name or position (`row["id"]`, `row[0]`, `dict(row)`), `fetchone()`, `fetchall()`, iteration, `rowcount`, `lastrowid`, plus `scalar()` and `scalars()`. `db.rows(...)` turns it into a list of dicts.

**2. `conn.orm`: when objects help.** Load an object, change its attributes, add new ones: `conn.orm.get(Trip, 3)`, `conn.orm.add(Trip(...))`, `conn.orm.scalars(select(Segment).where(...)).all()`. Use it for edit handlers that look a row up, check it exists and change a few columns. Don’t use it to build API responses from many rows (use 1 and `db.rows()`), or in loops that would lazy-load per row.

Both share one connection and one transaction:

- Pending ORM changes (`add()`, attribute changes) are written (“flushed”) before any `conn.execute()` runs, so statements always see them. They are also written at `conn.commit()`.
- After an `UPDATE`, `DELETE` or `INSERT` through `conn.execute()`, objects the Session had loaded are expired and re-read when next used, so they’re never stale.
- `conn.commit()` commits both; `conn.rollback()` rolls back both; `db.session()` commits on success and rolls back on an exception. **Don’t call `conn.orm.commit()` or `conn.sa.commit()` yourself**: always `conn.commit()`.
- Objects stay readable after a commit (`expire_on_commit=False`).
- There is one Connection (and so one Session) per request or sync, never shared between threads.

### Commit points and network calls

Some code commits before a slow network request so SQLite’s write lock isn’t held through it: `conn.commit()`, then a call to an outside service such as Gmail, then carry on with the same `conn`. After `conn.commit()`, both the connection and `conn.orm` start a new transaction on their next use.

- Keep every existing `conn.commit()` where it is.
- When you use `conn.orm`, changes are written lazily. A commit before a network call includes them (commit flushes), but a read through another connection won’t see them until then.

## Reads

Imports: `from sqlalchemy import select, func, ...` and `from .models import User, ...` (from `waypoint/server/api/*`: `from ...storage.models import ...`).

### Columns, filters, order

A hypothetical query for a trip’s flights, soonest first:

```python
flights = db.rows(conn.execute(
    select(Segment.id, Segment.flight_number, Segment.departs_at)
    .where(Segment.trip_id == trip_id, Segment.kind == "flight").order_by(Segment.departs_at)))
```

- Several conditions: `.where(a, b)`; or: `or_(a, b)`; not: `~x` or `not_(x)`.
- Null checks: `X.col.is_(None)` and `.is_not(None)`, never `== None` (ruff flags it anyway).
- `.in_([...])` (an empty list is fine: it’s false); `.not_in(...)`; a subquery: `.in_(select(Trip.id).where(...))`.
- `.order_by(A.a, A.b.desc())`, `.limit(n)`, `.offset(n)`.
- A computed column’s name is `.label("name")`. The label is the dict key in the result.
- Every model attribute is named as its column.

### Every column

`select(Model)` through `conn.execute()` gives every column, named as the table’s columns, in schema.py’s order:

```python
out = db.rows(conn.execute(select(Trip).order_by(Trip.starts_on, Trip.name)))
```

To leave out a big column (a stored `raw` blob), select the rest instead of loading it:

```python
SEGMENT_COLUMNS = [c for c in Segment.__table__.c if c.key != "raw"]   # a segment, less its source text
segments = db.rows(conn.execute(select(*SEGMENT_COLUMNS).order_by(Segment.departs_at, Segment.id)))
```

### Joins and aliases

```python
select(Segment.id, Trip.name).join(Trip, Trip.id == Segment.trip_id)       # INNER JOIN
select(...).outerjoin(Trip, Trip.id == Segment.trip_id)                  # LEFT JOIN
select(Trip.id).join(Trip.segments)                                      # via a relationship
```

- A table in two roles (a user as the traveller and as the person who booked): `booker = aliased(User)` (`from sqlalchemy.orm import aliased`), then `booker.id`, `booker.name`.
- A relationship loaded on objects is `lazy="raise"`: load it explicitly with `.options(selectinload(Trip.segments))`, or you get an error rather than one query per row.

### Aggregates and GROUP BY

```python
select(Segment.kind, func.count().label("n"))
    .where(Segment.departs_at >= start).group_by(Segment.kind).having(func.count() > 1)
```

`func.max/min/avg/coalesce/lower/upper/abs/round/length/substr` render as the same SQL functions. For one number: `conn.execute(select(func.count()).select_from(Trip)).scalar()`.

To `GROUP BY` or `ORDER BY` a computed column, label it once and reuse the label object:

```python
name = func.coalesce(User.display_name, User.email).label("name")
select(User.id, name).where(User.disabled == 0).order_by(name)
```

### Strings, dates and `CASE`

- **Substring position:** `db.instr(haystack, needle) > 0` (SQLite `instr`, Postgres `strpos`). It is exact and case-sensitive, with no wildcards; wrap both sides in `func.lower()` for a case-insensitive match.
- **Matching text:** `.like(value)` treats `%` and `_` in the value as wildcards. To match literally, use `.contains(text, autoescape=True)` or `.startswith(..., autoescape=True)`. A search box does `func.lower(col).contains(text.lower(), autoescape=True)`.
- **Lower-casing:** `func.lower()` lowers every letter on both databases (“CAFÉ” is “café”). SQLite’s own only lowers ASCII, so `db.py` puts Python’s `str.lower` in its place on every SQLite connection. It doesn’t case-fold (ß stays ß, as on Postgres).
- **Concatenation:** `A.a + B.b` on text columns, or `func.coalesce(...) + " (" + A.owner + ")"`.
- **`CASE`:** `case((c, x), else_=y)` for `CASE WHEN c THEN x ELSE y END`.
- **Dates** are ISO text in this schema: compare them as strings (`Segment.departs_at >= start.isoformat()`). `schema.now_text()` is the portable “now” as text.
- **A constant in the select list** that must stay SQL, not a parameter (inside a `UNION`, say): `literal_column("'split'", Text)`.

## Writes

### Insert

A hypothetical trip:

```python
cur = conn.execute(insert(Trip).values(name=fields.pop("name"), starts_on=starts_on, source=body.get("source") or "manual"))
trip_id = cur.lastrowid
```

`lastrowid` is the new row’s primary key on both databases (from SQLAlchemy’s `inserted_primary_key`). Columns you leave out get their server default.

For many rows, pass a list: `conn.execute(insert(Segment), [{"trip_id": trip_id, "kind": k} for k in kinds])`. Every dict must have the same keys. An empty list does nothing.

### Update and delete

```python
conn.execute(update(Trip).where(Trip.id == trip_id).values(**fields))
conn.execute(delete(Segment).where(Segment.trip_id == trip_id))
```

- `.values(**fields)` is safe only because `fields`’ keys are column names the code chose. Never pass keys from a request body unchecked: SQLAlchemy rejects unknown columns, but a known one you didn’t mean to allow would be written.
- `rowcount` gives the rows affected.
- Expressions work: `.values(passengers=Trip.passengers + 1)`.

### Upserts (`ON CONFLICT`)

`db.upsert()` builds `INSERT ... ON CONFLICT ... DO UPDATE` with the SQLite or Postgres `insert()` to match the connection (`waypoint/storage/db.py`):

```python
db.upsert(conn, Setting, {"key": key, "value": value}, key=["key"])
```

- `update=None` (the default) updates every column given, except the key, from `excluded`. To update only some, pass `update=["a", "b"]`.
- For anything else in the SET clause: `update=lambda ex: {"value": func.coalesce(ex.value, Setting.value)}` (`ex` is `excluded`; the model’s attributes are the existing row).
- `update=[]` gives `ON CONFLICT DO NOTHING`, as does `db.insert_ignore(conn, Model, values, key=[...])` (`key=None`: any unique constraint). Don’t use SQLite’s `INSERT OR IGNORE`: it doesn’t run on Postgres.
- A list of dicts upserts many rows in one call.
- For something else (`ON CONFLICT ... DO UPDATE ... WHERE`), use `stmt = db.dialect_insert(conn, Model).values(...)`, then SQLAlchemy’s own `stmt.on_conflict_do_update(index_elements=[...], set_={...}, where=...)`. Both dialects accept the same arguments.

## Using the ORM Session

A hypothetical edit handler:

```python
trip = conn.orm.get(Trip, trip_id)
if trip is None:
    raise ApiError("Trip not found", 404)
for k, v in fields.items():
    setattr(trip, k, v)
trip.notes = None
```

`conn.orm.add(Trip(**fields))` adds a new row. Notes:

- Changes are written at the next `conn.execute()`, `conn.orm` query or `conn.commit()`. If you need a generated id now, `conn.orm.flush()` then read `obj.id`.
- Attributes not set on a new object are left out of the INSERT, so server defaults apply.
- `conn.orm.get()` loads every column (including big `raw` JSON). For a mere existence check use `conn.execute(select(Model.id).where(...)).fetchone()`.
- To return an object as a dict: `db.as_dict(obj)` (columns in table order). For lists, prefer `db.rows(conn.execute(select(...)))`.
- To delete, prefer `conn.execute(delete(Model).where(...))`. The relationships are view-only, so nothing cascades.

## API responses

Handlers return dicts that become JSON; the frontend reads them by key.

- `db.rows(conn.execute(stmt))` gives a list of dicts.
- Dict keys are the selected columns’ names or labels. `select(Model.col)` is keyed `col`; a computed column needs `.label()`. When you change a query, check every key the frontend reads survived.
- SQLite gives back the types it stored.
- Keep every `ORDER BY`, and don’t rely on an order the query doesn’t ask for.
- When you rewrite a query, compare its output before and after on the same data. Run the previous version (from `git show HEAD:waypoint/x.py`, loaded as a module) and the new one on a demo database (`demo.seed(conn)`) plus the edge cases the module handles, and compare `json.dumps(...)` of both (key order included).

## When SQLAlchemy can’t express it: `text()`

Almost everything can be written with SQLAlchemy: window functions with `func.row_number().over(...)`, CTEs with `.cte()`, `UNION` with `union_all()`, correlated subqueries with `.scalar_subquery()`, `EXISTS` with `.exists()`.

If something genuinely can’t, use `sqlalchemy.text()` with named parameters, add the module and the statement’s text to `RAW_SQL` in `tests/test_orm_guard.py`, and say why in the commit message:

```python
conn.execute(text("... WHERE x = :x"), {"x": x})
```

- The guard counts every `text()` call whose statement `RAW_SQL` doesn’t list for that module, so a new one in the same file still fails.
- The SQL must still run on both databases.
- Dynamic table names (`waypoint/storage/backup.py`) aren’t a reason: use `schema.metadata.tables[name]` and `insert(table)`.

Some SQL is not a statement, on purpose:

- Alembic migrations (`waypoint/storage/migrations`, with `op.execute`).
- The driver-level setup in `db.py`’s engine functions (`dbapi_conn.execute("PRAGMA ...")`) and its schema upgrade (`exec_driver_sql` DDL).
- Tests that set up an older schema, a column the models don’t have, or a SQLite setting. They run SQL with `exec_driver_sql` on a SQLAlchemy connection: `conn.sa.exec_driver_sql(...)` for a `db.Connection`, and a `PRAGMA` only `if not db.using_postgres()`.

## SQLite and Postgres

Tests run on SQLite by default; CI also runs everything on Postgres 16 (`DATABASE_URL`, see `.github/workflows/docker.yml`). To run it locally, start Postgres, then `DATABASE_URL=postgresql://user:pass@localhost/db python -m unittest discover tests` (each test gets its own schema). [Development](/Waypoint/contributing/development/) has a throwaway setup.

- Statements are compiled for the connection’s database, so portable constructs are portable automatically. Avoid a `func.<something>` that exists on only one:
  - `func.instr` → `db.instr`.
  - `func.strftime`, `func.datetime`, `func.julianday`, `func.group_concat` and `func.ifnull` are SQLite-only. Use `func.coalesce`, string comparison of ISO dates, or do it in Python.
  - Import `sqlite_*` and `postgresql_*` constructs only through `db.dialect_insert`.
- On Postgres, SQLAlchemy sends parameters with a cast to the column’s type (`%(x)s::VARCHAR`, `::INTEGER`), and Waypoint’s Postgres setup sends Python values as untyped text. A value that doesn’t fit the column’s type (a string of letters, or `1.5`, for an integer column) fails on Postgres where SQLite would have stored it. Pass values of the column’s type (`int(...)` for 0/1 flags).
- `func.round(x, 2)` on a float column fails on Postgres (it needs numeric): round in Python, as the code mostly does.
- `LIMIT -1` is SQLite-only (see `oidc.py`): use `.offset(n)` alone.
- `GROUP BY`: Postgres requires every selected non-aggregate column to be grouped (SQLite doesn’t), so a query that relies on SQLite picking “some row” per group fails on Postgres.
- Booleans are 0/1 integers in this schema: compare with `== 1` or `== 0`, not `.is_(True)`.

## Testing a change

1. `python -W ignore -m unittest discover tests`: all pass. The module’s own tests should cover the queries you changed; add a test for any query path that isn’t covered before you change it.
2. When rewriting a query, compare its output before and after (see API responses).
3. `ruff check .` and `mypy`.
4. `python -m unittest tests.test_orm_guard`: it fails on SQL text anywhere in `waypoint/` or `tests/`.
5. Try the pages it feeds (`python run.py demo`, then `python run.py`).

## Checklist

- [ ] Every `conn.execute(...)` runs a statement (or a `text()` listed in `RAW_SQL`).
- [ ] Rewritten queries keep the same rows, order, dict keys and types, and the same `lastrowid` and `rowcount` use.
- [ ] Every `conn.commit()` kept where it was; no `conn.orm.commit()`.
- [ ] No per-row queries (use joins, `in_()` or `selectinload`).
- [ ] A fragment two queries share lives in one helper, not in copies.
- [ ] Nothing SQLite- or Postgres-only.
- [ ] Tests, ruff and the guard pass.
