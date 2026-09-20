"""The default mock database: the same seeded demo class the frontend's mockSource.js builds."""

import math

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from factories import signed_in

CLASS = "/api/classes/c1"


def ranking(client, week, **params):
    response = client.get(f"{CLASS}/ranking", params={"week": week} | params)
    assert response.status_code == 200, response.text
    return response.json()


def round1(score):
    return math.floor(score * 10 + 0.5) / 10


def by_student(body):
    return {row["student_id"]: row for row in body["rows"]}


class TestShape:
    def test_a_class_of_35_students_over_10_weeks_and_5_criteria(self, toy_teacher):
        body = toy_teacher.get(CLASS).json()
        assert body["class"] == {
            "id": "c1", "external_id": "clever:sec-4821", "name": "Year 10 Physics · Set B", "term_id": "t1",
        }
        assert [w["id"] for w in body["weeks"]] == [f"w{n}" for n in range(1, 11)]
        assert [c["key"] for c in body["criteria"]] == [
            "homework", "attendance", "participation", "project", "quizzes",
        ]
        assert body["weights"] == {
            "homework": 25, "attendance": 20, "participation": 20, "project": 25, "quizzes": 10,
        }
        assert body["source"] == {"kind": "toy", "label": "Demo data", "demo": True}
        assert body["issues"] == []

    def test_demo_accounts(self, toy_app):
        accounts = TestClient(toy_app).get("/api/demo/accounts").json()
        assert [(a["email"], a["role"], a["student_id"]) for a in accounts] == [
            ("teacher@demo.test", "teacher", None),
            ("amara@demo.test", "student", "s01"),
            ("rosa@demo.test", "student", "s18"),
        ]

    def test_the_seed_is_reproducible(self, toy_app, clock):
        creds = {"email": "teacher@demo.test", "password": "demo-teacher-1"}
        one = signed_in(toy_app, creds).get(f"{CLASS}/ranking", params={"week": "w5"}).json()
        two = signed_in(create_app(clock=clock), creds).get(f"{CLASS}/ranking", params={"week": "w5"}).json()
        assert one["rows"] == two["rows"]


class TestEveryWeekAndCriterion:
    """Phase 1: a teacher can browse all 10 weeks and 5 criteria."""

    @pytest.mark.parametrize("week", [f"w{n}" for n in range(1, 11)])
    @pytest.mark.parametrize("window", ["week", "cumulative"])
    def test_every_week_ranks_consistently(self, toy_teacher, week, window):
        rows = ranking(toy_teacher, week, window=window)["rows"]
        assert rows
        scores = [r["score"] for r in rows]
        assert scores == sorted(scores, key=lambda s: -round1(s))
        assert all(0 <= s <= 100 for s in scores)
        for row in rows:
            ahead = sum(1 for other in rows if round1(other["score"]) > round1(row["score"]))
            assert row["rank"] == ahead + 1

    @pytest.mark.parametrize("criterion", ["homework", "attendance", "participation", "project", "quizzes"])
    def test_every_single_criterion_view(self, toy_teacher, criterion):
        body = ranking(toy_teacher, "w10", criteria=criterion)
        assert body["criteria_keys"] == [criterion]
        assert body["weights"] == {criterion: 100}
        assert body["rows"]

    def test_project_only_has_entries_in_weeks_2_5_8_and_10(self, toy_teacher):
        for n in range(1, 11):
            rows = ranking(toy_teacher, f"w{n}", criteria="project")["rows"]
            assert bool(rows) == (n in (2, 5, 8, 10))


class TestSeededEdgeCases:
    def test_a_student_who_joins_mid_term_has_no_earlier_entries(self, toy_teacher):
        for week in ("w1", "w2", "w3"):
            assert "s35" not in by_student(ranking(toy_teacher, week))
        assert "s35" in by_student(ranking(toy_teacher, "w4"))
        assert len(ranking(toy_teacher, "w3")["rows"]) == 34
        assert len(ranking(toy_teacher, "w4")["rows"]) == 35

    def test_the_late_joiner_has_no_rank_movement_in_their_first_week(self, toy_teacher):
        assert by_student(ranking(toy_teacher, "w4"))["s35"]["rank_delta"] is None

    def test_a_perfect_week(self, toy_teacher):
        amara = by_student(ranking(toy_teacher, "w5"))["s01"]
        assert amara["score"] == pytest.approx(100)
        assert amara["rank"] == 1

    def test_a_zero_week_scores_zero_rather_than_missing(self, toy_teacher):
        gideon = by_student(ranking(toy_teacher, "w6"))["s33"]
        assert gideon["score"] == pytest.approx(0)
        assert gideon["missing"] == []

    def test_a_missing_entry_is_flagged_and_not_scored_as_zero(self, toy_teacher):
        rosa = by_student(ranking(toy_teacher, "w7"))["s18"]
        assert rosa["missing"] == ["participation"]
        assert rosa["score"] > 0
        explanation = toy_teacher.get(
            f"{CLASS}/students/s18/explanation", params={"week": "w7"}
        ).json()
        part = {p["key"]: p for p in explanation["parts"]}["participation"]
        assert part["missing"] is True and part["earned"] is None
        assert sum(p["effective_weight"] for p in explanation["parts"]) == pytest.approx(100)

    def test_an_exact_tie_shares_a_rank(self, toy_teacher):
        rows = by_student(ranking(toy_teacher, "w9"))
        ben, liam = rows["s02"], rows["s12"]
        assert ben["score"] == pytest.approx(liam["score"])
        assert ben["rank"] == liam["rank"]
        assert ben["tied"] and liam["tied"]

    def test_no_score_is_nan(self, toy_teacher):
        for week in ("w1", "w5", "w10"):
            for row in ranking(toy_teacher, week)["rows"]:
                assert not math.isnan(row["score"])


class TestStudentAccessOnDemoData:
    def test_amara_reads_her_own_breakdown_but_not_rosas(self, toy_app):
        amara = signed_in(toy_app, {"email": "amara@demo.test", "password": "demo-student-1"})
        params = {"week": "w10"}
        assert amara.get(f"{CLASS}/students/s01/explanation", params=params).status_code == 200
        assert amara.get(f"{CLASS}/students/s18/explanation", params=params).status_code == 403
