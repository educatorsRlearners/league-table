"""The default demo data: 24 students, 16 weeks, 5 criteria and one student in every commitments state."""

import math

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from factories import signed_in

CLASS = "/api/classes/c1"
WEEKS = [f"w{n}" for n in range(1, 17)]


def ranking(client, week, **params):
    response = client.get(f"{CLASS}/ranking", params={"week": week} | params)
    assert response.status_code == 200, response.text
    return response.json()


def round1(score):
    return math.floor(score * 10 + 0.5) / 10


def by_student(body):
    return {row["student_id"]: row for row in body["rows"]}


class TestShape:
    def test_a_class_of_24_students_over_16_weeks_and_5_criteria(self, toy_instructor):
        body = toy_instructor.get(CLASS).json()
        assert body["class"]["name"] == "Introductory Physics · Group B"
        assert [w["id"] for w in body["weeks"]] == WEEKS
        assert [c["key"] for c in body["criteria"]] == [
            "homework", "attendance", "participation", "project", "quizzes",
        ]
        assert body["weights"] == {
            "homework": 25, "attendance": 20, "participation": 20, "project": 25, "quizzes": 10,
        }
        assert body["source"] == {"kind": "toy", "label": "Demo data", "demo": True}
        assert body["issues"] == []
        assert len(ranking(toy_instructor, "w16")["rows"]) == 24

    def test_the_term_is_anchored_so_today_is_in_week_16(self, toy_instructor, clock):
        weeks = toy_instructor.get(f"{CLASS}/weeks").json()
        assert weeks[0]["start_date"] == "2026-09-28"
        assert weeks[-1]["start_date"] == "2027-01-11"  # the Monday of 15 Jan 2027

    def test_the_seed_is_reproducible(self, toy_app, clock):
        one = signed_in(toy_app, "demo-instructor").get(f"{CLASS}/ranking", params={"week": "w5"}).json()
        two = signed_in(create_app(clock=clock), "demo-instructor").get(f"{CLASS}/ranking", params={"week": "w5"}).json()
        assert one["rows"] == two["rows"]

    def test_the_demo_has_the_instructor_and_five_students(self, toy_app):
        accounts = TestClient(toy_app).get("/api/demo/accounts").json()
        assert [(a["name"], a["role"], a["student_id"]) for a in accounts] == [
            ("Instructor", "instructor", None),
            ("Amara Okonkwo", "student", "s01"),
            ("Ben Halvorsen", "student", "s02"),
            ("Cleo Marchetti", "student", "s03"),
            ("Dara Whitfield", "student", "s04"),
            ("Rosa Ibarra", "student", "s18"),
        ]

    def test_every_student_has_an_account_of_their_own(self, toy_app):
        codes = {f"demo-{name}" for name in ("amara", "ben", "cleo", "wes", "xanthe")}
        for code in codes:
            assert TestClient(toy_app).post("/api/auth/login", json={"code": code}).status_code == 200


class TestEveryWeekAndCriterion:
    """Phase 1: browse all 16 weeks and 5 criteria."""

    @pytest.mark.parametrize("week", WEEKS)
    @pytest.mark.parametrize("window", ["week", "cumulative", "rolling"])
    def test_every_week_ranks_consistently(self, toy_instructor, week, window):
        rows = ranking(toy_instructor, week, window=window)["rows"]
        assert rows
        scores = [r["score"] for r in rows]
        assert scores == sorted(scores, key=lambda s: -round1(s))
        assert all(0 <= s <= 100 for s in scores)
        # Rank numbers never skip backwards, and a better rank never has a lower score.
        assert [r["rank"] for r in rows] == sorted(r["rank"] for r in rows)
        assert rows[0]["rank"] == 1

    @pytest.mark.parametrize("criterion", ["homework", "attendance", "participation", "project", "quizzes"])
    def test_every_single_criterion_view(self, toy_instructor, criterion):
        body = ranking(toy_instructor, "w16", criteria=criterion)
        assert body["criteria_keys"] == [criterion]
        assert body["weights"] == {criterion: 100}
        assert body["rows"]

    def test_project_only_has_entries_in_weeks_4_8_12_and_16(self, toy_instructor):
        for n in range(1, 17):
            rows = ranking(toy_instructor, f"w{n}", criteria="project")["rows"]
            assert bool(rows) == (n in (4, 8, 12, 16))


class TestSeededEdgeCases:
    def test_a_student_who_joins_mid_semester_has_no_earlier_entries(self, toy_instructor):
        for week in ("w1", "w2", "w3"):
            assert "s24" not in by_student(ranking(toy_instructor, week))
        assert "s24" in by_student(ranking(toy_instructor, "w4"))
        assert len(ranking(toy_instructor, "w3")["rows"]) == 23
        assert len(ranking(toy_instructor, "w4")["rows"]) == 24

    def test_the_late_joiner_has_no_rank_movement_in_their_first_week(self, toy_instructor):
        assert by_student(ranking(toy_instructor, "w4"))["s24"]["rank_delta"] is None

    def test_a_perfect_week_leads_the_table_even_against_a_capped_factor(self, toy_instructor):
        body = ranking(toy_instructor, "w5")
        amara = by_student(body)["s01"]
        assert amara["score"] == pytest.approx(100)
        assert amara["rank"] == 1
        # Ben's raw score times x1.25 also reaches 100, so raw score is what puts Amara ahead.
        ben = by_student(body)["s02"]
        assert ben["score"] == pytest.approx(100)
        assert ben["rank"] > 1 and not ben["tied"]

    def test_a_zero_week_scores_zero_rather_than_missing(self, toy_instructor):
        pablo = by_student(ranking(toy_instructor, "w6"))["s16"]
        assert pablo["score"] == pytest.approx(0)
        # Only the project, which nobody has in week 6, is missing; the zeros are real scores.
        assert pablo["missing"] == ["project"]

    def test_a_missing_entry_is_flagged_and_not_scored_as_zero(self, toy_instructor):
        rosa = by_student(ranking(toy_instructor, "w7"))["s18"]
        assert rosa["missing"] == ["participation", "project"]  # no project is recorded in week 7
        assert rosa["score"] > 0
        explanation = toy_instructor.get(f"{CLASS}/students/s18/explanation", params={"week": "w7"}).json()
        part = {p["key"]: p for p in explanation["parts"]}["participation"]
        assert part["missing"] is True and part["earned"] is None
        assert sum(p["effective_weight"] for p in explanation["parts"]) == pytest.approx(100)

    def test_an_exact_tie_shares_a_rank(self, toy_instructor):
        rows = by_student(ranking(toy_instructor, "w9"))
        farid, liam = rows["s06"], rows["s12"]
        assert farid["score"] == pytest.approx(liam["score"])
        assert farid["rank"] == liam["rank"]
        assert farid["tied"] and liam["tied"]

    def test_no_score_is_nan(self, toy_instructor):
        for week in ("w1", "w5", "w16"):
            for row in ranking(toy_instructor, week)["rows"]:
                assert not math.isnan(row["score"])


class TestSeededCommitments:
    """One student in each state the spec lists."""

    def mine(self, toy_app, code):
        return signed_in(toy_app, code).get("/api/me/commitments").json()

    def test_a_student_with_no_entry(self, toy_app):
        body = self.mine(toy_app, "demo-rosa")
        assert body["baseline"] is None and body["in_effect"] is None
        assert {w["factor"] for w in body["weeks"]} == {1.0}

    def test_a_pending_baseline(self, toy_app):
        body = self.mine(toy_app, "demo-cleo")
        assert body["baseline"]["status"] == "pending"
        assert body["in_effect"] is None
        assert {w["factor"] for w in body["weeks"]} == {1.0}

    def test_an_approved_baseline_counts_only_from_its_week(self, toy_app):
        body = self.mine(toy_app, "demo-amara")
        assert body["in_effect"]["status"] == "approved"
        assert body["in_effect"]["effective_from_week"] == 3
        factors = {w["week_number"]: w["factor"] for w in body["weeks"]}
        assert factors[1] == factors[2] == 1.0
        assert factors[3] == pytest.approx(1.18)

    def test_a_factor_that_reaches_the_cap(self, toy_app):
        factors = {w["factor"] for w in self.mine(toy_app, "demo-ben")["weeks"]}
        assert factors == {1.25}

    def test_a_weekly_update(self, toy_app):
        body = self.mine(toy_app, "demo-amara")
        assert [(u["week_number"], u["editable"]) for u in body["weekly_updates"]] == [(16, True)]
        assert body["weeks"][-1]["source"] == "weekly"
        assert body["weeks"][-1]["weighted_hours"] == 22  # 16 work + 6 child care

    def test_a_rejected_baseline(self, toy_app):
        body = self.mine(toy_app, "demo-dara")
        assert body["baseline"]["status"] == "rejected"
        assert {w["factor"] for w in body["weeks"]} == {1.0}

    def test_a_reversed_update_is_in_the_log_and_no_longer_counts(self, toy_instructor):
        log = toy_instructor.get(f"{CLASS}/change-log", params={"student_id": "s05"}).json()
        assert [e["action"] for e in reversed(log)] == [
            "baseline_submitted", "baseline_approved", "weekly_update", "weekly_reversed",
        ]
        assert log[0]["flagged"] is False
        assert [e["flagged"] for e in reversed(log)][2] is True  # 32 hours over the baseline
        assert not any(e["reversible"] for e in log)

    def test_a_baseline_change_keeps_the_earlier_weeks_factor(self, toy_app):
        client = signed_in(toy_app, "demo-greta")
        factors = {w["week_number"]: w["factor"] for w in client.get("/api/me/commitments").json()["weeks"]}
        assert factors[1] == factors[8] == pytest.approx(1.10)
        assert factors[9] == factors[16] == pytest.approx(1.20)


class TestStudentAccessOnDemoData:
    def test_amara_reads_her_own_breakdown_but_not_rosas(self, toy_app):
        amara = signed_in(toy_app, "demo-amara")
        params = {"week": "w16"}
        assert amara.get(f"{CLASS}/students/s01/explanation", params=params).status_code == 200
        assert amara.get(f"{CLASS}/students/s18/explanation", params=params).status_code == 403
