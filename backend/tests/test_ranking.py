"""Ranking against the hand-calculated tables described in factories.py."""

import pytest

from factories import make_entry

URL = "/api/classes/c1/ranking"


def ranking(client, **params):
    response = client.get(URL, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def by_student(body):
    return {row["student_id"]: row for row in body["rows"]}


class TestWeekWindow:
    def test_response_shape(self, instructor):
        body = ranking(instructor, week="w1")
        assert set(body) == {
            "class_id", "week_id", "window_mode", "rolling_weeks", "criteria_keys", "weights", "rows",
            "last_updated", "stale", "issues",
        }
        assert body["class_id"] == "c1"
        assert body["week_id"] == "w1"
        assert body["window_mode"] == "week"
        assert body["stale"] is False
        assert body["issues"] == []
        assert set(body["rows"][0]) == {
            "student_id", "display_name", "score", "rank", "tied", "rank_delta",
            "missing", "gap_to_next", "gap_to_below",
        }

    def test_scores_match_the_hand_calculation(self, instructor):
        rows = by_student(ranking(instructor, week="w1"))
        assert rows["s01"]["score"] == pytest.approx(94)
        assert rows["s02"]["score"] == pytest.approx(82)
        assert rows["s04"]["score"] == pytest.approx(82)
        assert rows["s03"]["score"] == pytest.approx(75)

    def test_only_students_with_entries_appear(self, instructor):
        assert "s05" not in by_student(ranking(instructor, week="w1"))
        assert "s05" in by_student(ranking(instructor, week="w2"))

    def test_rows_are_best_first_with_competition_ranks(self, instructor):
        rows = ranking(instructor, week="w1")["rows"]
        assert [r["student_id"] for r in rows] == ["s01", "s02", "s04", "s03"]
        assert [r["rank"] for r in rows] == [1, 2, 2, 4]

    def test_every_member_of_a_tie_group_is_marked_tied(self, instructor):
        rows = by_student(ranking(instructor, week="w1"))
        assert {sid: rows[sid]["tied"] for sid in rows} == {
            "s01": False, "s02": True, "s04": True, "s03": False,
        }

    def test_tie_breaker_separates_students_level_on_score_and_raw_score(self, instructor):
        # Week 2: Ada and Cy both score 86, raw and adjusted. Ada's attendance (100) beats
        # Cy's (80), so she ranks 2nd and he 3rd rather than sharing a rank.
        rows = ranking(instructor, week="w2")["rows"]
        assert [r["student_id"] for r in rows] == ["s02", "s01", "s03", "s05", "s04"]
        assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5]
        assert not any(r["tied"] for r in rows)

    def test_missing_data_is_excluded_and_weights_rescaled_not_scored_as_zero(self, instructor):
        # Cy has no participation in week 1: 60*62.5% + 100*37.5% = 75, not 60*.5 + 100*.3 = 60.
        rows = by_student(ranking(instructor, week="w1"))
        assert rows["s03"]["score"] == pytest.approx(75)
        assert rows["s03"]["missing"] == ["participation"]
        assert rows["s01"]["missing"] == []

    def test_gaps_to_the_rank_above_and_below(self, instructor):
        rows = by_student(ranking(instructor, week="w1"))
        assert rows["s01"]["gap_to_next"] is None
        assert rows["s01"]["gap_to_below"] == pytest.approx(12)
        # Tied students both look past their tie partner.
        for sid in ("s02", "s04"):
            assert rows[sid]["gap_to_next"] == pytest.approx(12)
            assert rows[sid]["gap_to_below"] == pytest.approx(7)
        assert rows["s03"]["gap_to_next"] == pytest.approx(7)
        assert rows["s03"]["gap_to_below"] is None

    def test_default_window_is_week(self, instructor):
        assert ranking(instructor, week="w2") == ranking(instructor, week="w2", window="week")

    def test_scores_are_between_0_and_100(self, instructor):
        for week in ("w1", "w2"):
            assert all(0 <= r["score"] <= 100 for r in ranking(instructor, week=week)["rows"])

    def test_a_week_nobody_has_entries_for_is_an_empty_table(self, instructor):
        body = ranking(instructor, week="w3")
        assert body["rows"] == []


class TestRankMovement:
    def test_first_week_has_no_movement(self, instructor):
        assert {r["rank_delta"] for r in ranking(instructor, week="w1")["rows"]} == {None}

    def test_positive_is_up_negative_is_down(self, instructor):
        # Week 1 ranks: s01 1, s02 2, s04 2, s03 4.  Week 2 ranks: s02 1, s01 2, s03 3, s05 4, s04 5.
        rows = by_student(ranking(instructor, week="w2"))
        assert rows["s02"]["rank_delta"] == 1
        assert rows["s01"]["rank_delta"] == -1
        assert rows["s03"]["rank_delta"] == 1
        assert rows["s04"]["rank_delta"] == -3

    def test_null_when_the_student_was_not_ranked_the_week_before(self, instructor):
        assert by_student(ranking(instructor, week="w2"))["s05"]["rank_delta"] is None

    def test_unchanged_is_zero_not_null(self, instructor):
        rows = by_student(ranking(instructor, week="w2", criteria="attendance"))
        assert rows["s02"]["rank_delta"] == 0

    def test_movement_uses_the_same_criteria_and_weights_as_the_current_table(self, instructor):
        # Attendance only. Week 1: Ben, Cy, Di tie on 100 (rank 1), Ada 80 (rank 4).
        # Week 2: Ada, Ben, Di, Ed tie on 100 (rank 1), Cy 80 (rank 5).
        rows = by_student(ranking(instructor, week="w2", criteria="attendance"))
        assert rows["s01"]["rank_delta"] == 3
        assert rows["s02"]["rank_delta"] == 0
        assert rows["s03"]["rank_delta"] == -4


class TestCumulativeWindow:
    def test_averages_the_weekly_adjusted_scores(self, instructor):
        rows = by_student(ranking(instructor, week="w2", window="cumulative"))
        assert rows["s01"]["score"] == pytest.approx((94 + 86) / 2)
        # Each week is scored on its own, so Ben's 82 and 100 average to 91. Pooling his
        # participation (25 of 35) would have given 89.29.
        assert rows["s02"]["score"] == pytest.approx(91)
        assert rows["s03"]["score"] == pytest.approx((75 + 86) / 2)
        assert rows["s04"]["score"] == pytest.approx(72)
        # Ed has no week 1, which is left out of his average rather than scored as zero.
        assert rows["s05"]["score"] == pytest.approx(76)

    def test_order_and_ranks(self, instructor):
        body = ranking(instructor, week="w2", window="cumulative")
        assert body["window_mode"] == "cumulative"
        assert [r["student_id"] for r in body["rows"]] == ["s02", "s01", "s03", "s05", "s04"]
        assert [r["rank"] for r in body["rows"]] == [1, 2, 3, 4, 5]

    def test_movement_compares_with_the_previous_cumulative_table(self, instructor):
        rows = by_student(ranking(instructor, week="w2", window="cumulative"))
        assert rows["s01"]["rank_delta"] == -1
        assert rows["s02"]["rank_delta"] == 1
        assert rows["s03"]["rank_delta"] == 1
        assert rows["s04"]["rank_delta"] == -3
        assert rows["s05"]["rank_delta"] is None

    def test_first_week_cumulative_equals_the_week_table(self, instructor):
        cumulative = ranking(instructor, week="w1", window="cumulative")["rows"]
        assert cumulative == ranking(instructor, week="w1", window="week")["rows"]

    def test_a_criterion_missing_one_week_still_counts_when_present_in_another(self, instructor):
        # Cy has participation only in week 2: week 1 alone lacks it, the cumulative total does not.
        rows = by_student(ranking(instructor, week="w2", window="cumulative"))
        assert rows["s03"]["missing"] == []
        assert by_student(ranking(instructor, week="w1"))["s03"]["missing"] == ["participation"]


class TestCriteriaSelection:
    def test_single_criterion_view(self, instructor):
        body = ranking(instructor, week="w1", criteria="attendance")
        assert body["criteria_keys"] == ["attendance"]
        assert body["weights"] == {"attendance": 100}
        rows = by_student(body)
        assert rows["s01"]["score"] == pytest.approx(80)
        assert rows["s02"]["score"] == pytest.approx(100)
        assert [r["rank"] for r in body["rows"]] == [1, 1, 1, 4]
        assert rows["s01"]["rank"] == 4

    def test_weights_of_the_selected_criteria_are_rescaled_to_100(self, instructor):
        body = ranking(instructor, week="w1", criteria="homework,attendance")
        assert body["criteria_keys"] == ["homework", "attendance"]
        assert body["weights"] == pytest.approx({"homework": 62.5, "attendance": 37.5})

    def test_criteria_keys_are_reported_in_criterion_order(self, instructor):
        body = ranking(instructor, week="w1", criteria="attendance,homework")
        assert body["criteria_keys"] == ["homework", "attendance"]

    @pytest.mark.parametrize("value", [None, ""])
    def test_omitted_or_empty_means_all_criteria(self, instructor, value):
        params = {"week": "w1"} if value is None else {"week": "w1", "criteria": value}
        body = ranking(instructor, **params)
        assert body["criteria_keys"] == ["homework", "attendance", "participation"]
        assert body["weights"] == pytest.approx({"homework": 50, "attendance": 30, "participation": 20})

    def test_a_student_with_only_unselected_criteria_is_left_out(self, instructor, db):
        db.entries[:] = [e for e in db.entries if not (e.student_id == "s03" and e.criterion_id != "k1")]
        rows = by_student(ranking(instructor, week="w1", criteria="attendance"))
        assert "s03" not in rows

    def test_unknown_criterion_is_422(self, instructor):
        response = instructor.get(URL, params={"week": "w1", "criteria": "homework,charisma"})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


class TestWeights:
    def test_saved_weights_are_used_when_none_are_given(self, instructor):
        instructor.put("/api/classes/c1/settings", json={"weights": {"homework": 1}})
        body = ranking(instructor, week="w1")
        assert body["weights"] == {"homework": 100, "attendance": 0, "participation": 0}
        rows = by_student(body)
        assert rows["s01"]["score"] == pytest.approx(100)
        assert rows["s03"]["score"] == pytest.approx(60)

    def test_preview_weights_override_the_saved_ones(self, instructor):
        instructor.put("/api/classes/c1/settings", json={"weights": {"attendance": 1}})
        body = ranking(instructor, week="w1", weights='{"homework": 100}')
        assert by_student(body)["s01"]["score"] == pytest.approx(100)

    def test_previewing_does_not_save(self, instructor):
        ranking(instructor, week="w1", weights='{"homework": 100}')
        assert instructor.get("/api/classes/c1/settings").json()["weights"] == {
            "homework": 50, "attendance": 30, "participation": 20,
        }

    def test_preview_weights_are_rescaled_to_100_and_unlisted_criteria_get_zero(self, instructor):
        body = ranking(instructor, week="w1", weights='{"homework": 2, "attendance": 1}')
        assert body["weights"] == pytest.approx({"homework": 200 / 3, "attendance": 100 / 3, "participation": 0})

    def test_only_selected_criteria_count_towards_the_rescaling(self, instructor):
        weights = '{"homework": 30, "attendance": 10, "participation": 60}'
        body = ranking(instructor, week="w1", criteria="homework,attendance", weights=weights)
        assert body["weights"] == pytest.approx({"homework": 75, "attendance": 25})

    def test_a_student_may_preview_weights_too(self, ada):
        body = ranking(ada, week="w1", weights='{"homework": 100}')
        assert by_student(body)["s01"]["score"] == pytest.approx(100)

    @pytest.mark.parametrize(
        "weights",
        ["not json", "[1, 2]", '"text"', '{"homework": -5}', '{"homework": "x"}', '{"charisma": 10}'],
    )
    def test_malformed_weights_are_422(self, instructor, weights):
        response = instructor.get(URL, params={"week": "w1", "weights": weights})
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


class TestNameMode:
    def names(self, client, mode=None):
        params = {"week": "w1"} | ({"name_mode": mode} if mode else {})
        return {r["student_id"]: r["display_name"] for r in ranking(client, **params)["rows"]}

    def test_full_is_the_default(self, instructor):
        assert self.names(instructor)["s01"] == "Ada Lovelace"
        assert self.names(instructor, "full")["s02"] == "Ben Carter"

    def test_nickname_falls_back_to_the_full_name(self, instructor):
        names = self.names(instructor, "nickname")
        assert names["s01"] == "Ace"
        assert names["s02"] == "Ben Carter"

    def test_initials_show_first_name_and_last_initial(self, instructor):
        names = self.names(instructor, "initials")
        assert names["s01"] == "Ada L."
        assert names["s02"] == "Ben C."

    def test_name_mode_does_not_change_the_order(self, instructor):
        orders = [
            [r["student_id"] for r in ranking(instructor, week="w1", name_mode=mode)["rows"]]
            for mode in ("full", "nickname", "initials")
        ]
        assert orders[0] == orders[1] == orders[2]

    def test_unknown_mode_is_422(self, instructor):
        assert instructor.get(URL, params={"week": "w1", "name_mode": "shout"}).status_code == 422


class TestAccess:
    def test_a_student_sees_the_full_ranking(self, instructor, ada):
        assert ranking(ada, week="w1") == ranking(instructor, week="w1")
        assert len(ranking(ada, week="w1")["rows"]) == 4


class TestErrors:
    def test_week_is_required(self, instructor):
        response = instructor.get(URL)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_unknown_window_is_422(self, instructor):
        assert instructor.get(URL, params={"week": "w1", "window": "yearly"}).status_code == 422
        assert instructor.get(URL, params={"week": "w1", "window": "rolling", "rolling_weeks": 1}).status_code == 422

    def test_unknown_week_is_404(self, instructor):
        response = instructor.get(URL, params={"week": "w99"})
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)

    def test_unknown_class_is_404(self, instructor):
        assert instructor.get("/api/classes/nope/ranking", params={"week": "w1"}).status_code == 404

    def test_503_when_the_source_is_down_and_nothing_is_cached(self, instructor, db):
        db.fail = True
        response = instructor.get(URL, params={"week": "w1"})
        assert response.status_code == 503
        assert response.json() == {"detail": "The data source did not respond."}


class TestDataChecks:
    def test_problems_are_listed_and_the_table_is_still_served(self, instructor, db):
        db.entries.append(make_entry("bad1", "s99", "w1", "homework", 3, 5))
        db.entries.append(make_entry("bad2", "s01", "w1", "homework", 6, 5))
        db.entries.append(make_entry("bad3", "s02", "w1", "homework", float("nan"), 5))
        body = ranking(instructor, week="w1")
        assert {(i["level"], i["where"], i["message"]) for i in body["issues"]} == {
            ("error", "bad1", 'Unknown student ID "s99"'),
            ("warning", "bad2", "s01: 6 earned of 5 possible"),
            ("error", "bad3", "Non-numeric score for s02"),
        }
        assert "s99" not in by_student(body)
        assert len(body["rows"]) == 4

    def test_a_non_numeric_entry_is_skipped_not_scored_as_zero(self, instructor, db):
        db.entries.append(make_entry("bad3", "s02", "w1", "homework", float("nan"), 5))
        # Ben's homework now has one good entry (4/5) and one unusable one; the good one still counts.
        assert by_student(ranking(instructor, week="w1"))["s02"]["score"] == pytest.approx(82)
