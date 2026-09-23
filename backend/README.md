# League Table backend

FastAPI service implementing `../openapi.yaml`, running on a seeded in-memory
toy data source until a real adapter replaces it. Read-write state (league
settings, commitments, risk settings, notes) lives in a SQLAlchemy-backed
`AppStore`; set `DATABASE_URL` to point it at a real database (defaults to an
in-memory SQLite DB, so a fresh, empty store every run).

From the repo root, `make install`, `make run` and `make test` do the following (`make help` lists them):

```sh
uv sync
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/docs
uv run pytest

# Persist to a SQLite file instead of the default in-memory DB:
DATABASE_URL="sqlite:///./league_table.db" uv run uvicorn app.main:create_app --factory --reload
```

Auth is a Bearer token on every endpoint (`bearerAuth`, JWT shape). The demo
accepts opaque tokens: `i1` (instructor `i1`), `s01` (student `s01` in `c1`),
`t03` (student `t03` in `c2`), plus `student:<sid>:<cid>` /
`instructor:<iid>` forms. Students only ever see their own raw score, factor
and hours; classmates' rows carry adjusted score + rank only.

The server also serves `../frontend`, so open http://localhost:8000 for the app.

## Layout

| Path | Role |
| --- | --- |
| `app/main.py` | `create_app(db, store, clock, ...)`, so tests and later adapters can inject their own |
| `app/datasource.py` | The read-only `DataSource` interface an adapter implements |
| `app/store.py` | The read-write `AppStore` interface and `SqlAlchemyStore`: league settings, baselines, weekly updates, risk settings/snapshots, notes |
| `app/db.py`, `app/db_models.py` | SQLAlchemy engine/session setup (`DATABASE_URL`-configured, database-agnostic) and the ORM tables `SqlAlchemyStore` uses |
| `app/auth.py` | Bearer caller parsing (`Caller`) + instructor guard |
| `app/mock_db.py`, `app/toy_seed.py` | The toy `DataSource` and seeded demo classes (2 × 24 students, 16 weeks) with commitments and notes, ported from `frontend/services/mockSource.js` |
| `app/scoring.py` | Pure scoring ported from `frontend/services/scoring.js`: weighted raw, hours resolution, factor/cap, windows, competition ranks, gaps |
| `app/risk.py` | Pure risk engine ported from `frontend/services/risk.js`: five signals, levels, digest diff |
| `app/service.py` | 60 s cache, stale-snapshot fallback, data check, refresh cooldown, ranking/risk helpers |
| `app/routers/` | `classes.py` (classes/bootstrap/explainer/settings), `ranking.py`, `risk.py` (commitments/digest/risk/notes/standing), `data.py` (refresh/status) |

To point the store at Postgres or another SQLAlchemy-supported database, just change
`DATABASE_URL` — `SqlAlchemyStore` doesn't assume SQLite. To swap in a real scores
source, write a class with the `DataSource` methods and pass it to `create_app`.
