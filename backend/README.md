# League Table backend

FastAPI service implementing `../openapi.yaml`, running on a seeded in-memory mock
database until a real data source replaces it.

From the repo root, `make install`, `make run` and `make test` do the following (`make help` lists them):

```sh
uv sync
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/api/docs
uv run pytest
```

The server also serves `../frontend`, so open http://localhost:8000 for the app. The page
talks to the API through `frontend/services/httpApi.js` on the same origin (so the session
cookie works) and signs in as the demo teacher automatically; sessions are in memory, so
the page signs in again after a restart. `frontend/services/api.js` and `mockSource.js`
remain as the in-browser mock used by the frontend test suite.

Demo sign-ins: `GET /api/demo/accounts` lists them (for example `teacher@demo.test` /
`demo-teacher-1`). Google sign-in is mocked: send the token `demo-google:<email>`.

## Layout

| Path | Role |
| --- | --- |
| `app/main.py` | `create_app(db, settings, clock)`, so tests and later adapters can inject their own |
| `app/datasource.py` | The read-only `DataSource` interface an adapter implements |
| `app/mock_db.py`, `app/toy_seed.py` | The mock database and the seeded demo class (same data as `frontend/services/mockSource.js`) |
| `app/scoring.py`, `app/ranking.py` | Pure scoring, tie-breaking, gaps and rank movement |
| `app/service.py` | 60 s cache, stale-snapshot fallback, data check, refresh cooldown |
| `app/routers/` | The endpoints |

To swap in a real database, write a class with the `DataSource` methods (plus an
account lookup and a settings store) and pass it to `create_app`.
