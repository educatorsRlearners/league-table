"""Every AppStore adapter must pass this suite; that is what makes swapping one for another safe."""

import pytest

from app.identity import hash_code
from app.store import AdjustmentSettings, LogEntry, MemoryStore, Settings, StoredAccount

HOURS = {"work": 10.0, "childcare": 0.0, "eldercare": 0.0}
NOW = "2027-01-15T09:00:00+00:00"


def log(action="x", student="s01", week=None, old=None, new=None):
    return LogEntry("", "a2", action, student, week, old, new, NOW)


@pytest.fixture(params=["memory"])
def store(request):
    return MemoryStore(
        [
            StoredAccount("a1", "instructor", None, "demo:instructor", None),
            StoredAccount("a2", "student", "s01", "demo:ada", hash_code("ada-code")),
        ]
    )


class TestAccounts:
    def test_finds_an_account_by_id_and_by_code_hash(self, store):
        assert store.get_account("a2").student_id == "s01"
        assert store.get_account_by_code(hash_code("ada-code")).id == "a2"

    def test_an_unknown_id_or_hash_is_none(self, store):
        assert store.get_account("zzz") is None
        assert store.get_account_by_code(hash_code("nope")) is None
        assert store.get_account_by_code("") is None

    def test_an_account_without_a_code_is_never_found_by_code(self, store):
        assert store.get_account_by_code(None) is None

    def test_lists_every_account(self, store):
        assert [a.id for a in store.list_accounts()] == ["a1", "a2"]


class TestBaselines:
    def test_a_saved_baseline_is_pending_and_gets_an_id(self, store):
        baseline = store.save_baseline("s01", HOURS, NOW, log("baseline_submitted"))
        assert (baseline.status, baseline.hours, baseline.submitted_at) == ("pending", HOURS, NOW)
        assert store.get_baseline(baseline.id) == baseline

    def test_the_stored_hours_are_a_copy(self, store):
        hours = dict(HOURS)
        baseline = store.save_baseline("s01", hours, NOW, log())
        hours["work"] = 99
        assert store.get_baseline(baseline.id).hours["work"] == 10

    def test_saving_again_supersedes_the_pending_one(self, store):
        first = store.save_baseline("s01", HOURS, NOW, log())
        second = store.save_baseline("s01", {**HOURS, "work": 20.0}, NOW, log())
        assert store.get_baseline(first.id).status == "superseded"
        assert store.get_baseline(second.id).status == "pending"

    def test_lists_by_student(self, store):
        store.save_baseline("s01", HOURS, NOW, log())
        store.save_baseline("s02", HOURS, NOW, log(student="s02"))
        assert [b.student_id for b in store.list_baselines("s02")] == ["s02"]
        assert len(store.list_baselines()) == 2

    def test_approving_records_who_when_and_from_which_week(self, store):
        baseline = store.save_baseline("s01", HOURS, NOW, log())
        decided = store.decide_baseline(
            baseline.id, status="approved", effective_from_week=3, decided_by="a1", at=NOW, entry=log("baseline_approved")
        )
        assert (decided.status, decided.effective_from_week, decided.decided_by, decided.decided_at) == (
            "approved", 3, "a1", NOW,
        )
        assert decided.decision_seq is not None

    def test_rejecting_has_no_effective_week(self, store):
        baseline = store.save_baseline("s01", HOURS, NOW, log())
        decided = store.decide_baseline(
            baseline.id, status="rejected", effective_from_week=5, decided_by="a1", at=NOW, entry=log()
        )
        assert (decided.status, decided.effective_from_week, decided.decision_seq) == ("rejected", None, None)

    def test_a_later_approval_supersedes_the_earlier_one_but_keeps_its_week(self, store):
        one = store.save_baseline("s01", HOURS, NOW, log())
        store.decide_baseline(one.id, status="approved", effective_from_week=1, decided_by="a1", at=NOW, entry=log())
        two = store.save_baseline("s01", {**HOURS, "work": 20.0}, NOW, log())
        second = store.decide_baseline(two.id, status="approved", effective_from_week=9, decided_by="a1", at=NOW, entry=log())
        old = store.get_baseline(one.id)
        assert (old.status, old.effective_from_week) == ("superseded", 1)
        assert second.decision_seq > old.decision_seq

    def test_only_a_pending_baseline_can_be_decided(self, store):
        baseline = store.save_baseline("s01", HOURS, NOW, log())
        store.decide_baseline(baseline.id, status="rejected", effective_from_week=None, decided_by="a1", at=NOW, entry=log())
        with pytest.raises(LookupError):
            store.decide_baseline(baseline.id, status="approved", effective_from_week=1, decided_by="a1", at=NOW, entry=log())
        with pytest.raises(LookupError):
            store.decide_baseline("b99", status="approved", effective_from_week=1, decided_by="a1", at=NOW, entry=log())

    def test_a_failed_decision_writes_no_log_entry(self, store):
        with pytest.raises(LookupError):
            store.decide_baseline("b99", status="approved", effective_from_week=1, decided_by="a1", at=NOW, entry=log())
        assert store.list_log() == []


class TestWeeklyUpdates:
    def test_a_saved_update_is_linked_to_its_log_entry(self, store):
        update = store.save_weekly_update("s01", "w3", HOURS, NOW, log("weekly_update", week="w3"))
        assert store.list_log()[-1].id == update.entry_id
        assert (update.hours, update.reversed_at) == (HOURS, None)

    def test_a_reset_is_an_update_without_hours(self, store):
        assert store.save_weekly_update("s01", "w3", None, NOW, log("weekly_reset")).hours is None

    def test_updates_are_kept_not_overwritten(self, store):
        store.save_weekly_update("s01", "w3", HOURS, NOW, log())
        store.save_weekly_update("s01", "w3", {**HOURS, "work": 20.0}, NOW, log())
        assert [u.hours["work"] for u in store.list_weekly_updates("s01")] == [10, 20]

    def test_reversing_marks_who_and_when(self, store):
        update = store.save_weekly_update("s01", "w3", HOURS, NOW, log())
        reversed_ = store.reverse_weekly_update(update.id, reversed_by="a1", at=NOW, entry=log("weekly_reversed"))
        assert (reversed_.reversed_by, reversed_.reversed_at) == ("a1", NOW)
        assert store.list_weekly_updates("s01")[0].reversed_at == NOW

    def test_an_update_cannot_be_reversed_twice(self, store):
        update = store.save_weekly_update("s01", "w3", HOURS, NOW, log())
        store.reverse_weekly_update(update.id, reversed_by="a1", at=NOW, entry=log())
        with pytest.raises(LookupError):
            store.reverse_weekly_update(update.id, reversed_by="a1", at=NOW, entry=log())
        assert len(store.list_log()) == 2  # the failed attempt wrote nothing


class TestLog:
    def test_entries_come_back_oldest_first_with_ids(self, store):
        store.append_log(log("one"))
        store.append_log(log("two"))
        entries = store.list_log()
        assert [e.action for e in entries] == ["one", "two"]
        assert len({e.id for e in entries}) == 2 and "" not in {e.id for e in entries}

    def test_can_be_filtered_by_student(self, store):
        store.append_log(log("one", student="s01"))
        store.append_log(log("two", student="s02"))
        assert [e.action for e in store.list_log("s02")] == ["two"]

    def test_a_change_and_its_entry_are_saved_together(self, store):
        store.save_baseline("s01", HOURS, NOW, log("baseline_submitted"))
        assert [e.action for e in store.list_log()] == ["baseline_submitted"]


class TestSettings:
    def test_defaults_when_nothing_is_saved(self, store):
        settings = store.get_settings("c1")
        assert settings.weights is None
        assert (settings.adjustment.rate, settings.adjustment.cap) == (0.01, 1.25)
        assert settings.adjustment.type_weights == {"work": 1.0, "childcare": 1.0, "eldercare": 1.0}

    def test_saved_settings_come_back(self, store):
        saved = Settings(weights={"homework": 100.0}, adjustment=AdjustmentSettings(rate=0.02, cap=1.5))
        store.save_settings("c1", saved, log("settings_changed", student=None))
        assert store.get_settings("c1") == saved
        assert store.get_settings("other") == Settings()
        assert [e.action for e in store.list_log()] == ["settings_changed"]
