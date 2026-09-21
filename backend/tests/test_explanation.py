import pytest
from dataclasses import replace

from fastapi.testclient import TestClient

from factories import ADA

PART_FIELDS = {
    "key", "label", "earned", "possible", "normalised", "weight", "effective_weight", "points", "missing",
}


def url(student_id: str) -> str:
    return f"/api/classes/c1/students/{student_id}/explanation"


def explanation(client, student_id="s03", **params):
    params = {"week": "w1"} | params
    response = client.get(url(student_id), params=params)
    assert response.status_code == 200, response.text
    return response.json()


def parts_by_key(body):
    return {p["key"]: p for p in body["parts"]}


class TestBreakdown:
    def test_response_shape(self, instructor):
        body = explanation(instructor)
        assert set(body) == {
            "student_id", "display_name", "rank", "tied", "score", "raw_score", "factor",
            "weighted_hours", "hours", "capped", "parts", "weeks", "gap_to_next", "gap_to_below",
            "above", "week_id", "window_mode", "rolling_weeks",
        }
        assert body["week_id"] == "w1"
        assert body["window_mode"] == "week"
        assert all(set(p) == PART_FIELDS for p in body["parts"])

    def test_shows_the_formula_with_real_numbers(self, instructor):
        parts = parts_by_key(explanation(instructor, "s01"))
        assert parts["homework"] == {
            "key": "homework", "label": "Homework", "earned": 5, "possible": 5, "normalised": 100,
            "weight": 50, "effective_weight": 50, "points": 50, "missing": False,
        }
        assert parts["attendance"]["earned"] == 4
        assert parts["attendance"]["possible"] == 5
        assert parts["attendance"]["normalised"] == pytest.approx(80)
        assert parts["attendance"]["points"] == pytest.approx(24)

    def test_parts_are_in_criterion_order(self, instructor):
        assert [p["key"] for p in explanation(instructor)["parts"]] == ["homework", "attendance", "participation"]

    def test_a_missing_criterion_is_excluded_not_scored_as_zero(self, instructor):
        body = explanation(instructor, "s03")
        missing = parts_by_key(body)["participation"]
        assert missing == {
            "key": "participation", "label": "Participation", "earned": None, "possible": None,
            "normalised": None, "weight": 20, "effective_weight": 0, "points": 0, "missing": True,
        }
        # The remaining weights are rescaled to 100: 50/80 and 30/80.
        parts = parts_by_key(body)
        assert parts["homework"]["effective_weight"] == pytest.approx(62.5)
        assert parts["attendance"]["effective_weight"] == pytest.approx(37.5)
        assert body["score"] == pytest.approx(75)

    def test_rank_and_gaps_for_a_student_in_a_lone_rank(self, instructor):
        body = explanation(instructor, "s03")
        assert body["rank"] == 4
        assert body["tied"] is False
        assert body["gap_to_next"] == pytest.approx(7)
        assert body["gap_to_below"] is None

    def test_above_is_the_nearest_student_ranked_higher(self, instructor):
        # Ranks 1, 2, 2, 4: the nearest student above Cy (4th) is Di, listed last of the tied pair.
        assert explanation(instructor, "s03")["above"] == "Di Evans"

    def test_a_tied_student_looks_past_their_tie_partner(self, instructor):
        body = explanation(instructor, "s04")
        assert body["rank"] == 2
        assert body["tied"] is True
        assert body["above"] == "Ada Lovelace"
        assert body["gap_to_next"] == pytest.approx(12)

    def test_the_leader_has_nothing_above(self, instructor):
        body = explanation(instructor, "s01")
        assert body["rank"] == 1
        assert body["above"] is None
        assert body["gap_to_next"] is None
        assert body["gap_to_below"] == pytest.approx(12)

    def test_parts_add_up_to_the_score_for_every_student_and_window(self, instructor):
        for window in ("week", "cumulative", "rolling"):
            for week in ("w1", "w2"):
                table = instructor.get(
                    "/api/classes/c1/ranking", params={"week": week, "window": window}
                ).json()["rows"]
                for row in table:
                    body = explanation(instructor, row["student_id"], week=week, window=window)
                    # The criteria add up to the raw score; with no commitments that is the score.
                    assert sum(p["points"] for p in body["parts"]) == pytest.approx(body["raw_score"])
                    assert body["score"] == pytest.approx(body["raw_score"])
                    assert body["score"] == pytest.approx(row["score"])

    def test_matches_the_ranking_row(self, instructor):
        table = instructor.get("/api/classes/c1/ranking", params={"week": "w2"}).json()["rows"]
        for row in table:
            body = explanation(instructor, row["student_id"], week="w2")
            assert {k: body[k] for k in ("rank", "tied", "gap_to_next", "gap_to_below")} == pytest.approx(
                {k: row[k] for k in ("rank", "tied", "gap_to_next", "gap_to_below")}
            )
            assert body["display_name"] == row["display_name"]


class TestSameOptionsAsTheRanking:
    def test_cumulative_window(self, instructor):
        body = explanation(instructor, "s02", week="w2", window="cumulative")
        assert body["window_mode"] == "cumulative"
        assert body["score"] == pytest.approx(91)  # the mean of 82 and 100
        participation = parts_by_key(body)["participation"]
        assert (participation["earned"], participation["possible"]) == (25, 35)

    def test_criteria_selection(self, instructor):
        body = explanation(instructor, "s01", criteria="attendance,homework")
        assert [p["key"] for p in body["parts"]] == ["homework", "attendance"]
        assert body["score"] == pytest.approx(100 * 0.625 + 80 * 0.375)

    def test_preview_weights(self, instructor):
        body = explanation(instructor, "s01", weights='{"attendance": 100}')
        assert body["score"] == pytest.approx(80)
        assert parts_by_key(body)["attendance"]["weight"] == pytest.approx(100)
        assert parts_by_key(body)["homework"]["weight"] == 0

    def test_saved_weights_are_used_by_default(self, instructor):
        instructor.put("/api/classes/c1/settings", json={"weights": {"attendance": 1}})
        assert explanation(instructor, "s01")["score"] == pytest.approx(80)

    @pytest.mark.parametrize(
        "mode,expected", [("full", "Ada Lovelace"), ("nickname", "Ace"), ("initials", "Ada L.")]
    )
    def test_name_mode(self, instructor, mode, expected):
        assert explanation(instructor, "s01", name_mode=mode)["display_name"] == expected

    def test_above_uses_the_name_mode(self, instructor):
        assert explanation(instructor, "s04", name_mode="nickname")["above"] == "Ace"


class TestRoles:
    def test_the_instructor_may_open_any_student(self, instructor):
        for student_id in ("s01", "s02", "s03", "s04"):
            assert explanation(instructor, student_id)["student_id"] == student_id

    def test_a_student_may_open_their_own(self, ada):
        assert explanation(ada, "s01")["student_id"] == "s01"

    def test_a_student_may_not_open_someone_elses(self, ada):
        response = ada.get(url("s02"), params={"week": "w1"})
        assert response.status_code == 403
        assert response.json() == {"detail": "A student may only open their own breakdown."}

    def test_every_other_student_is_refused_whatever_the_options(self, ben):
        for params in (
            {"week": "w1"},
            {"week": "w2", "window": "cumulative"},
            {"week": "w1", "criteria": "attendance", "name_mode": "initials"},
        ):
            assert ben.get(url("s01"), params=params).status_code == 403

    def test_a_student_learns_nothing_about_ids_that_are_not_theirs(self, ada):
        # Refused the same way whether or not the other student exists.
        assert ada.get(url("s99"), params={"week": "w1"}).status_code == 403

    def test_a_student_sees_the_same_numbers_as_the_instructor(self, instructor, ada):
        assert explanation(ada, "s01") == explanation(instructor, "s01")


class TestErrors:
    def test_week_is_required(self, instructor):
        response = instructor.get(url("s01"))
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_unknown_student_is_404(self, instructor):
        response = instructor.get(url("s99"), params={"week": "w1"})
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)

    def test_student_with_no_entries_in_the_window_is_404(self, instructor):
        # Ed joins in week 2.
        assert instructor.get(url("s05"), params={"week": "w1"}).status_code == 404
        assert instructor.get(url("s05"), params={"week": "w2"}).status_code == 200

    def test_a_student_with_no_entries_gets_404_for_their_own_breakdown(self, app, store):
        store._accounts[1] = replace(store._accounts[1], student_id="s05")  # Ada's code now belongs to Ed
        client = TestClient(app)
        client.post("/api/auth/login", json={"code": ADA})
        assert client.get(url("s05"), params={"week": "w1"}).status_code == 404

    def test_unknown_week_is_404(self, instructor):
        assert instructor.get(url("s01"), params={"week": "w99"}).status_code == 404

    def test_unknown_class_is_404(self, instructor):
        response = instructor.get("/api/classes/nope/students/s01/explanation", params={"week": "w1"})
        assert response.status_code == 404

    def test_invalid_options_are_422(self, instructor):
        for params in ({"window": "yearly"}, {"criteria": "charisma"}, {"weights": "nope"}, {"name_mode": "x"}):
            assert instructor.get(url("s01"), params={"week": "w1"} | params).status_code == 422

    def test_503_when_the_source_is_down_and_nothing_is_cached(self, instructor, db):
        db.fail = True
        response = instructor.get(url("s01"), params={"week": "w1"})
        assert response.status_code == 503
