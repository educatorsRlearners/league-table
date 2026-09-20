"""Status, refresh, caching and the stale-snapshot fallback."""

from datetime import datetime, timezone

import pytest

from factories import make_entry

STATUS = "/api/classes/c1/status"
REFRESH = "/api/classes/c1/refresh"
RANKING = "/api/classes/c1/ranking"


def utc(seconds: float) -> datetime:
    return datetime.fromtimestamp(seconds, tz=timezone.utc)


def last_updated(client) -> datetime:
    return datetime.fromisoformat(client.get(STATUS).json()["last_updated"])


def week_one(client):
    response = client.get(RANKING, params={"week": "w1"})
    assert response.status_code == 200, response.text
    return response.json()


class TestStatus:
    def test_before_any_read_last_updated_is_null(self, teacher):
        assert teacher.get(STATUS).json() == {
            "last_updated": None,
            "stale": False,
            "issues": [],
            "source": {"kind": "toy", "label": "Demo data", "demo": True},
        }

    def test_status_never_triggers_a_fetch(self, teacher, clock):
        teacher.get(STATUS)
        clock.advance(500)
        teacher.get(STATUS)
        assert teacher.get(STATUS).json()["last_updated"] is None

    def test_reports_when_the_source_was_last_read(self, teacher, clock):
        week_one(teacher)
        assert last_updated(teacher) == utc(clock.now)

    def test_a_student_may_read_the_status(self, teacher, ada):
        week_one(teacher)
        assert ada.get(STATUS).status_code == 200

    def test_lists_data_problems(self, teacher, db):
        db.entries.append(make_entry("bad1", "s99", "w1", "homework", 3, 5))
        week_one(teacher)
        assert teacher.get(STATUS).json()["issues"] == [
            {"level": "error", "where": "bad1", "message": 'Unknown student ID "s99"'},
        ]

    def test_unknown_class_is_404(self, teacher):
        assert teacher.get("/api/classes/nope/status").status_code == 404

    def test_works_while_the_source_is_down(self, teacher, db):
        db.fail = True
        response = teacher.get(STATUS)
        assert response.status_code == 200
        assert response.json()["last_updated"] is None


class TestCache:
    def test_reads_within_60_seconds_are_served_from_the_cache(self, teacher, db, clock):
        first = week_one(teacher)
        db.entries.append(make_entry("new", "s05", "w1", "homework", 5, 5))
        clock.advance(59)
        assert week_one(teacher) == first

    def test_a_read_after_60_seconds_picks_up_changes(self, teacher, db, clock):
        week_one(teacher)
        db.entries.append(make_entry("new", "s05", "w1", "homework", 5, 5))
        clock.advance(61)
        body = week_one(teacher)
        assert "s05" in {r["student_id"] for r in body["rows"]}
        assert datetime.fromisoformat(body["last_updated"]) == utc(clock.now)

    def test_last_updated_stays_put_while_cached(self, teacher, clock):
        started = clock.now
        week_one(teacher)
        clock.advance(30)
        assert datetime.fromisoformat(week_one(teacher)["last_updated"]) == utc(started)


class TestRefresh:
    def test_teacher_refresh_succeeds(self, teacher, clock):
        response = teacher.post(REFRESH)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"last_updated", "issues", "stale"}
        assert body["stale"] is False
        assert datetime.fromisoformat(body["last_updated"]) == utc(clock.now)

    def test_bypasses_the_cache(self, teacher, db, clock):
        assert "s05" not in {r["student_id"] for r in week_one(teacher)["rows"]}
        db.entries.append(make_entry("new", "s05", "w1", "homework", 5, 5))
        clock.advance(5)  # still inside the 60 s cache window
        assert "s05" not in {r["student_id"] for r in week_one(teacher)["rows"]}

        assert teacher.post(REFRESH).status_code == 200
        assert "s05" in {r["student_id"] for r in week_one(teacher)["rows"]}

    def test_refresh_updates_last_updated(self, teacher, clock):
        week_one(teacher)
        clock.advance(20)
        teacher.post(REFRESH)
        assert last_updated(teacher) == utc(clock.now)

    def test_reports_data_problems(self, teacher, db):
        db.entries.append(make_entry("bad1", "s99", "w1", "homework", 3, 5))
        assert teacher.post(REFRESH).json()["issues"][0]["where"] == "bad1"

    def test_a_second_call_inside_10_seconds_is_429(self, teacher):
        teacher.post(REFRESH)
        response = teacher.post(REFRESH)
        assert response.status_code == 429
        assert response.json() == {"detail": "Please wait 10s before refreshing again."}
        assert response.headers["retry-after"] == "10"

    def test_the_message_counts_down(self, teacher, clock):
        teacher.post(REFRESH)
        clock.advance(3)
        response = teacher.post(REFRESH)
        assert response.status_code == 429
        assert response.json() == {"detail": "Please wait 7s before refreshing again."}
        assert response.headers["retry-after"] == "7"

    def test_partial_seconds_round_up(self, teacher, clock):
        teacher.post(REFRESH)
        clock.advance(3.5)
        assert teacher.post(REFRESH).json() == {"detail": "Please wait 7s before refreshing again."}

    def test_allowed_again_after_10_seconds(self, teacher, clock):
        teacher.post(REFRESH)
        clock.advance(10)
        assert teacher.post(REFRESH).status_code == 200

    def test_a_refused_call_does_not_extend_the_cooldown(self, teacher, clock):
        teacher.post(REFRESH)
        clock.advance(6)
        assert teacher.post(REFRESH).status_code == 429
        clock.advance(4)
        assert teacher.post(REFRESH).status_code == 200

    def test_reading_the_table_does_not_count_as_a_refresh(self, teacher):
        week_one(teacher)
        assert teacher.post(REFRESH).status_code == 200

    def test_a_student_may_not_refresh(self, ada):
        response = ada.post(REFRESH)
        assert response.status_code == 403
        assert isinstance(response.json()["detail"], str)

    def test_a_refused_student_does_not_use_up_the_teachers_turn(self, teacher, ada):
        ada.post(REFRESH)
        assert teacher.post(REFRESH).status_code == 200

    def test_unknown_class_is_404(self, teacher):
        assert teacher.post("/api/classes/nope/refresh").status_code == 404


class TestSourceFailure:
    def test_serves_the_last_snapshot_marked_stale(self, teacher, db, clock):
        good = week_one(teacher)
        db.fail = True
        clock.advance(61)
        body = week_one(teacher)
        assert body["stale"] is True
        assert body["rows"] == good["rows"]
        assert body["last_updated"] == good["last_updated"]

    def test_status_reports_stale_after_a_failed_read(self, teacher, db, clock):
        week_one(teacher)
        db.fail = True
        clock.advance(61)
        week_one(teacher)
        status = teacher.get(STATUS).json()
        assert status["stale"] is True
        assert datetime.fromisoformat(status["last_updated"]) == utc(clock.now - 61)

    def test_bootstrap_is_served_from_the_snapshot_too(self, teacher, db, clock):
        teacher.get("/api/classes/c1")
        db.fail = True
        clock.advance(61)
        assert teacher.get("/api/classes/c1").status_code == 200

    def test_recovers_when_the_source_comes_back(self, teacher, db, clock):
        week_one(teacher)
        db.fail = True
        clock.advance(61)
        assert week_one(teacher)["stale"] is True
        db.fail = False
        body = week_one(teacher)
        assert body["stale"] is False
        assert datetime.fromisoformat(body["last_updated"]) == utc(clock.now)

    def test_refresh_succeeds_with_stale_true_when_a_snapshot_exists(self, teacher, db, clock):
        week_one(teacher)
        started = clock.now
        db.fail = True
        clock.advance(20)
        response = teacher.post(REFRESH)
        assert response.status_code == 200
        body = response.json()
        assert body["stale"] is True
        assert datetime.fromisoformat(body["last_updated"]) == utc(started)

    def test_refresh_is_503_when_there_is_no_snapshot(self, teacher, db):
        db.fail = True
        response = teacher.post(REFRESH)
        assert response.status_code == 503
        assert response.json() == {"detail": "The data source did not respond."}

    def test_a_failed_refresh_still_starts_the_cooldown(self, teacher, db):
        db.fail = True
        teacher.post(REFRESH)
        assert teacher.post(REFRESH).status_code == 429

    def test_no_snapshot_means_503_not_an_empty_table(self, teacher, db):
        db.fail = True
        assert teacher.get(RANKING, params={"week": "w1"}).status_code == 503
