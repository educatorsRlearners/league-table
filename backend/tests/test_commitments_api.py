"""A student enters commitments; the instructor approves, reverses and reviews them.

The test clock is Friday 15 Jan 2027, in week 3 of the three-week test term, so weeks 2 and 3
can be edited and week 1 is locked.
"""

import pytest

from factories import ADA, BEN

BASE = {"work": 12, "childcare": 6, "eldercare": 0}
CLASS = "/api/classes/c1"
ME = "/api/me/commitments"


def submit(student, hours=BASE):
    response = student.put(f"{ME}/baseline", json={"hours": hours})
    assert response.status_code == 200, response.text
    return response.json()


def decide(instructor, approval, decision="approve", **body):
    return instructor.post(f"{CLASS}/approvals/{approval['id']}", json={"decision": decision} | body)


def approve(instructor, student, hours=BASE, effective_week=1):
    baseline = submit(student, hours)
    response = decide(instructor, baseline, effective_week=effective_week)
    assert response.status_code == 200, response.text
    return response.json()


def mine(student):
    return student.get(ME).json()


def ranking(client, week="w2", **params):
    return client.get(f"{CLASS}/ranking", params={"week": week} | params).json()["rows"]


def score(client, student_id, week="w2", **params):
    return next(r["score"] for r in ranking(client, week, **params) if r["student_id"] == student_id)


class TestMyCommitments:
    def test_a_student_with_nothing_entered_is_neutral(self, ada):
        body = mine(ada)
        assert body["baseline"] is None and body["in_effect"] is None
        assert body["weekly_updates"] == []
        assert {w["factor"] for w in body["weeks"]} == {1.0}
        assert {w["source"] for w in body["weeks"]} == {"none"}

    def test_lists_the_types_and_limits(self, ada):
        body = mine(ada)
        assert [t["key"] for t in body["types"]] == ["work", "childcare", "eldercare"]
        assert body["limits"] == {"step": 0.5, "per_type_max": 80, "total_max": 120}

    def test_the_edit_window_is_the_current_and_previous_week(self, ada):
        assert mine(ada)["edit_window"] == {"current_week_id": "w3", "editable_week_ids": ["w2", "w3"]}

    def test_the_instructor_has_no_commitments_of_their_own(self, instructor):
        assert instructor.get(ME).status_code == 403


class TestBaseline:
    def test_a_new_baseline_starts_pending_and_changes_nothing(self, ada, instructor):
        before = score(instructor, "s01")
        baseline = submit(ada)
        assert baseline["status"] == "pending"
        assert baseline["hours"] == BASE
        assert baseline["effective_from_week"] is None
        assert score(instructor, "s01") == before
        assert mine(ada)["in_effect"] is None

    def test_a_missing_type_counts_as_zero(self, ada):
        assert submit(ada, {"work": 8})["hours"] == {"work": 8, "childcare": 0, "eldercare": 0}

    def test_submitting_again_while_pending_replaces_it(self, ada, instructor):
        submit(ada, {"work": 5})
        submit(ada, {"work": 9})
        pending = instructor.get(f"{CLASS}/approvals").json()["pending"]
        assert [p["hours"]["work"] for p in pending] == [9]

    @pytest.mark.parametrize(
        "hours",
        [{"work": 7.3}, {"work": -1}, {"work": 81}, {"work": 80, "childcare": 41}, {"gardening": 1}, {"work": "lots"}],
    )
    def test_hours_that_break_a_limit_are_422_and_saved_nowhere(self, ada, instructor, hours):
        response = ada.put(f"{ME}/baseline", json={"hours": hours})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)
        assert mine(ada)["baseline"] is None
        assert instructor.get(f"{CLASS}/approvals").json()["pending"] == []

    def test_the_change_is_logged_with_who_and_when(self, ada, instructor, clock):
        submit(ada)
        (entry,) = instructor.get(f"{CLASS}/change-log").json()
        assert (entry["action"], entry["actor_name"], entry["student_name"]) == (
            "baseline_submitted", "Ada Lovelace", "Ada Lovelace",
        )
        assert entry["new_values"] == {"hours": BASE}
        assert entry["old_values"] is None


class TestApprovals:
    def test_the_queue_shows_pending_baselines_with_hours_by_type(self, ada, ben, instructor):
        submit(ada)
        submit(ben, {"work": 20})
        body = instructor.get(f"{CLASS}/approvals").json()
        assert body["current_week"] == 3
        assert [(p["display_name"], p["hours"]["work"], p["is_change"]) for p in body["pending"]] == [
            ("Ada Lovelace", 12, False), ("Ben Carter", 20, False),
        ]
        assert body["pending"][0]["suggested_effective_week"] == 3

    def test_approving_from_a_week_makes_the_factor_count_from_then(self, ada, instructor):
        approved = approve(instructor, ada, effective_week=2)
        assert approved["status"] == "approved"
        assert approved["effective_from_week"] == 2
        assert score(instructor, "s01", "w1") == pytest.approx(94)          # before the effective week
        assert score(instructor, "s01", "w2") == pytest.approx(100)         # 86 x 1.18 = 101.48, clipped
        assert instructor.get(f"{CLASS}/approvals").json()["pending"] == []

    def test_the_effective_week_defaults_to_the_current_week(self, ada, instructor):
        approved = decide(instructor, submit(ada)).json()
        assert approved["effective_from_week"] == 3

    def test_an_earlier_effective_week_can_be_chosen(self, ada, instructor):
        approved = decide(instructor, submit(ada), effective_week=1).json()
        assert approved["effective_from_week"] == 1

    def test_rejecting_leaves_the_factor_neutral(self, ada, instructor):
        before = score(instructor, "s01")
        rejected = decide(instructor, submit(ada), "reject").json()
        assert rejected["status"] == "rejected"
        assert score(instructor, "s01") == before
        assert mine(ada)["baseline"]["status"] == "rejected"

    def test_a_decided_baseline_cannot_be_decided_again(self, ada, instructor):
        baseline = submit(ada)
        decide(instructor, baseline, "reject")
        response = decide(instructor, baseline)
        assert response.status_code == 409
        assert isinstance(response.json()["detail"], str)

    def test_an_unknown_approval_is_404(self, instructor):
        assert instructor.post(f"{CLASS}/approvals/b99", json={"decision": "approve"}).status_code == 404

    def test_an_effective_week_outside_the_term_is_422(self, ada, instructor):
        baseline = submit(ada)
        assert decide(instructor, baseline, effective_week=9).status_code == 422
        assert decide(instructor, baseline, effective_week=0).status_code == 422
        assert instructor.get(f"{CLASS}/approvals").json()["pending"] != []

    def test_a_student_cannot_decide_or_see_the_queue(self, ada, ben, instructor):
        baseline = submit(ada)
        assert ben.get(f"{CLASS}/approvals").status_code == 403
        assert ada.post(f"{CLASS}/approvals/{baseline['id']}", json={"decision": "approve"}).status_code == 403
        assert mine(ada)["baseline"]["status"] == "pending"

    def test_a_baseline_change_waits_for_approval_and_keeps_the_old_one_meanwhile(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        change = submit(ada, {"work": 20})
        (pending,) = instructor.get(f"{CLASS}/approvals").json()["pending"]
        assert (pending["is_change"], pending["current"]["work"]) == (True, 10)
        body = mine(ada)
        assert body["baseline"]["status"] == "pending"
        assert body["in_effect"]["hours"]["work"] == 10
        assert {w["weighted_hours"] for w in body["weeks"]} == {10}
        assert change["status"] == "pending"

    def test_an_approved_change_replaces_the_old_baseline_from_its_week_only(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        approve(instructor, ada, {"work": 20}, effective_week=3)
        factors = {w["week_number"]: w["factor"] for w in mine(ada)["weeks"]}
        assert factors == {1: pytest.approx(1.10), 2: pytest.approx(1.10), 3: pytest.approx(1.20)}


class TestWeeklyUpdates:
    def put(self, student, week, hours):
        return student.put(f"{ME}/weeks/{week}", json={"hours": hours})

    def test_the_current_and_previous_week_can_be_edited(self, ada):
        assert self.put(ada, 3, {"work": 5}).status_code == 200
        assert self.put(ada, 2, {"work": 5}).status_code == 200

    def test_an_older_week_is_locked(self, ada):
        response = self.put(ada, 1, {"work": 5})
        assert response.status_code == 403
        assert response.json() == {"detail": "Only the current and previous week can be edited."}
        assert mine(ada)["weekly_updates"] == []

    def test_the_window_follows_the_server_clock(self, ada, clock):
        clock.advance(7 * 86400)  # a week later, week 3 has passed and no week is current
        assert self.put(ada, 3, {"work": 5}).status_code == 403
        assert mine(ada)["edit_window"] == {"current_week_id": None, "editable_week_ids": []}

    def test_an_unknown_week_is_404(self, ada):
        assert self.put(ada, 99, {"work": 5}).status_code == 404

    def test_invalid_hours_are_422(self, ada):
        assert self.put(ada, 3, {"work": 200}).status_code == 422

    def test_it_takes_effect_at_once_once_a_baseline_is_approved(self, ada, instructor):
        approve(instructor, ada, {"work": 5}, effective_week=1)
        assert score(instructor, "s01", "w2") == pytest.approx(86 * 1.05)
        self.put(ada, 2, {"work": 10})
        assert score(instructor, "s01", "w2") == pytest.approx(86 * 1.10)
        assert score(instructor, "s01", "w1") == pytest.approx(94 * 1.05)  # a locked week keeps its hours

    def test_it_is_stored_but_has_no_effect_before_approval(self, ada, instructor):
        before = score(instructor, "s01", "w2")
        self.put(ada, 2, {"work": 40})
        assert score(instructor, "s01", "w2") == before
        assert mine(ada)["weekly_updates"][0]["hours"]["work"] == 40

    def test_it_is_logged_with_the_old_and_new_hours(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        self.put(ada, 2, {"work": 14})
        entry = instructor.get(f"{CLASS}/change-log").json()[0]
        assert entry["action"] == "weekly_update"
        assert entry["week_number"] == 2
        assert entry["old_values"]["hours"]["work"] == 10
        assert entry["new_values"]["hours"]["work"] == 14

    def test_a_big_difference_from_the_baseline_is_flagged(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        self.put(ada, 2, {"work": 15})
        self.put(ada, 3, {"work": 25})
        flags = {e["week_number"]: e["flagged"] for e in instructor.get(f"{CLASS}/change-log").json() if e["action"] == "weekly_update"}
        assert flags == {2: False, 3: True}

    def test_the_flag_threshold_can_be_tuned(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        instructor.put(f"{CLASS}/settings", json={"adjustment": {"flag_hours": 2}})
        self.put(ada, 2, {"work": 15})
        assert instructor.get(f"{CLASS}/change-log").json()[0]["flagged"] is True

    def test_reset_returns_the_week_to_the_baseline(self, ada, instructor):
        approve(instructor, ada, {"work": 5}, effective_week=1)
        self.put(ada, 2, {"work": 10})
        assert ada.delete(f"{ME}/weeks/2").status_code == 204
        assert score(instructor, "s01", "w2") == pytest.approx(86 * 1.05)
        assert instructor.get(f"{CLASS}/change-log").json()[0]["action"] == "weekly_reset"

    def test_resetting_a_week_that_follows_the_baseline_changes_nothing(self, ada, instructor):
        assert ada.delete(f"{ME}/weeks/2").status_code == 204
        assert instructor.get(f"{CLASS}/change-log").json() == []

    def test_a_locked_week_cannot_be_reset(self, ada):
        assert ada.delete(f"{ME}/weeks/1").status_code == 403


class TestReversal:
    def reverse(self, instructor, student="s01", week=2):
        return instructor.post(f"{CLASS}/students/{student}/weeks/{week}/reverse")

    def test_a_reversal_restores_the_baseline_and_is_logged(self, ada, instructor):
        approve(instructor, ada, {"work": 5}, effective_week=1)
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 30}})
        assert score(instructor, "s01", "w2") == 100  # 1.30 is held at the 1.25 cap, and 107.5 stops at 100
        assert self.reverse(instructor).status_code == 204
        assert score(instructor, "s01", "w2") == pytest.approx(86 * 1.05)
        entry = instructor.get(f"{CLASS}/change-log").json()[0]
        assert (entry["action"], entry["actor_name"]) == ("weekly_reversed", "Instructor")
        assert entry["old_values"]["hours"]["work"] == 30
        assert entry["new_values"]["hours"]["work"] == 5

    def test_reversing_restores_an_earlier_update_when_there_was_one(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 14}})
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 40}})
        self.reverse(instructor)
        assert mine(ada)["weekly_updates"][0]["hours"]["work"] == 14

    def test_only_the_latest_logged_update_is_reversible(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=1)
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 14}})
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 15}})
        reversible = [e["new_values"]["hours"]["work"] for e in instructor.get(f"{CLASS}/change-log").json() if e["reversible"]]
        assert reversible == [15]
        self.reverse(instructor)
        assert not any(e["reversible"] and e["week_number"] == 2 and e["new_values"]["hours"]["work"] == 15
                       for e in instructor.get(f"{CLASS}/change-log").json())

    def test_the_student_can_enter_the_week_again_after_a_reversal(self, ada, instructor):
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 14}})
        self.reverse(instructor)
        assert ada.put(f"{ME}/weeks/2", json={"hours": {"work": 12}}).status_code == 200

    def test_nothing_to_reverse_is_404(self, ada, instructor):
        assert self.reverse(instructor).status_code == 404
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 14}})
        self.reverse(instructor)
        assert self.reverse(instructor).status_code == 404

    def test_unknown_student_or_week_is_404(self, instructor):
        assert self.reverse(instructor, "s99").status_code == 404
        assert self.reverse(instructor, "s01", 99).status_code == 404

    def test_a_student_cannot_reverse(self, ada, ben):
        ben.put(f"{ME}/weeks/2", json={"hours": {"work": 14}})
        assert ada.post(f"{CLASS}/students/s02/weeks/2/reverse").status_code == 403


class TestChangeLog:
    def test_every_change_appears_newest_first(self, ada, instructor):
        baseline = submit(ada)
        decide(instructor, baseline, effective_week=1)
        ada.put(f"{ME}/weeks/2", json={"hours": {"work": 14}})
        instructor.post(f"{CLASS}/students/s01/weeks/2/reverse")
        assert [e["action"] for e in instructor.get(f"{CLASS}/change-log").json()] == [
            "weekly_reversed", "weekly_update", "baseline_approved", "baseline_submitted",
        ]

    def test_an_approval_records_the_decision_and_the_week(self, ada, instructor):
        decide(instructor, submit(ada), effective_week=2)
        entry = instructor.get(f"{CLASS}/change-log").json()[0]
        assert entry["new_values"]["status"] == "approved"
        assert entry["new_values"]["effective_from_week"] == 2
        assert entry["actor_name"] == "Instructor"

    def test_can_be_filtered_by_student_and_limited(self, ada, ben, instructor):
        submit(ada)
        submit(ben)
        assert [e["student_id"] for e in instructor.get(f"{CLASS}/change-log", params={"student_id": "s02"}).json()] == ["s02"]
        assert len(instructor.get(f"{CLASS}/change-log", params={"limit": 1}).json()) == 1

    def test_entries_carry_a_utc_timestamp(self, ada, instructor):
        submit(ada)
        assert instructor.get(f"{CLASS}/change-log").json()[0]["at"].startswith("2027-01-15T")

    def test_only_the_instructor_can_read_it(self, ada):
        assert ada.get(f"{CLASS}/change-log").status_code == 403


class TestOverview:
    def test_shows_every_students_status_hours_and_factor(self, ada, ben, cy, instructor):
        approve(instructor, ada, {"work": 20}, effective_week=1)
        submit(ben, {"work": 5})
        decide(instructor, submit(cy), "reject")
        rows = {r["student_id"]: r for r in instructor.get(f"{CLASS}/commitments").json()}
        assert (rows["s01"]["status"], rows["s01"]["factor"], rows["s01"]["weighted_hours"]) == ("approved", pytest.approx(1.2), 20)
        assert (rows["s02"]["status"], rows["s02"]["factor"]) == ("pending", 1.0)
        assert rows["s03"]["status"] == "rejected"
        assert (rows["s04"]["status"], rows["s04"]["hours"]) == ("none", None)

    def test_only_the_instructor_can_read_it(self, ada):
        assert ada.get(f"{CLASS}/commitments").status_code == 403


class TestPreview:
    def preview(self, student, hours, **body):
        return student.post(f"{ME}/preview", json={"hours": hours} | body)

    def test_shows_the_factor_and_adjusted_score_without_saving(self, ada):
        response = self.preview(ada, {"work": 12, "childcare": 6})
        assert response.status_code == 200
        body = response.json()
        assert body["week_id"] == "w2"  # her latest week with scores
        assert body["raw_score"] == pytest.approx(86)
        assert body["weighted_hours"] == 18
        assert body["factor"] == pytest.approx(1.18)
        assert body["adjusted_score"] == 100 and body["capped"] is True
        assert mine(ada)["baseline"] is None

    def test_a_chosen_week(self, ada):
        assert self.preview(ada, {"work": 10}, week_id="w1").json()["raw_score"] == pytest.approx(94)

    def test_a_week_with_no_scores_is_404(self, ada):
        assert self.preview(ada, {"work": 10}, week_id="w3").status_code == 404

    def test_invalid_hours_are_422(self, ada):
        assert self.preview(ada, {"work": 99}).status_code == 422

    def test_it_follows_the_instructors_settings(self, ada, instructor):
        instructor.put(f"{CLASS}/settings", json={"adjustment": {"rate": 0.02, "cap": 2}})
        assert self.preview(ada, {"work": 10}, week_id="w1").json()["factor"] == pytest.approx(1.2)


class TestPrivacy:
    """Classmates see the final adjusted score and rank only."""

    HIDDEN = {"raw_score", "factor", "hours", "weighted_hours", "capped", "weeks"}

    def test_ranking_rows_carry_no_raw_score_factor_or_hours(self, ada, ben, instructor):
        approve(instructor, ben, {"work": 20}, effective_week=1)
        for client in (ada, ben):
            for row in ranking(client):
                assert not (self.HIDDEN & set(row))

    def test_no_ranking_response_mentions_anyones_hours(self, ada, ben, instructor):
        approve(instructor, ben, {"work": 33.5}, effective_week=1)
        text = ada.get(f"{CLASS}/ranking", params={"week": "w2"}).text
        assert "33.5" not in text and "childcare" not in text

    def test_a_student_cannot_open_a_classmates_breakdown_and_so_never_sees_their_factor(self, ada, ben, instructor):
        approve(instructor, ben, {"work": 20}, effective_week=1)
        assert ada.get(f"{CLASS}/students/s02/explanation", params={"week": "w2"}).status_code == 403

    def test_a_student_sees_their_own_hours_factor_and_cap_note(self, ada, instructor):
        approve(instructor, ada, {"work": 20}, effective_week=1)
        body = ada.get(f"{CLASS}/students/s01/explanation", params={"week": "w2"}).json()
        assert body["hours"] == {"work": 20, "childcare": 0, "eldercare": 0}
        assert (body["raw_score"], body["factor"], body["score"], body["capped"]) == (
            pytest.approx(86), pytest.approx(1.2), 100, True,
        )

    def test_students_cannot_read_each_others_commitments(self, ada, ben):
        submit(ben, {"work": 33.5})
        assert "33.5" not in ada.get(ME).text

    def test_the_general_explainer_holds_no_hours(self, ada, ben, instructor):
        approve(instructor, ben, {"work": 33.5}, effective_week=1)
        assert "33.5" not in ada.get(f"{CLASS}/explainer").text
