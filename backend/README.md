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
cookie works). Sessions are in memory, so the page returns to sign-in after a restart.
`frontend/services/api.js` and `mockSource.js` remain as the in-browser mock used by the
frontend test suite; they do not follow the adjustment rules.

Sign-in is by access code: each student has a personal code (only its hash is stored) and the
instructor has one passcode. Demo data has a default passcode, `demo-instructor`; anything else
needs `INSTRUCTOR_PASSCODE` in the environment or the app will not start. `GET /api/demo/accounts`
lists the demo codes (for example `demo-amara`).

## Layout

| Path | Role |
| --- | --- |
| `app/main.py` | `create_app(db, store, clock, ...)`, so tests and later adapters can inject their own |
| `app/datasource.py` | The read-only `DataSource` interface an adapter implements |
| `app/store.py` | The read-write `AppStore` interface and `MemoryStore`: accounts, baselines, weekly updates, log, settings |
| `app/identity.py` | The `IdentityProvider` interface and access-code sign-in |
| `app/mock_db.py`, `app/toy_seed.py` | The toy `DataSource` and the seeded demo class (24 students, 16 weeks) with its commitments |
| `app/scoring.py`, `app/ranking.py` | Pure criterion scoring, weekly adjustment, windows, tie-breaking, gaps and rank movement |
| `app/commitments.py` | Pure rules: hour limits, the factor and cap, which baseline counts, the edit window |
| `app/explainer.py` | The formula, parameters and worked examples every student can read |
| `app/service.py` | 60 s cache, stale-snapshot fallback, data check, refresh cooldown |
| `app/routers/` | The endpoints |

To swap in a real database, write a class with the `DataSource` methods and another with the
`AppStore` methods, and pass them to `create_app`. `tests/test_store_contract.py` is the suite a
new store must pass.
