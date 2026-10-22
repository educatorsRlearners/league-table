"""FAULT_COMMITMENT_ERRORS: demo-only switch that fails the commitment submission."""

import pytest
from fastapi.testclient import TestClient

from tests.test_change_log import client, hours, params, put_week

VAR = "FAULT_COMMITMENT_ERRORS"


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "2"])
def test_off_values_leave_behaviour_unchanged(app, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(VAR, raising=False)
    else:
        monkeypatch.setenv(VAR, value)
    assert put_week(client(app, "s10"), "s10", work=10).status_code == 200


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "True"])
def test_on_values_return_500_and_write_nothing(app, monkeypatch, value):
    s10 = client(app, "s10")
    before = s10.get("/me/commitments", params=params("s10")).json()
    monkeypatch.setenv(VAR, value)
    faulty = TestClient(app, raise_server_exceptions=False)
    faulty.headers.update({"Authorization": "Bearer s10"})
    r = faulty.put("/me/commitments/weeks/16", params=params("s10"), json=hours(work=33))
    assert r.status_code == 500
    assert set(r.json()) == {"message"}
    monkeypatch.delenv(VAR)
    assert s10.get("/me/commitments", params=params("s10")).json() == before


def test_switch_is_read_per_request_and_affects_no_other_route(app, monkeypatch):
    s10 = client(app, "s10")
    monkeypatch.setenv(VAR, "1")
    assert s10.get("/me/commitments", params=params("s10")).status_code == 200
    assert s10.put("/me/commitments/baseline", params=params("s10"), json=hours(work=5)).status_code == 200
    monkeypatch.delenv(VAR)
    assert put_week(s10, "s10", work=10).status_code == 200


def test_fault_message_names_switch_without_student_data(monkeypatch):
    from app.faults import CommitmentFault, maybe_fail_commitment

    monkeypatch.setenv(VAR, "1")
    with pytest.raises(CommitmentFault) as exc:
        maybe_fail_commitment()
    assert VAR in str(exc.value)
