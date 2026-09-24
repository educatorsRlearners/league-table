"""Integration tests against the real docker-compose stack.

Unlike the rest of the suite (in-process FastAPI app + in-memory SQLite via
`TestClient`), these boot the actual Docker image and a real Postgres over
real HTTP, to catch the class of bug the fast suite can't see: bad
`DATABASE_URL` wiring, Postgres-specific SQL/JSON behaviour, and data that
doesn't actually survive a restart. Slow and requires Docker, so they're
excluded from the default `pytest` run (see `[tool.pytest.ini_options]`) and
opt-in via `make test-integration` / `pytest -m integration`.

The stack runs under its own compose project name and remapped ports
(docker-compose.integration.yml) so it never touches a stack you already
have running with plain `docker compose up`.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Any

import httpx2 as httpx
import psycopg
import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[2]
PROJECT = "league_table_it"
COMPOSE_ARGS = [
    "-p", PROJECT,
    "-f", str(REPO_ROOT / "docker-compose.yml"),
    "-f", str(REPO_ROOT / "docker-compose.integration.yml"),
]
BASE_URL = "http://localhost:18000"
DB_DSN = "postgresql://league_table:league_table@localhost:15433/league_table"


def _compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *COMPOSE_ARGS, *args],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=180,
    )


def _wait_until_healthy(timeout: float = 90.0) -> None:
    deadline = time.time() + timeout
    last_error: Exception | str | None = None
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE_URL}/login/options", timeout=2.0)
            if r.status_code == 200:
                return
            last_error = f"status {r.status_code}: {r.text}"
        except Exception as exc:  # just retrying until the port is up
            last_error = exc
        time.sleep(1)
    raise RuntimeError(f"backend never became healthy at {BASE_URL}: {last_error}")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _row(table: str, **where: Any) -> dict | None:
    clause = " AND ".join(f"{k} = %s" for k in where)
    with psycopg.connect(DB_DSN) as conn, conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(f"SELECT * FROM {table} WHERE {clause}", list(where.values()))
        return cur.fetchone()


@pytest.fixture(scope="module")
def stack():
    up = _compose("up", "-d", "--build")
    assert up.returncode == 0, f"docker compose up failed:\n{up.stderr}"
    try:
        _wait_until_healthy()
        yield
    finally:
        down = _compose("down", "-v")
        assert down.returncode == 0, f"docker compose down failed:\n{down.stderr}"


def test_stack_serves_seeded_classes_over_http(stack):
    r = httpx.get(f"{BASE_URL}/login/options", timeout=5.0)
    assert r.status_code == 200
    classes = {c["id"] for c in r.json()["classes"]}
    assert classes == {"c1", "c2"}


def test_baseline_and_weekly_update_flow_persists_to_postgres(stack):
    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        # Student submits a baseline.
        r = client.put(
            "/me/commitments/baseline", params={"classId": "c1", "studentId": "s01"},
            json={"work": 10, "childcare": 2, "eldercare": 0}, headers=_auth("s01"),
        )
        assert r.status_code == 200, r.text
        baseline_id = r.json()["baseline"]["id"]

        # It landed in Postgres, not just the response body.
        row = _row("baselines", id=baseline_id)
        assert row is not None and row["status"] == "pending" and row["work_hours"] == 10

        # Instructor approves it.
        r = client.post(
            f"/classes/c1/commitments/baselines/{baseline_id}/decide",
            json={"decision": "approved", "effectiveFromWeek": 1}, headers=_auth("i1"),
        )
        assert r.status_code == 200, r.text
        assert _row("baselines", id=baseline_id)["status"] == "approved"

        # Student logs a weekly update for an editable week.
        editable = client.get(
            "/me/commitments", params={"classId": "c1", "studentId": "s01"}, headers=_auth("s01"),
        ).json()["editableWeeks"]
        week = editable[0]
        r = client.put(
            f"/me/commitments/weeks/{week}", params={"classId": "c1", "studentId": "s01"},
            json={"work": 12, "childcare": 3, "eldercare": 0}, headers=_auth("s01"),
        )
        assert r.status_code == 200, r.text
        update_id = next(u["id"] for u in r.json()["weeklyUpdates"] if u["week_number"] == week)

        assert _row("weekly_updates", id=update_id)["work_hours"] == 12


def test_league_settings_json_columns_round_trip(stack):
    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        patch = {"typeWeights": {"work": 2, "childcare": 1, "eldercare": 3}, "tieBreakers": ["homework"]}
        r = client.put("/classes/c2/settings", json=patch, headers=_auth("i1"))
        assert r.status_code == 200, r.text
        assert r.json()["typeWeights"] == patch["typeWeights"]

        # Read the JSON column back directly to make sure Postgres round-trips
        # the nested structure (not e.g. double-encoded as a JSON string).
        row = _row("league_settings", class_id="c2")
        assert row["type_weights"] == patch["typeWeights"]
        assert row["tie_breakers"] == patch["tieBreakers"]


def _active_baseline_id(client: httpx.Client) -> str:
    r = client.get("/me/commitments", params={"classId": "c1", "studentId": "s01"}, headers=_auth("s01"))
    assert r.status_code == 200
    return r.json()["activeBaseline"]["id"]


def test_data_survives_backend_container_restart(stack):
    # Proves persistence lives in Postgres, not backend process memory -
    # the whole point of this feature (the default DATABASE_URL is an
    # in-memory SQLite DB that would lose everything here).
    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        before_id = _active_baseline_id(client)

    restart = _compose("restart", "backend")
    assert restart.returncode == 0, restart.stderr
    _wait_until_healthy()

    with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
        assert _active_baseline_id(client) == before_id


def test_data_survives_full_stack_recreation(stack):
    # `stop`/`up` (not `down -v`) recreates both containers against the same
    # named volume, exercising that the Postgres data directory - not just
    # the running process - is what's durable.
    before = _row("league_settings", class_id="c2")
    assert before is not None

    stop = _compose("stop")
    assert stop.returncode == 0, stop.stderr
    up = _compose("up", "-d")
    assert up.returncode == 0, up.stderr
    _wait_until_healthy()

    after = _row("league_settings", class_id="c2")
    assert after == before
