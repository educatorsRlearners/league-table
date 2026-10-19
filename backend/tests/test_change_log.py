"""Commitment change log (issue #43): logging, atomicity, reversal and privacy."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

LOG = "/classes/c1/commitments/change-log"


def hours(work=0, childcare=0, eldercare=0):
    return {"work": work, "childcare": childcare, "eldercare": eldercare}


def log_hours(work=0, childcare=0, eldercare=0):
    return {"work_hours": work, "childcare_hours": childcare, "eldercare_hours": eldercare}


def client(app, token):
    c = TestClient(app)
    c.headers.update({"Authorization": f"Bearer {token}"})
    return c


def params(sid):
    return {"classId": "c1", "studentId": sid}


def log(instructor, **q):
    r = instructor.get(LOG, params=q)
    assert r.status_code == 200
    return r.json()


def put_baseline(student, sid, **h):
    r = student.put("/me/commitments/baseline", params=params(sid), json=hours(**h))
    assert r.status_code == 200
    return r.json()["baseline"]["id"]


def decide(instructor, baseline_id, body):
    return instructor.post(f"/classes/c1/commitments/baselines/{baseline_id}/decide", json=body)


def put_week(student, sid, week=16, **h):
    return student.put(f"/me/commitments/weeks/{week}", params=params(sid), json=hours(**h))


def week16(student, sid):
    comm = student.get("/me/commitments", params=params(sid)).json()
    return next(w for w in comm["byWeek"] if w["week_number"] == 16), comm


@pytest.fixture
def s10(app):
    return client(app, "s10")


def approved_baseline(app, instructor, sid="s10", work=10):
    student = client(app, sid)
    bid = put_baseline(student, sid, work=work)
    assert decide(instructor, bid, {"decision": "approved", "effectiveFromWeek": 1}).status_code == 200
    return student


def test_fresh_store_has_empty_log(instructor):
    r = instructor.get(LOG)
    assert r.status_code == 200 and r.json() == []


def test_baseline_submit_approve_reject_entries(app, instructor, clock, s10):
    assert log(instructor) == []
    bid = put_baseline(s10, "s10", work=10, childcare=2)
    [entry] = log(instructor)
    assert entry["action"] == "baseline.submit"
    assert entry["actor_id"] == "s10" and entry["student_id"] == "s10"
    assert entry["week_id"] is None and entry["old_values"] is None
    assert entry["new_values"] == log_hours(10, 2, 0)
    assert entry["id"]
    assert entry["at"] == datetime.fromtimestamp(clock(), tz=UTC).isoformat()

    decide(instructor, bid, {"decision": "approved", "effectiveFromWeek": 3})
    newest = log(instructor)[0]
    assert newest["action"] == "baseline.approve" and newest["actor_id"] == "i1"
    assert newest["student_id"] == "s10" and newest["week_id"] is None
    assert newest["new_values"]["effective_from_week"] == 3
    assert newest["new_values"]["work_hours"] == 10

    s13 = client(app, "s13")
    bid2 = put_baseline(s13, "s13", work=5)
    decide(instructor, bid2, {"decision": "rejected"})
    newest = log(instructor)[0]
    assert newest["action"] == "baseline.reject" and newest["actor_id"] == "i1"
    assert newest["student_id"] == "s13"
    assert len(log(instructor)) == 4


def test_resubmitted_baseline_records_previous_hours(s10, instructor):
    put_baseline(s10, "s10", work=10)
    put_baseline(s10, "s10", work=15)
    newest = log(instructor)[0]
    assert newest["old_values"] == log_hours(10, 0, 0) and newest["new_values"] == log_hours(15, 0, 0)


def test_weekly_set_old_values_and_chain(app, instructor):
    # no baseline applies: old_values is null
    s13 = client(app, "s13")
    assert put_week(s13, "s13", work=4).status_code == 200
    entry = log(instructor, studentId="s13")[0]
    assert entry["action"] == "weekly.set" and entry["old_values"] is None
    assert entry["new_values"] == log_hours(4, 0, 0) and entry["week_id"]
    assert entry["actor_id"] == "s13"

    s10 = approved_baseline(app, instructor)
    put_week(s10, "s10", work=20)
    put_week(s10, "s10", work=30)
    second, first = log(instructor, studentId="s10")[:2]
    assert first["action"] == second["action"] == "weekly.set"
    assert first["old_values"] == log_hours(10, 0, 0)  # baseline in effect
    assert first["new_values"] == log_hours(20, 0, 0)
    assert second["old_values"] == first["new_values"]
    assert second["new_values"] == log_hours(30, 0, 0)


def test_reverse_entry_and_restores_earlier_weekly_value(app, instructor):
    s10 = approved_baseline(app, instructor)
    put_week(s10, "s10", work=20)
    put_week(s10, "s10", work=30)
    comm = s10.get("/me/commitments", params=params("s10")).json()
    current = next(u for u in comm["weeklyUpdates"] if u["week_number"] == 16)
    assert current["work_hours"] == 30

    assert instructor.post(f"/classes/c1/commitments/weekly-updates/{current['id']}/reverse").status_code == 200
    entry = log(instructor)[0]
    assert entry["action"] == "weekly.reverse" and entry["actor_id"] == "i1"
    assert entry["student_id"] == "s10" and entry["week_id"]
    assert entry["old_values"] == log_hours(30, 0, 0)
    assert entry["new_values"] == log_hours(20, 0, 0)

    wk, comm = week16(s10, "s10")
    assert wk["hours"] == hours(20, 0, 0) and wk["source"] == "weekly"
    live = [u for u in comm["weeklyUpdates"] if u["week_number"] == 16 and u["reversed_at"] is None]
    assert [u["work_hours"] for u in live] == [20]


def test_reversing_a_superseded_update_is_409_and_not_logged(app, instructor):
    s10 = approved_baseline(app, instructor)
    put_week(s10, "s10", work=20)
    comm = s10.get("/me/commitments", params=params("s10")).json()
    first = next(u for u in comm["weeklyUpdates"] if u["week_number"] == 16)
    put_week(s10, "s10", work=30)  # replaces the first update
    before = log(instructor)

    resp = instructor.post(f"/classes/c1/commitments/weekly-updates/{first['id']}/reverse")
    assert resp.status_code == 409
    assert "replaced by a later edit" in resp.text
    assert log(instructor) == before
    wk, _ = week16(s10, "s10")
    assert wk["hours"] == hours(30, 0, 0)


def test_reverse_falls_back_to_baseline_and_ranking_is_restored(app, instructor):
    s10 = approved_baseline(app, instructor)
    ranking = {"week": "w16"}
    before = instructor.get("/classes/c1/ranking", params=ranking).json()
    put_week(s10, "s10", work=30)
    during = instructor.get("/classes/c1/ranking", params=ranking).json()
    assert during != before
    upd = next(u for u in s10.get("/me/commitments", params=params("s10")).json()["weeklyUpdates"]
               if u["week_number"] == 16)
    instructor.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse")

    entry = log(instructor)[0]
    assert entry["old_values"] == log_hours(30, 0, 0) and entry["new_values"] == log_hours(10, 0, 0)
    wk, _ = week16(s10, "s10")
    assert wk["hours"] == hours(10, 0, 0) and wk["source"] == "baseline"
    after = instructor.get("/classes/c1/ranking", params=ranking).json()
    assert after == before


def test_ranking_factor_matches_restored_weekly_value(app, instructor):
    s10 = approved_baseline(app, instructor)
    put_week(s10, "s10", work=20)
    ranking = {"week": "w16"}
    at_20 = instructor.get("/classes/c1/ranking", params=ranking).json()
    put_week(s10, "s10", work=30)
    upd = next(u for u in s10.get("/me/commitments", params=params("s10")).json()["weeklyUpdates"]
               if u["week_number"] == 16)
    instructor.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse")
    assert instructor.get("/classes/c1/ranking", params=ranking).json() == at_20
    wk, _ = week16(s10, "s10")
    row = next(r for r in at_20["rows"] if r["student_id"] == "s10")
    assert wk["factor"] == row["factor"]


def test_reverse_without_approved_baseline_gives_zero_hours(app, instructor):
    s13 = client(app, "s13")
    put_week(s13, "s13", work=6)
    upd = s13.get("/me/commitments", params=params("s13")).json()["weeklyUpdates"][0]
    instructor.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse")
    entry = log(instructor)[0]
    assert entry["action"] == "weekly.reverse"
    assert entry["new_values"] == log_hours(0, 0, 0)
    wk, _ = week16(s13, "s13")
    assert wk["hours"] == hours(0, 0, 0) and wk["source"] == "none"


def test_edit_after_reversal_creates_new_update(app, instructor):
    s10 = approved_baseline(app, instructor)
    put_week(s10, "s10", work=20)
    first = next(u for u in s10.get("/me/commitments", params=params("s10")).json()["weeklyUpdates"]
                 if u["week_number"] == 16)
    instructor.post(f"/classes/c1/commitments/weekly-updates/{first['id']}/reverse")
    put_week(s10, "s10", work=25)
    updates = [u for u in s10.get("/me/commitments", params=params("s10")).json()["weeklyUpdates"]
               if u["week_number"] == 16]
    assert len(updates) == 2
    old = next(u for u in updates if u["id"] == first["id"])
    assert old["reversed_at"] is not None
    new = next(u for u in updates if u["id"] != first["id"])
    assert new["reversed_at"] is None and new["work_hours"] == 25
    newest = log(instructor)[0]
    assert newest["action"] == "weekly.set" and newest["old_values"] == log_hours(10, 0, 0)


def test_entries_newest_first_and_filter_by_student(app, instructor, clock):
    s10 = client(app, "s10")
    put_baseline(s10, "s10", work=1)
    clock.advance(60)
    s13 = client(app, "s13")
    put_baseline(s13, "s13", work=2)
    entries = log(instructor)
    assert [e["student_id"] for e in entries] == ["s13", "s10"]
    assert entries[0]["at"] > entries[1]["at"]
    assert len({e["id"] for e in entries}) == 2 and all(e["id"] for e in entries)
    assert [e["student_id"] for e in log(instructor, studentId="s10")] == ["s10"]
    assert log(instructor, studentId="nobody") == []


def test_failures_leave_no_trace(app, instructor, s10):
    bid = put_baseline(s10, "s10", work=10)
    assert decide(instructor, bid, {"decision": "approved", "effectiveFromWeek": 1}).status_code == 200
    baseline_count = len(log(instructor))

    p = params("s10")
    assert s10.put("/me/commitments/baseline", params=p, json=hours(work=81)).status_code == 422
    assert s10.put("/me/commitments/baseline", params=p, json=hours(work=10.25)).status_code == 422
    assert s10.put("/me/commitments/baseline", params=p, json=hours(80, 40, 1)).status_code == 422
    assert s10.put("/me/commitments/weeks/16", params=p, json=hours(work=81)).status_code == 422
    assert s10.put("/me/commitments/weeks/1", params=p, json=hours(work=3)).status_code == 400  # not editable
    assert s10.put("/me/commitments/weeks/99", params=p, json=hours(work=3)).status_code == 404
    assert s10.put("/me/commitments/weeks/16", params=params("s13"), json=hours(work=3)).status_code == 403
    assert instructor.put("/me/commitments/baseline", params=p, json=hours(work=3)).status_code == 403
    assert s10.put("/me/commitments/baseline", params={"classId": "nope", "studentId": "s10"},
                   json=hours(work=3)).status_code == 404
    assert decide(instructor, bid, {"decision": "approved"}).status_code == 409
    assert decide(instructor, "c1-b999", {"decision": "approved"}).status_code == 404
    assert s10.post(f"/classes/c1/commitments/baselines/{bid}/decide",
                    json={"decision": "approved"}).status_code == 403
    assert len(log(instructor)) == baseline_count

    put_week(s10, "s10", work=20)
    upd = next(u for u in s10.get("/me/commitments", params=p).json()["weeklyUpdates"] if u["week_number"] == 16)
    assert s10.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse").status_code == 403
    assert instructor.post("/classes/c1/commitments/weekly-updates/c1-u999/reverse").status_code == 404
    count = len(log(instructor))
    assert instructor.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse").status_code == 200
    assert len(log(instructor)) == count + 1
    assert instructor.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse").status_code == 409
    assert len(log(instructor)) == count + 1


def test_log_write_failure_rolls_back_the_change(app, instructor, monkeypatch):
    store = app.state.ctx.store

    def boom(*args, **kwargs):
        raise RuntimeError("log write failed")

    s10 = approved_baseline(app, instructor)
    put_week(s10, "s10", work=20)
    upd = next(u for u in s10.get("/me/commitments", params=params("s10")).json()["weeklyUpdates"]
               if u["week_number"] == 16)
    entries_before = log(instructor)
    commitments_before = s10.get("/me/commitments", params=params("s10")).json()
    pending_before = instructor.get("/classes/c1/commitments/pending").json()

    monkeypatch.setattr(store, "_add_log", boom)
    safe = TestClient(app, raise_server_exceptions=False)
    safe.headers.update({"Authorization": "Bearer s10"})
    inst = TestClient(app, raise_server_exceptions=False)
    inst.headers.update({"Authorization": "Bearer i1"})

    assert safe.put("/me/commitments/baseline", params=params("s10"), json=hours(work=7)).status_code == 500
    assert safe.put("/me/commitments/weeks/16", params=params("s10"), json=hours(work=40)).status_code == 500
    assert inst.post(f"/classes/c1/commitments/weekly-updates/{upd['id']}/reverse").status_code == 500

    monkeypatch.undo()
    assert s10.get("/me/commitments", params=params("s10")).json() == commitments_before
    assert instructor.get("/classes/c1/commitments/pending").json() == pending_before
    assert log(instructor) == entries_before

    # the decision path too
    s13 = client(app, "s13")
    bid = put_baseline(s13, "s13", work=5)
    monkeypatch.setattr(store, "_add_log", boom)
    assert inst.post(f"/classes/c1/commitments/baselines/{bid}/decide",
                     json={"decision": "approved"}).status_code == 500
    monkeypatch.undo()
    assert any(p["baseline"]["id"] == bid for p in instructor.get("/classes/c1/commitments/pending").json())


def test_change_log_roles(app, anon, instructor, ada, ben):
    put_baseline(client(app, "s10"), "s10", work=3)
    assert anon.get(LOG).status_code == 401
    assert ada.get(LOG).status_code == 403
    assert ada.get(LOG, params={"studentId": "s01"}).status_code == 403
    assert ada.get(LOG, params={"studentId": "s02"}).status_code == 403
    assert instructor.get("/classes/nope/commitments/change-log").status_code == 404


def test_students_cannot_see_other_students_hours(app, instructor, ada):
    put_week(client(app, "s02"), "s02", work=33)
    assert ada.get("/me/commitments", params=params("s02")).status_code == 403
    own = ada.put("/me/commitments/weeks/16", params=params("s01"), json=hours(work=5))
    assert own.status_code == 200
    for payload in (own.json(), ada.get("/me/commitments", params=params("s01")).json()):
        text = json.dumps(payload)
        assert "old_values" not in text and "new_values" not in text and "s02" not in text

    ranking = ada.get("/classes/c1/ranking", params={"week": "w16"}).json()
    for row in ranking["rows"]:
        text = json.dumps(row)
        assert "old_values" not in text and "new_values" not in text
        if row["student_id"] != "s01":
            assert not {"weighted_hours", "factor", "raw", "capped", "hours_source"} & set(row)
    assert ada.get("/classes/c1/students/s02/explanation", params={"week": "w16"}).status_code == 403
    own_expl = ada.get("/classes/c1/students/s01/explanation", params={"week": "w16"}).json()
    assert "old_values" not in json.dumps(own_expl)
    assert ada.post("/classes/c1/commitments/weekly-updates/c1-u1/reverse").status_code == 403


def test_log_survives_restart_with_sqlite_file(tmp_path):
    from app.main import create_app

    url = f"sqlite:///{tmp_path / 'league.db'}"
    first = create_app(database_url=url, frontend_dir=None)
    s10 = client(first, "s10")
    inst = client(first, "i1")
    put_baseline(s10, "s10", work=9)
    entries = log(inst)
    assert len(entries) == 1
    first.state.ctx.store._engine.dispose()

    second = create_app(database_url=url, frontend_dir=None)
    assert log(client(second, "i1")) == entries
    # ids keep counting from the saved log
    put_baseline(client(second, "s13"), "s13", work=2)
    ids = [e["id"] for e in log(client(second, "i1"))]
    assert len(set(ids)) == 2
