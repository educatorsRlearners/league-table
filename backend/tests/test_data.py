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
    def test_before_any_read_last_updated_is_null(self, instructor):
        assert instructor.get(STATUS).json() == {
            "last_updated": None,
            "stale": False,
            "issues": [],
            "source": {"kind": "toy", "label": "Demo data", "demo": True},
        }

    def test_status_never_triggers_a_fetch(self, instructor, clock):
        instructor.get(STATUS)
        clock.advance(500)
        instructor.get(STATUS)
        assert instructor.get(STATUS).json()["last_updated"] is None

    def test_reports_when_the_source_was_last_read(self, instructor, clock):
        week_one(instructor)
        assert last_updated(instructor) == utc(clock.now)

    def test_a_student_may_read_the_status(self, instructor, ada):
        week_one(instructor)
        assert ada.get(STATUS).status_code == 200

    def test_lists_data_problems(self, instructor, db):
        db.entries.append(make_entry("bad1", "s99", "w1", "homework", 3, 5))
        week_one(instructor)
        assert instructor.get(STATUS).json()["issues"] == [
            {"level": "error", "where": "bad1", "message": 'Unknown student ID "s99"'},
        ]

    def test_unknown_class_is_404(self, instructor):
        assert instructor.get("/api/classes/nope/status").status_code == 404

    def test_works_while_the_source_is_down(self, instructor, db):
        db.fail = True
        response = instructor.get(STATUS)
        assert response.status_code == 200
        assert response.json()["last_updated"] is None


class TestCache:
    def test_reads_within_60_seconds_are_served_from_the_cache(self, instructor, db, clock):
        first = week_one(instructor)
        db.entries.append(make_entry("new", "s05", "w1", "homework", 5, 5))
        clock.advance(59)
        assert week_one(instructor) == first

    def test_a_read_after_60_seconds_picks_up_changes(self, instructor, db, clock):
        week_one(instructor)
        db.entries.append(make_entry("new", "s05", "w1", "homework", 5, 5))
        clock.advance(61)
        body = week_one(instructor)
        assert "s05" in {r["student_id"] for r in body["rows"]}
        assert datetime.fromisoformat(body["last_updated"]) == utc(clock.now)

    def test_last_updated_stays_put_while_cached(self, instructor, clock):
        started = clock.now
        week_one(instructor)
        clock.advance(30)
        assert datetime.fromisoformat(week_one(instructor)["last_updated"]) == utc(started)


class TestRefresh:
    def test_teacher_refresh_succeeds(self, instructor, clock):
        response = instructor.post(REFRESH)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"last_updated", "issues", "stale"}
        assert body["stale"] is False
        assert datetime.fromisoformat(body["last_updated"]) == utc(clock.now)

    def test_bypasses_the_cache(self, instructor, db, clock):
        assert "s05" not in {r["student_id"] for r in week_one(instructor)["rows"]}
        db.entries.append(make_entry("new", "s05", "w1", "homework", 5, 5))
        clock.advance(5)  # still inside the 60 s cache window
        assert "s05" not in {r["student_id"] for r in week_one(instructor)["rows"]}

        assert instructor.post(REFRESH).status_code == 200
        assert "s05" in {r["student_id"] for r in week_one(instructor)["rows"]}

    def test_refresh_updates_last_updated(self, instructor, clock):
        week_one(instructor)
        clock.advance(20)
        instructor.post(REFRESH)
        assert last_updated(instructor) == utc(clock.now)

    def test_reports_data_problems(self, instructor, db):
        db.entries.append(make_entry("bad1", "s99", "w1", "homework", 3, 5))
        assert instructor.post(REFRESH).json()["issues"][0]["where"] == "bad1"

    def test_a_second_call_inside_10_seconds_is_429(self, instructor):
        instructor.post(REFRESH)
        response = instructor.post(REFRESH)
        assert response.status_code == 429
        assert response.json() == {"detail": "Please wait 10s before refreshing again."}
        assert response.headers["retry-after"] == "10"

    def test_the_message_counts_down(self, instructor, clock):
        instructor.post(REFRESH)
        clock.advance(3)
        response = instructor.post(REFRESH)
        assert response.status_code == 429
        assert response.json() == {"detail": "Please wait 7s before refreshing again."}
        assert response.headers["retry-after"] == "7"

    def test_partial_seconds_round_up(self, instructor, clock):
        instructor.post(REFRESH)
        clock.advance(3.5)
        assert instructor.post(REFRESH).json() == {"detail": "Please wait 7s before refreshing again."}

    def test_allowed_again_after_10_seconds(self, instructor, clock):
        instructor.post(REFRESH)
        clock.advance(10)
        assert instructor.post(REFRESH).status_code == 200

    def test_a_refused_call_does_not_extend_the_cooldown(self, instructor, clock):
        instructor.post(REFRESH)
        clock.advance(6)
        assert instructor.post(REFRESH).status_code == 429
        clock.advance(4)
        assert instructor.post(REFRESH).status_code == 200

    def test_reading_the_table_does_not_count_as_a_refresh(self, instructor):
        week_one(instructor)
        assert instructor.post(REFRESH).status_code == 200

    def test_a_student_may_not_refresh(self, ada):
        response = ada.post(REFRESH)
        assert response.status_code == 403
        assert isinstance(response.json()["detail"], str)

    def test_a_refused_student_does_not_use_up_the_teachers_turn(self, instructor, ada):
        ada.post(REFRESH)
        assert instructor.post(REFRESH).status_code == 200

    def test_unknown_class_is_404(self, instructor):
        assert instructor.post("/api/classes/nope/refresh").status_code == 404


class TestSourceFailure:
    def test_serves_the_last_snapshot_marked_stale(self, instructor, db, clock):
        good = week_one(instructor)
        db.fail = True
        clock.advance(61)
        body = week_one(instructor)
        assert body["stale"] is True
        assert body["rows"] == good["rows"]
        assert body["last_updated"] == good["last_updated"]

    def test_status_reports_stale_after_a_failed_read(self, instructor, db, clock):
        week_one(instructor)
        db.fail = True
        clock.advance(61)
        week_one(instructor)
        status = instructor.get(STATUS).json()
        assert status["stale"] is True
        assert datetime.fromisoformat(status["last_updated"]) == utc(clock.now - 61)

    def test_bootstrap_is_served_from_the_snapshot_too(self, instructor, db, clock):
        instructor.get("/api/classes/c1")
        db.fail = True
        clock.advance(61)
        assert instructor.get("/api/classes/c1").status_code == 200

    def test_recovers_when_the_source_comes_back(self, instructor, db, clock):
        week_one(instructor)
        db.fail = True
        clock.advance(61)
        assert week_one(instructor)["stale"] is True
        db.fail = False
        body = week_one(instructor)
        assert body["stale"] is False
        assert datetime.fromisoformat(body["last_updated"]) == utc(clock.now)

    def test_refresh_succeeds_with_stale_true_when_a_snapshot_exists(self, instructor, db, clock):
        week_one(instructor)
        started = clock.now
        db.fail = True
        clock.advance(20)
        response = instructor.post(REFRESH)
        assert response.status_code == 200
        body = response.json()
        assert body["stale"] is True
        assert datetime.fromisoformat(body["last_updated"]) == utc(started)

    def test_refresh_is_503_when_there_is_no_snapshot(self, instructor, db):
        db.fail = True
        response = instructor.post(REFRESH)
        assert response.status_code == 503
        assert response.json() == {"detail": "The data source did not respond."}

    def test_a_failed_refresh_still_starts_the_cooldown(self, instructor, db):
        db.fail = True
        instructor.post(REFRESH)
        assert instructor.post(REFRESH).status_code == 429

    def test_no_snapshot_means_503_not_an_empty_table(self, instructor, db):
        db.fail = True
        assert instructor.get(RANKING, params={"week": "w1"}).status_code == 503
