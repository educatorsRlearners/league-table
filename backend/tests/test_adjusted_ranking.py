"""Ranking and breakdowns once commitments are approved.

Hand-calculated from factories.py. Raw scores: week 1 Ada 94, Ben 82, Cy 75, Di 82;
week 2 Ada 86, Ben 100, Cy 86, Di 62, Ed 76.
"""

import pytest

from test_commitments_api import CLASS, approve, ranking

EXPLAIN = f"{CLASS}/students/{{}}/explanation"


def rows(client, week="w2", **params):
    return {r["student_id"]: r for r in ranking(client, week, **params)}


def explanation(client, student, week="w2", **params):
    response = client.get(EXPLAIN.format(student), params={"week": week} | params)
    assert response.status_code == 200, response.text
    return response.json()


class TestAdjustedScore:
    def test_the_table_ranks_the_adjusted_score(self, ada, cy, instructor):
        approve(instructor, cy, {"work": 10}, effective_week=1)  # x1.10
        table = rows(instructor, "w1")
        assert table["s03"]["score"] == pytest.approx(75 * 1.10)
        assert table["s01"]["score"] == pytest.approx(94)

    def test_a_student_can_overtake_someone_with_a_higher_raw_score(self, cy, instructor):
        # Cy 75 raw is 4th in week 1; x1.25 makes 93.75, still below Ada 94 but above Ben and Di.
        approve(instructor, cy, {"work": 30}, effective_week=1)
        assert [r["student_id"] for r in ranking(instructor, "w1")] == ["s01", "s03", "s02", "s04"]

    def test_the_factor_is_held_at_the_cap_whatever_is_entered(self, cy, instructor):
        approve(instructor, cy, {"work": 80, "childcare": 40}, effective_week=1)
        assert rows(instructor, "w1")["s03"]["score"] == pytest.approx(75 * 1.25)

    def test_no_score_exceeds_100(self, ada, ben, cy, instructor):
        for student in (ada, ben, cy):
            approve(instructor, student, {"work": 40}, effective_week=1)
        for week in ("w1", "w2"):
            for window in ("week", "cumulative", "rolling"):
                assert all(r["score"] <= 100 for r in ranking(instructor, week, window=window))

    def test_a_baseline_only_counts_from_its_effective_week(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=2)
        assert rows(instructor, "w1")["s01"]["score"] == pytest.approx(94)
        assert rows(instructor, "w2")["s01"]["score"] == pytest.approx(86 * 1.10)

    def test_changing_the_settings_re_ranks_every_week(self, cy, instructor):
        approve(instructor, cy, {"work": 10}, effective_week=1)
        instructor.put(f"{CLASS}/settings", json={"adjustment": {"rate": 0.02}})
        assert rows(instructor, "w1")["s03"]["score"] == pytest.approx(75 * 1.20)
        assert rows(instructor, "w2")["s03"]["score"] == 100  # 86 x 1.20 = 103.2, clipped

    def test_a_type_weight_changes_what_an_hour_counts_for(self, cy, instructor):
        approve(instructor, cy, {"childcare": 10}, effective_week=1)
        instructor.put(f"{CLASS}/settings", json={"adjustment": {"type_weights": {"childcare": 1.5}}})
        assert rows(instructor, "w1")["s03"]["score"] == pytest.approx(75 * 1.15)


class TestTiesAtTheCap:
    def test_students_level_at_100_are_ordered_by_raw_score(self, ada, ben, cy, instructor):
        # Ben 100 raw, Ada 86 and Cy 86 all reach 100 with x1.25 (Ada x1.2 is enough).
        for student in (ada, ben, cy):
            approve(instructor, student, {"work": 30}, effective_week=1)
        table = ranking(instructor, "w2")
        assert [(r["student_id"], r["score"]) for r in table[:3]] == [("s02", 100), ("s01", 100), ("s03", 100)]
        # Ada and Cy have the same raw 86, so attendance (100 against 80) decides, and they still get distinct ranks.
        assert [r["rank"] for r in table[:3]] == [1, 2, 3]
        assert not any(r["tied"] for r in table[:3])

    def test_students_level_on_everything_share_a_rank(self, ben, instructor):
        # Ben's week-1 raw is 82, the same as Di's, with the same attendance and homework.
        approve(instructor, ben, {}, effective_week=1)  # an approved baseline of no hours: factor 1.00
        table = rows(instructor, "w1")
        assert table["s02"]["rank"] == table["s04"]["rank"] == 2
        assert table["s02"]["tied"] and table["s04"]["tied"]


class TestWindows:
    def test_cumulative_averages_weeks_that_have_different_factors(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=2)  # week 1 stays x1.00
        assert rows(instructor, "w2", window="cumulative")["s01"]["score"] == pytest.approx((94 + 86 * 1.10) / 2)

    def test_a_capped_week_is_clipped_before_it_is_averaged(self, ada, instructor):
        approve(instructor, ada, {"work": 30}, effective_week=1)
        # Week 1: 94 x 1.25 = 117.5 -> 100. Week 2: 86 x 1.25 = 107.5 -> 100. The mean is 100, not 112.5.
        assert rows(instructor, "w2", window="cumulative")["s01"]["score"] == 100

    def test_an_average_never_exceeds_100(self, ada, ben, instructor):
        for student in (ada, ben):
            approve(instructor, student, {"work": 80}, effective_week=1)
        assert max(r["score"] for r in ranking(instructor, "w2", window="cumulative")) <= 100

    def test_rolling_covers_the_last_n_weeks_only(self, instructor):
        # Week 3 has no entries. A window of two weeks ending there holds weeks 2 and 3, so only
        # week 2 counts; a window of three also reaches week 1.
        assert rows(instructor, "w3", window="rolling", rolling_weeks=2)["s01"]["score"] == pytest.approx(86)
        assert rows(instructor, "w3", window="rolling", rolling_weeks=3)["s01"]["score"] == pytest.approx(90)

    def test_a_rolling_window_wider_than_the_term_equals_the_cumulative_one(self, instructor):
        assert ranking(instructor, "w2", window="rolling", rolling_weeks=16) == ranking(instructor, "w2", window="cumulative")

    def test_a_rolling_window_of_the_default_length_is_reported(self, instructor):
        body = instructor.get(f"{CLASS}/ranking", params={"week": "w2", "window": "rolling"}).json()
        assert (body["window_mode"], body["rolling_weeks"]) == ("rolling", 4)
        other = instructor.get(f"{CLASS}/ranking", params={"week": "w2", "window": "rolling", "rolling_weeks": 2}).json()
        assert other["rolling_weeks"] == 2

    def test_rolling_weeks_is_not_reported_for_other_windows(self, instructor):
        assert instructor.get(f"{CLASS}/ranking", params={"week": "w2"}).json()["rolling_weeks"] is None

    def test_movement_compares_adjusted_ranks_week_to_week(self, cy, instructor):
        before = rows(instructor, "w2")["s03"]["rank"]
        approve(instructor, cy, {"work": 30}, effective_week=2)  # only week 2 changes
        table = rows(instructor, "w2")
        assert table["s03"]["rank"] < before
        assert table["s03"]["rank_delta"] == 4 - table["s03"]["rank"]  # he was 4th in week 1, unadjusted


class TestBreakdown:
    def test_a_single_week_shows_the_whole_calculation(self, ada, instructor):
        approve(instructor, ada, {"work": 12, "childcare": 6}, effective_week=1)
        body = explanation(ada, "s01", "w1")
        assert body["raw_score"] == pytest.approx(94)
        assert body["hours"] == {"work": 12, "childcare": 6, "eldercare": 0}
        assert body["weighted_hours"] == 18
        assert body["factor"] == pytest.approx(1.18)
        assert body["score"] == 100 and body["capped"] is True
        assert sum(p["points"] for p in body["parts"]) == pytest.approx(body["raw_score"])
        assert len(body["weeks"]) == 1

    def test_the_parts_add_up_to_the_raw_score_and_the_factor_gives_the_score(self, ada, instructor):
        approve(instructor, ada, {"work": 5}, effective_week=1)
        body = explanation(ada, "s01", "w1")
        assert sum(p["points"] for p in body["parts"]) == pytest.approx(body["raw_score"])
        assert body["raw_score"] * body["factor"] == pytest.approx(body["score"])
        assert body["capped"] is False

    def test_a_student_without_commitments_has_a_neutral_factor(self, ada):
        body = explanation(ada, "s01", "w1")
        assert (body["factor"], body["weighted_hours"], body["capped"]) == (1.0, 0, False)
        assert body["score"] == pytest.approx(body["raw_score"])

    def test_a_multi_week_window_lists_each_week(self, ada, instructor):
        approve(instructor, ada, {"work": 10}, effective_week=2)
        body = explanation(ada, "s01", "w2", window="cumulative")
        assert [w["week_number"] for w in body["weeks"]] == [1, 2]
        assert [round(w["factor"], 2) for w in body["weeks"]] == [1.0, 1.1]
        assert body["score"] == pytest.approx(sum(w["adjusted_score"] for w in body["weeks"]) / 2)
        assert body["raw_score"] == pytest.approx(sum(w["raw_score"] for w in body["weeks"]) / 2)
        assert body["factor"] is None and body["hours"] is None
        assert sum(p["points"] for p in body["parts"]) == pytest.approx(body["raw_score"])

    def test_a_week_with_no_entries_is_not_counted_in_the_average(self, instructor):
        body = explanation(instructor, "s05", "w2", window="cumulative")  # Ed joins in week 2
        assert [w["week_number"] for w in body["weeks"]] == [2]
        assert body["score"] == pytest.approx(76)

    def test_the_breakdown_matches_the_ranking_row(self, ada, ben, instructor):
        approve(instructor, ada, {"work": 12, "childcare": 6}, effective_week=1)
        approve(instructor, ben, {"work": 5}, effective_week=2)
        for window in ("week", "cumulative", "rolling"):
            table = rows(instructor, "w2", window=window)
            for student, row in table.items():
                body = explanation(instructor, student, "w2", window=window)
                assert body["score"] == pytest.approx(row["score"])
                assert (body["rank"], body["tied"]) == (row["rank"], row["tied"])
