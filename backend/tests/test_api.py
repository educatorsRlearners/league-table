"""Functional tests for the spec endpoints (mirrors frontend/services/tests.js)."""

import json
from itertools import pairwise


def approx(a, b, eps=1e-6):
    return abs(a - b) <= eps


def test_auth_required(anon):
    assert anon.get("/classes").status_code == 401
    assert anon.get("/classes/c1/bootstrap").status_code == 401


def test_list_classes(instructor):
    r = instructor.get("/classes")
    assert r.status_code == 200
    classes = r.json()
    assert len(classes) == 2 and all(c["instructor_id"] == "i1" for c in classes)


def test_list_classes_forbids_other_instructor(instructor):
    r = instructor.get("/classes", params={"instructor_id": "i2"})
    assert r.status_code == 403


def test_student_cannot_list_classes(ada):
    assert ada.get("/classes").status_code == 403


def test_bootstrap_shape(instructor):
    boot = instructor.get("/classes/c1/bootstrap").json()
    assert len(boot["weeks"]) == 16 and len(boot["criteria"]) == 5
    assert round(sum(boot["weights"].values())) == 100
    assert boot["settings"]["cap"] == 1.25 and boot["settings"]["rate"] == 0.01
    assert boot["source"]["demo"] is True
    assert len(boot["tieBreakers"]) >= 1
    assert boot["rollingN"] == 4
    assert boot["latestCompleteWeekId"] is not None


def test_ranking_shape_and_order(instructor):
    res = instructor.get("/classes/c1/ranking", params={"week": "w5"}).json()
    assert len(res["rows"]) == 24
    assert res["rows"][0]["rank"] == 1
    scores = [r["score"] for r in res["rows"]]
    assert all(b <= a + 1e-9 for a, b in pairwise(scores))
    assert all(0 <= r["score"] <= 100 + 1e-9 for r in res["rows"])
    assert res["weekCount"] == 1


def test_ranking_unknown_and_empty_week(instructor):
    unknown = instructor.get("/classes/c1/ranking", params={"week": "w99"}).json()
    assert unknown["rows"] == []
    empty = instructor.get("/classes/c1/ranking", params={"week": "w15"}).json()
    assert empty["rows"] == []


def test_cap_and_factor(instructor):
    res = instructor.get("/classes/c1/ranking", params={"week": "w5"}).json()
    capped = [r for r in res["rows"] if r.get("capped")]
    assert capped and all(approx(r["score"], 100, 1e-9) for r in capped)
    assert all(r["factor"] <= 1.25 + 1e-9 for r in res["rows"] if r.get("factor") is not None)


def test_pending_baseline_neutral(instructor):
    res = instructor.get("/classes/c1/ranking", params={"week": "w8"}).json()
    pending = next(r for r in res["rows"] if r["student_id"] == "s03")
    assert approx(pending["factor"], 1, 1e-9)


def test_effective_week(instructor):
    before = instructor.get("/classes/c1/ranking", params={"week": "w5"}).json()
    after = instructor.get("/classes/c1/ranking", params={"week": "w6"}).json()
    sid = "s05"
    assert approx(next(r for r in before["rows"] if r["student_id"] == sid)["factor"], 1, 1e-9)
    assert next(r for r in after["rows"] if r["student_id"] == sid)["factor"] > 1


def test_tie_and_rank_delta(instructor):
    res = instructor.get("/classes/c1/ranking", params={"week": "w9"}).json()
    tied = [r for r in res["rows"] if r["tied"]]
    assert len(tied) >= 2
    assert len({r["rank"] for r in tied}) < len(tied)


def test_windows(instructor):
    week = instructor.get("/classes/c1/ranking", params={"week": "w8"}).json()
    rolling = instructor.get("/classes/c1/ranking", params={"week": "w8", "window": "rolling", "rollingN": 4}).json()
    cume = instructor.get("/classes/c1/ranking", params={"week": "w8", "window": "cumulative"}).json()
    assert (week["weekCount"], rolling["weekCount"], cume["weekCount"]) == (1, 4, 8)
    early = instructor.get("/classes/c1/ranking", params={"week": "w2", "window": "rolling", "rollingN": 4}).json()
    assert early["weekCount"] == 2


def test_weights_override_rescaled(instructor):
    boot = instructor.get("/classes/c1/bootstrap").json()
    before = instructor.get("/classes/c1/ranking", params={"week": "w5", "weights": json.dumps(boot["weights"])}).json()
    after = instructor.get("/classes/c1/ranking", params={
        "week": "w5",
        "weights": json.dumps({"homework": 100, "attendance": 0, "participation": 0, "project": 0, "quizzes": 0}),
    }).json()
    assert [r["student_id"] for r in before["rows"]] != [r["student_id"] for r in after["rows"]]
    assert round(sum(after["weights"].values())) == 100


def test_criteria_filter(instructor):
    res = instructor.get("/classes/c1/ranking", params={"week": "w5", "criteria": "attendance"}).json()
    assert res["criteriaKeys"] == ["attendance"]
    ex = instructor.get(f"/classes/c1/students/{res['rows'][0]['student_id']}/explanation",
                        params={"week": "w5", "criteria": "attendance"}).json()
    assert len(ex["parts"]) == 1 and ex["parts"][0]["key"] == "attendance"


def test_name_mode(instructor):
    res = instructor.get("/classes/c1/ranking", params={"week": "w5", "nameMode": "initials"}).json()
    import re
    assert all(re.match(r"^[^ ]+ [A-Z]\.$", r["display_name"]) for r in res["rows"])


def test_student_scoping(ada):
    res = ada.get("/classes/c1/ranking", params={"week": "w7"}).json()
    for r in res["rows"]:
        if r["student_id"] == "s01":
            assert r["raw"] is not None and r["factor"] is not None and r["is_self"] is True
        else:
            assert "raw" not in r and "factor" not in r and "weighted_hours" not in r
            assert r["score"] is not None and r["rank"] is not None


def test_student_other_class_forbidden(ada):
    assert ada.get("/classes/c2/ranking", params={"week": "w5"}).status_code == 403


def test_explanation_sums(instructor):
    boot = instructor.get("/classes/c1/bootstrap").json()
    res = instructor.get("/classes/c1/ranking",
                         params={"week": "w7", "weights": json.dumps(boot["weights"])}).json()
    for row in res["rows"][:3]:
        ex = instructor.get(f"/classes/c1/students/{row['student_id']}/explanation",
                            params={"week": "w7", "weights": json.dumps(boot["weights"])}).json()
        assert approx(sum(p["points"] for p in ex["parts"]), ex["raw"], 1e-6) or approx(
            sum(p["points"] for p in ex["parts"]), ex["focusRaw"], 1e-6)
        assert approx(ex["score"], min(100, ex["raw"] * ex["factor"]), 1e-6)
        assert approx(ex["score"], row["score"], 1e-6)


def test_explanation_auth(ada):
    assert ada.get("/classes/c1/students/s02/explanation", params={"week": "w5"}).status_code == 403
    assert ada.get("/classes/c1/students/s99/explanation", params={"week": "w5"}).status_code in (403, 404)
    own = ada.get("/classes/c1/students/s01/explanation", params={"week": "w5"})
    assert own.status_code == 200


def test_explainer(instructor):
    ex = instructor.get("/classes/c1/explainer").json()
    assert len(ex["table"]) == 4 and approx(ex["table"][3]["factor"], 1.25)
    assert approx(ex["example"]["adjusted"], 94.4, 1e-6)
    assert "student" not in json.dumps(ex).lower()


def test_commitments(instructor, ada):
    own = ada.get("/me/commitments", params={"classId": "c1", "studentId": "s01"}).json()
    assert len(own["byWeek"]) == 16
    assert approx(own["byWeek"][0]["factor"], 1.18, 1e-6)
    assert ada.get("/me/commitments", params={"classId": "c1", "studentId": "s02"}).status_code == 403
    full = instructor.get("/me/commitments", params={"classId": "c1", "studentId": "s02"}).json()
    assert full["studentId"] == "s02"


def test_digest(instructor):
    digest = instructor.get("/instructor/digest").json()
    assert len(digest["groups"]) == 2
    for g in digest["groups"]:
        assert g["rows"]
        assert len(g["rows"]) <= 12
        assert all(r["status"] in ("new", "still", "cleared") for r in g["rows"])
        assert g["comparedWith"] == g["week"] - 1 or (g["week"] == 1 and g["comparedWith"] is None)
    second = instructor.get("/instructor/digest").json()
    assert second == digest


def test_digest_week_param(instructor):
    digest = instructor.get("/instructor/digest", params={"week": 5}).json()
    for g in digest["groups"]:
        assert g["week"] == 5
        assert g["comparedWith"] == 4


def test_risk_record(instructor, ada):
    rec = instructor.get("/classes/c1/students/s01/risk").json()
    assert rec["level"] == "Not flagged"
    assert len(rec["signals"]) == 5
    assert rec["thresholds"]["projectedGrade"] == 60
    assert len(rec["history"]) > 1
    assert rec["notes"] is not None
    own = ada.get("/classes/c1/students/s01/risk").json()
    assert own["notes"] == []
    assert ada.get("/classes/c1/students/s02/risk").status_code == 403
    assert instructor.get("/classes/c1/students/s99/risk").status_code == 404


def test_risk_settings_per_class(instructor):
    instructor.put("/classes/c1/risk-settings", json={"thresholds": {"commitmentHours": 5}})
    a = instructor.get("/classes/c1/risk-settings").json()
    b = instructor.get("/classes/c2/risk-settings").json()
    assert a["thresholds"]["commitmentHours"] == 5 and b["thresholds"]["commitmentHours"] == 20


def test_notes(instructor, ada):
    before = instructor.get("/classes/c1/students/s13/risk").json()
    note = instructor.post("/classes/c1/students/s13/notes", json={"body": "  Called home 22 Sep  "}).json()
    assert note["body"] == "Called home 22 Sep"
    after = instructor.get("/classes/c1/students/s13/risk").json()
    assert len(after["notes"]) == len(before["notes"]) + 1
    assert instructor.post("/classes/c1/students/s13/notes", json={"body": "   "}).status_code == 400
    assert ada.post("/classes/c1/students/s13/notes", json={"body": "x"}).status_code == 403
    own = ada.get("/classes/c1/students/s01/risk").json()
    assert own["notes"] == []


def test_standing(ada):
    s = ada.get("/me/standing", params={"classId": "c1", "studentId": "s02",
                                        }).status_code
    assert s == 403
    standing = ada.get("/me/standing", params={"classId": "c1", "studentId": "s01"}).json()
    assert standing["signals"] == [x for x in standing["signals"] if x["on"]]
    assert standing["help"]
    text = json.dumps(standing).lower()
    assert "notes" not in standing
    for word in ["rank", "classmate", "fail", "likely to"]:
        assert word not in text


def test_settings_per_class(instructor):
    instructor.put("/classes/c1/settings", json={"weights": {"homework": 50, "attendance": 10, "participation": 10, "project": 20, "quizzes": 10}, "cap": 1.4})
    a = instructor.get("/classes/c1/bootstrap").json()
    b = instructor.get("/classes/c2/bootstrap").json()
    assert round(a["weights"]["homework"]) == 50 and a["settings"]["cap"] == 1.4
    assert b["settings"]["cap"] == 1.25


def test_refresh_cooldown_and_status(instructor):
    assert instructor.post("/classes/c1/refresh").status_code == 200
    assert instructor.post("/classes/c1/refresh").status_code == 429
    status = instructor.get("/classes/c1/status").json()
    assert status["lastUpdated"] is not None and "source" in status


def test_stale_on_source_failure(app, instructor, clock):
    instructor.get("/classes/c1/bootstrap")
    app.state.ctx.db.fail = True
    try:
        clock.advance(61)
        r = instructor.get("/classes/c1/ranking", params={"week": "w5"}).json()
        assert r["stale"] is True and len(r["rows"]) == 24
    finally:
        app.state.ctx.db.fail = False
