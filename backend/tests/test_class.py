from datetime import datetime, timedelta, timezone

import pytest

DEFAULT_WEIGHTS = {"homework": 50, "attendance": 30, "participation": 20}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0)
    return parsed


class TestBootstrap:
    def test_returns_everything_the_page_needs(self, teacher):
        response = teacher.get("/api/classes/c1")
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "class", "weeks", "criteria", "weights", "tie_breakers", "source", "last_updated", "issues",
        }
        assert body["class"] == {
            "id": "c1", "external_id": "test:c1", "name": "Test class", "term_id": "t1",
        }
        assert [w["id"] for w in body["weeks"]] == ["w1", "w2", "w3"]
        assert [c["key"] for c in body["criteria"]] == ["homework", "attendance", "participation"]
        assert body["issues"] == []

    def test_weights_fall_back_to_criterion_defaults(self, teacher):
        assert teacher.get("/api/classes/c1").json()["weights"] == DEFAULT_WEIGHTS

    def test_tie_breakers_are_labels_in_priority_order(self, teacher):
        assert teacher.get("/api/classes/c1").json()["tie_breakers"] == ["Attendance", "Homework"]

    def test_source_says_when_it_is_demo_data(self, teacher):
        assert teacher.get("/api/classes/c1").json()["source"] == {
            "kind": "toy", "label": "Demo data", "demo": True,
        }

    def test_source_is_not_demo_for_a_real_adapter(self, teacher, db):
        db.kind, db.label = "sheets", "Google Sheet"
        assert teacher.get("/api/classes/c1").json()["source"] == {
            "kind": "sheets", "label": "Google Sheet", "demo": False,
        }

    def test_last_updated_is_the_time_of_the_read_in_utc(self, teacher, clock):
        body = teacher.get("/api/classes/c1").json()
        assert parse_utc(body["last_updated"]) == datetime.fromtimestamp(clock.now, tz=timezone.utc)

    def test_students_can_load_it_too(self, ada):
        assert ada.get("/api/classes/c1").status_code == 200

    def test_saved_weights_replace_the_defaults(self, teacher):
        teacher.put("/api/classes/c1/weights", json={"weights": {"homework": 1, "attendance": 1, "participation": 2}})
        assert teacher.get("/api/classes/c1").json()["weights"] == {
            "homework": 25, "attendance": 25, "participation": 50,
        }

    def test_unknown_class_is_404(self, teacher):
        response = teacher.get("/api/classes/nope")
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)

    def test_503_when_the_source_is_down_and_nothing_is_cached(self, teacher, db):
        db.fail = True
        response = teacher.get("/api/classes/c1")
        assert response.status_code == 503
        assert response.json() == {"detail": "The data source did not respond."}


class TestWeeks:
    def test_lists_weeks_oldest_first(self, ada):
        response = ada.get("/api/classes/c1/weeks")
        assert response.status_code == 200
        weeks = response.json()
        assert [w["week_number"] for w in weeks] == [1, 2, 3]
        assert weeks[0] == {
            "id": "w1", "term_id": "t1", "week_number": 1,
            "start_date": "2026-01-05", "end_date": "2026-01-09",
        }

    def test_weeks_come_back_in_order_even_if_the_source_is_shuffled(self, ada, db):
        db.weeks.reverse()
        assert [w["id"] for w in ada.get("/api/classes/c1/weeks").json()] == ["w1", "w2", "w3"]

    def test_unknown_class_is_404(self, ada):
        assert ada.get("/api/classes/nope/weeks").status_code == 404

    def test_503_when_the_source_is_down(self, ada, db):
        db.fail = True
        assert ada.get("/api/classes/c1/weeks").status_code == 503


class TestCriteria:
    def test_lists_criteria_in_display_order(self, ada):
        response = ada.get("/api/classes/c1/criteria")
        assert response.status_code == 200
        criteria = response.json()
        assert [c["key"] for c in criteria] == ["homework", "attendance", "participation"]
        assert criteria[0] == {
            "id": "k1", "class_id": "c1", "key": "homework", "label": "Homework",
            "unit": "tasks on time", "default_weight": 50, "sort_order": 0,
        }

    def test_ordered_by_sort_order_not_source_order(self, ada, db):
        db.criteria.reverse()
        keys = [c["key"] for c in ada.get("/api/classes/c1/criteria").json()]
        assert keys == ["homework", "attendance", "participation"]

    def test_unknown_class_is_404(self, ada):
        assert ada.get("/api/classes/nope/criteria").status_code == 404

    def test_503_when_the_source_is_down(self, ada, db):
        db.fail = True
        assert ada.get("/api/classes/c1/criteria").status_code == 503


class TestGetWeights:
    def test_defaults_when_nothing_is_saved(self, ada):
        response = ada.get("/api/classes/c1/weights")
        assert response.status_code == 200
        assert response.json() == {"class_id": "c1", "weights": DEFAULT_WEIGHTS}

    def test_defaults_are_rescaled_to_total_100(self, ada, db):
        for criterion in db.criteria:
            criterion.default_weight = 1
        weights = ada.get("/api/classes/c1/weights").json()["weights"]
        assert sum(weights.values()) == pytest.approx(100)
        assert weights["homework"] == pytest.approx(100 / 3)

    def test_unknown_class_is_404(self, ada):
        assert ada.get("/api/classes/nope/weights").status_code == 404


class TestSaveWeights:
    URL = "/api/classes/c1/weights"

    def test_rescales_to_100_preserving_proportions(self, teacher):
        response = teacher.put(self.URL, json={"weights": {"homework": 1, "attendance": 1, "participation": 2}})
        assert response.status_code == 200
        assert response.json() == {
            "class_id": "c1", "weights": {"homework": 25, "attendance": 25, "participation": 50},
        }

    def test_saved_weights_are_returned_by_get(self, teacher, ada):
        teacher.put(self.URL, json={"weights": {"homework": 10, "attendance": 10, "participation": 30}})
        assert ada.get(self.URL).json()["weights"] == pytest.approx(
            {"homework": 20, "attendance": 20, "participation": 60}
        )

    def test_criteria_left_out_are_stored_as_zero(self, teacher):
        response = teacher.put(self.URL, json={"weights": {"homework": 3, "attendance": 1}})
        assert response.json()["weights"] == {"homework": 75, "attendance": 25, "participation": 0}

    def test_a_criterion_can_be_switched_off_with_zero(self, teacher):
        response = teacher.put(self.URL, json={"weights": {"homework": 0, "attendance": 1, "participation": 1}})
        assert response.json()["weights"] == {"homework": 0, "attendance": 50, "participation": 50}

    def test_saving_again_replaces_earlier_weights(self, teacher):
        teacher.put(self.URL, json={"weights": {"homework": 1}})
        teacher.put(self.URL, json={"weights": {"attendance": 1}})
        assert teacher.get(self.URL).json()["weights"] == {"homework": 0, "attendance": 100, "participation": 0}

    def test_weights_are_kept_in_app_settings_not_the_data_source(self, teacher, db):
        before = (list(db.criteria), list(db.entries))
        teacher.put(self.URL, json={"weights": {"homework": 1}})
        assert (db.criteria, db.entries) == before
        assert [c.default_weight for c in db.criteria] == [50, 30, 20]

    def test_a_student_may_not_save_weights(self, ada):
        response = ada.put(self.URL, json={"weights": {"homework": 1}})
        assert response.status_code == 403
        assert isinstance(response.json()["detail"], str)

    def test_a_refused_student_change_saves_nothing(self, ada):
        ada.put(self.URL, json={"weights": {"homework": 1}})
        assert ada.get(self.URL).json()["weights"] == DEFAULT_WEIGHTS

    def test_role_is_checked_before_the_body(self, ada):
        assert ada.put(self.URL, json={"nonsense": True}).status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"weights": {"homework": -1, "attendance": 1}},
            {"weights": {"homework": "lots"}},
            {"weights": {"homework": 1, "unknown_criterion": 1}},
            {"weights": {"homework": 0, "attendance": 0, "participation": 0}},
            {"weights": {}},
            {"weights": [1, 2, 3]},
        ],
    )
    def test_invalid_bodies_are_422(self, teacher, body):
        response = teacher.put(self.URL, json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_invalid_bodies_save_nothing(self, teacher):
        teacher.put(self.URL, json={"weights": {"homework": -1}})
        assert teacher.get(self.URL).json()["weights"] == DEFAULT_WEIGHTS

    def test_unknown_class_is_404(self, teacher):
        assert teacher.put("/api/classes/nope/weights", json={"weights": {"homework": 1}}).status_code == 404
