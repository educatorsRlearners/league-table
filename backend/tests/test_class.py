from datetime import datetime, timedelta, timezone

import pytest

DEFAULT_WEIGHTS = {"homework": 50, "attendance": 30, "participation": 20}


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    assert parsed.utcoffset() == timedelta(0)
    return parsed


class TestBootstrap:
    def test_returns_everything_the_page_needs(self, instructor):
        response = instructor.get("/api/classes/c1")
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

    def test_weights_fall_back_to_criterion_defaults(self, instructor):
        assert instructor.get("/api/classes/c1").json()["weights"] == DEFAULT_WEIGHTS

    def test_tie_breakers_are_labels_in_priority_order(self, instructor):
        assert instructor.get("/api/classes/c1").json()["tie_breakers"] == ["Attendance", "Homework"]

    def test_source_says_when_it_is_demo_data(self, instructor):
        assert instructor.get("/api/classes/c1").json()["source"] == {
            "kind": "toy", "label": "Demo data", "demo": True,
        }

    def test_source_is_not_demo_for_a_real_adapter(self, instructor, db):
        db.kind, db.label = "sheets", "Google Sheet"
        assert instructor.get("/api/classes/c1").json()["source"] == {
            "kind": "sheets", "label": "Google Sheet", "demo": False,
        }

    def test_last_updated_is_the_time_of_the_read_in_utc(self, instructor, clock):
        body = instructor.get("/api/classes/c1").json()
        assert parse_utc(body["last_updated"]) == datetime.fromtimestamp(clock.now, tz=timezone.utc)

    def test_students_can_load_it_too(self, ada):
        assert ada.get("/api/classes/c1").status_code == 200

    def test_saved_weights_replace_the_defaults(self, instructor):
        instructor.put("/api/classes/c1/settings", json={"weights": {"homework": 1, "attendance": 1, "participation": 2}})
        assert instructor.get("/api/classes/c1").json()["weights"] == {
            "homework": 25, "attendance": 25, "participation": 50,
        }

    def test_unknown_class_is_404(self, instructor):
        response = instructor.get("/api/classes/nope")
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)

    def test_503_when_the_source_is_down_and_nothing_is_cached(self, instructor, db):
        db.fail = True
        response = instructor.get("/api/classes/c1")
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
            "start_date": "2026-12-28", "end_date": "2027-01-01",
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


class TestGetSettings:
    URL = "/api/classes/c1/settings"

    def test_defaults_when_nothing_is_saved(self, instructor):
        response = instructor.get(self.URL)
        assert response.status_code == 200
        assert response.json() == {
            "weights": DEFAULT_WEIGHTS,
            "adjustment": {
                "type_weights": {"work": 1, "childcare": 1, "eldercare": 1},
                "rate": 0.01, "cap": 1.25, "flag_hours": 10,
            },
        }

    def test_default_weights_are_rescaled_to_total_100(self, instructor, db):
        for criterion in db.criteria:
            criterion.default_weight = 1
        weights = instructor.get(self.URL).json()["weights"]
        assert sum(weights.values()) == pytest.approx(100)
        assert weights["homework"] == pytest.approx(100 / 3)

    def test_a_student_may_not_read_the_settings(self, ada):
        assert ada.get(self.URL).status_code == 403

    def test_unknown_class_is_404(self, instructor):
        assert instructor.get("/api/classes/nope/settings").status_code == 404


class TestSaveCriterionWeights:
    URL = "/api/classes/c1/settings"

    def weights(self, client, **weights):
        response = client.put(self.URL, json={"weights": weights})
        assert response.status_code == 200, response.text
        return response.json()["weights"]

    def test_rescales_to_100_preserving_proportions(self, instructor):
        assert self.weights(instructor, homework=1, attendance=1, participation=2) == {
            "homework": 25, "attendance": 25, "participation": 50,
        }

    def test_saved_weights_are_used_by_the_bootstrap(self, instructor, ada):
        self.weights(instructor, homework=10, attendance=10, participation=30)
        assert ada.get("/api/classes/c1").json()["weights"] == pytest.approx(
            {"homework": 20, "attendance": 20, "participation": 60}
        )

    def test_criteria_left_out_are_stored_as_zero(self, instructor):
        assert self.weights(instructor, homework=3, attendance=1) == {
            "homework": 75, "attendance": 25, "participation": 0,
        }

    def test_a_criterion_can_be_switched_off_with_zero(self, instructor):
        assert self.weights(instructor, homework=0, attendance=1, participation=1) == {
            "homework": 0, "attendance": 50, "participation": 50,
        }

    def test_saving_again_replaces_earlier_weights(self, instructor):
        self.weights(instructor, homework=1)
        assert self.weights(instructor, attendance=1) == {"homework": 0, "attendance": 100, "participation": 0}

    def test_weights_are_kept_in_app_settings_not_the_data_source(self, instructor, db):
        before = (list(db.criteria), list(db.entries))
        self.weights(instructor, homework=1)
        assert (db.criteria, db.entries) == before
        assert [c.default_weight for c in db.criteria] == [50, 30, 20]

    def test_a_student_may_not_save_settings(self, ada, instructor):
        response = ada.put(self.URL, json={"weights": {"homework": 1}})
        assert response.status_code == 403
        assert isinstance(response.json()["detail"], str)
        assert instructor.get(self.URL).json()["weights"] == DEFAULT_WEIGHTS

    def test_role_is_checked_before_the_body(self, ada):
        assert ada.put(self.URL, json={"nonsense": True}).status_code == 403

    @pytest.mark.parametrize(
        "body",
        [
            {"weights": {"homework": -1, "attendance": 1}},
            {"weights": {"homework": "lots"}},
            {"weights": {"homework": 1, "unknown_criterion": 1}},
            {"weights": {"homework": 0, "attendance": 0, "participation": 0}},
            {"weights": {}},
            {"weights": [1, 2, 3]},
        ],
    )
    def test_invalid_bodies_are_422_and_save_nothing(self, instructor, body):
        response = instructor.put(self.URL, json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)
        assert instructor.get(self.URL).json()["weights"] == DEFAULT_WEIGHTS

    def test_unknown_class_is_404(self, instructor):
        assert instructor.put("/api/classes/nope/settings", json={"weights": {"homework": 1}}).status_code == 404


class TestSaveAdjustment:
    URL = "/api/classes/c1/settings"

    def test_tunes_the_type_weights_rate_and_cap(self, instructor):
        response = instructor.put(
            self.URL,
            json={"adjustment": {"type_weights": {"childcare": 1.5}, "rate": 0.02, "cap": 1.4}},
        )
        assert response.status_code == 200
        assert response.json()["adjustment"] == {
            "type_weights": {"work": 1, "childcare": 1.5, "eldercare": 1},
            "rate": 0.02, "cap": 1.4, "flag_hours": 10,
        }

    def test_what_is_left_out_keeps_its_value(self, instructor):
        instructor.put(self.URL, json={"adjustment": {"rate": 0.02}})
        instructor.put(self.URL, json={"adjustment": {"cap": 1.5}})
        assert instructor.get(self.URL).json()["adjustment"]["rate"] == 0.02

    def test_weights_are_untouched_by_an_adjustment_only_change(self, instructor):
        instructor.put(self.URL, json={"adjustment": {"cap": 1.5}})
        assert instructor.get(self.URL).json()["weights"] == DEFAULT_WEIGHTS

    @pytest.mark.parametrize(
        "adjustment",
        [{"rate": -0.1}, {"rate": 2}, {"cap": 0.9}, {"cap": 5}, {"flag_hours": -1},
         {"type_weights": {"work": -1}}, {"type_weights": {"nope": 1}}, {"rate": "high"}],
    )
    def test_out_of_range_values_are_422_and_save_nothing(self, instructor, adjustment):
        assert instructor.put(self.URL, json={"adjustment": adjustment}).status_code == 422
        assert instructor.get(self.URL).json()["adjustment"]["rate"] == 0.01

    def test_a_change_is_written_to_the_change_log(self, instructor):
        instructor.put(self.URL, json={"adjustment": {"cap": 1.5}})
        entry = instructor.get("/api/classes/c1/change-log").json()[0]
        assert entry["action"] == "settings_changed"
        assert entry["old_values"]["adjustment"]["cap"] == 1.25
        assert entry["new_values"]["adjustment"]["cap"] == 1.5

    def test_a_student_may_not_tune_it(self, ada):
        assert ada.put(self.URL, json={"adjustment": {"cap": 2}}).status_code == 403


class TestExplainer:
    URL = "/api/classes/c1/explainer"

    def test_every_signed_in_person_can_read_it(self, ada, instructor):
        assert ada.get(self.URL).status_code == 200
        assert instructor.get(self.URL).status_code == 200

    def test_states_the_current_parameters(self, ada):
        body = ada.get(self.URL).json()
        assert (body["rate"], body["cap"]) == (0.01, 1.25)
        assert body["type_weights"] == {"work": 1, "childcare": 1, "eldercare": 1}
        assert [t["key"] for t in body["types"]] == ["work", "childcare", "eldercare"]
        assert body["limits"] == {"step": 0.5, "per_type_max": 80, "total_max": 120}

    def test_the_factor_table_ends_at_the_cap(self, ada):
        table = ada.get(self.URL).json()["factor_table"]
        assert table[0] == {"weighted_hours": 0, "factor": 1}
        assert table[-1] == {"weighted_hours": 25, "factor": 1.25}

    def test_the_worked_example_matches_the_spec(self, ada):
        example = ada.get(self.URL).json()["examples"][0]
        assert example["weighted_hours"] == 18
        assert example["factor"] == pytest.approx(1.18)
        assert example["adjusted_score"] == pytest.approx(94.4)
        assert example["capped"] is False

    def test_an_example_that_reaches_100_says_so(self, ada):
        example = ada.get(self.URL).json()["examples"][1]
        assert example["adjusted_score"] == 100
        assert example["capped"] is True
        assert "100" in example["steps"][-1]

    def test_it_follows_the_settings(self, instructor, ada):
        instructor.put("/api/classes/c1/settings", json={"adjustment": {"rate": 0.02, "cap": 1.5}})
        body = ada.get(self.URL).json()
        assert (body["rate"], body["cap"]) == (0.02, 1.5)
        assert body["examples"][0]["factor"] == pytest.approx(1.36)

    def test_holds_no_personal_data(self, ada):
        text = str(ada.get(self.URL).json())
        assert "Ada" not in text and "s01" not in text
