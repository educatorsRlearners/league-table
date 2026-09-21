"""The adjustment rules on their own, checked against the spec's worked numbers."""

from datetime import date, timedelta

import pytest

from app.commitments import (
    CommitmentBook, InvalidHours, adjust, current_week, editable_weeks, factor_for, validate_adjustment,
    validate_hours,
)
from app.models import Week
from app.store import AdjustmentSettings, Baseline, WeeklyUpdate

PARAMS = AdjustmentSettings()


def weeks(count=16, first=date(2026, 9, 28)):
    return [
        Week(id=f"w{n}", term_id="t1", week_number=n, start_date=first + timedelta(weeks=n - 1),
             end_date=first + timedelta(weeks=n - 1, days=4))
        for n in range(1, count + 1)
    ]


class TestValidateHours:
    def test_missing_types_count_as_zero(self):
        assert validate_hours({"work": 10}) == {"work": 10, "childcare": 0, "eldercare": 0}

    def test_half_hours_are_fine(self):
        assert validate_hours({"work": 7.5})["work"] == 7.5

    @pytest.mark.parametrize(
        "hours,message",
        [
            ({"work": 7.25}, "steps of 0.5"),
            ({"work": -1}, "zero or more"),
            ({"work": 80.5}, "at most 80"),
            ({"work": 80, "childcare": 40, "eldercare": 1}, "120 hours"),
            ({"gardening": 3}, "Unknown commitment type"),
            ({"work": float("nan")}, "zero or more"),
        ],
    )
    def test_rejects_what_breaks_a_limit(self, hours, message):
        with pytest.raises(InvalidHours, match=message):
            validate_hours(hours)

    def test_the_limits_themselves_are_allowed(self):
        assert validate_hours({"work": 80, "childcare": 40, "eldercare": 0})["work"] == 80


class TestFactor:
    @pytest.mark.parametrize("hours,factor", [(0, 1.0), (10, 1.10), (20, 1.20), (25, 1.25), (26, 1.25), (80, 1.25)])
    def test_the_spec_table_and_the_cap(self, hours, factor):
        assert factor_for(hours, PARAMS) == pytest.approx(factor)

    def test_no_hours_can_push_the_factor_past_the_cap(self):
        assert max(factor_for(h / 2, PARAMS) for h in range(0, 241)) == 1.25


class TestAdjust:
    def test_the_spec_worked_example(self):
        # 80 raw with 12 hours of work and 6 of child care: 18 weighted hours, x1.18.
        result = adjust(80, {"work": 12, "childcare": 6, "eldercare": 0}, PARAMS)
        assert result.weighted_total == 18
        assert result.factor == pytest.approx(1.18)
        assert result.adjusted == pytest.approx(94.4)
        assert result.capped is False

    def test_a_score_over_100_is_clipped_and_says_so(self):
        result = adjust(92, {"work": 20, "childcare": 0, "eldercare": 0}, PARAMS)
        assert result.factor == pytest.approx(1.20)
        assert result.adjusted == 100
        assert result.capped is True

    def test_landing_exactly_on_100_is_not_capped(self):
        assert adjust(80, {"work": 25, "childcare": 0, "eldercare": 0}, PARAMS).capped is False

    def test_without_hours_the_factor_is_neutral(self):
        result = adjust(83.3, None, PARAMS)
        assert (result.factor, result.adjusted, result.capped, result.hours) == (1.0, 83.3, False, None)

    def test_each_type_counts_at_its_own_weight(self):
        params = AdjustmentSettings(type_weights={"work": 1.0, "childcare": 1.5, "eldercare": 2.0})
        result = adjust(50, {"work": 10, "childcare": 10, "eldercare": 10}, params)
        assert result.weighted == {"work": 10, "childcare": 15, "eldercare": 20}
        assert result.weighted_total == 45
        assert result.factor == 1.25  # 1.45 held at the cap

    def test_the_rate_and_cap_can_be_tuned(self):
        params = AdjustmentSettings(rate=0.02, cap=1.5)
        assert factor_for(10, params) == pytest.approx(1.2)
        assert factor_for(100, params) == 1.5

    def test_a_score_can_never_exceed_100(self):
        assert all(adjust(raw, {"work": 80}, PARAMS).adjusted <= 100 for raw in range(0, 101, 5))


class TestValidateAdjustment:
    @pytest.mark.parametrize(
        "changes",
        [{"rate": -0.01}, {"rate": 1.5}, {"cap": 0.99}, {"cap": 3.5}, {"flag_hours": -1}, {"type_weights": {"work": 1}}],
    )
    def test_rejects_out_of_range_values(self, changes):
        with pytest.raises(InvalidHours):
            validate_adjustment(AdjustmentSettings(**changes))


def baseline(bid, student, status, effective=None, seq=None, **hours):
    return Baseline(bid, student, {"work": 0.0, "childcare": 0.0, "eldercare": 0.0} | hours, status,
                    "2026-10-01T09:00:00+00:00", effective_from_week=effective, decision_seq=seq)


def update(uid, student, week_id, hours, reversed_=False):
    return WeeklyUpdate(uid, student, week_id, hours, "2026-10-05T09:00:00+00:00", "l1",
                        reversed_by="a1" if reversed_ else None, reversed_at="2026-10-06T09:00:00+00:00" if reversed_ else None)


W = weeks()


def hours_in(book, week_number, student="s01"):
    return book.hours_for(student, W[week_number - 1])


class TestCommitmentBook:
    def test_no_baseline_means_no_adjustment(self):
        assert hours_in(CommitmentBook([], []), 5) is None

    @pytest.mark.parametrize("status", ["pending", "rejected"])
    def test_a_baseline_that_is_not_approved_has_no_effect(self, status):
        assert hours_in(CommitmentBook([baseline("b1", "s01", status, work=10)], []), 5) is None

    def test_an_approved_baseline_counts_from_its_effective_week(self):
        book = CommitmentBook([baseline("b1", "s01", "approved", effective=3, seq=1, work=10)], [])
        assert [hours_in(book, n) is not None for n in (1, 2, 3, 4)] == [False, False, True, True]

    def test_a_weekly_update_replaces_the_baseline_for_that_week_only(self):
        book = CommitmentBook(
            [baseline("b1", "s01", "approved", effective=1, seq=1, work=10)],
            [update("u1", "s01", "w4", {"work": 30.0})],
        )
        assert hours_in(book, 4)["work"] == 30
        assert hours_in(book, 3)["work"] == hours_in(book, 5)["work"] == 10

    def test_a_weekly_update_has_no_effect_before_the_baseline_is_approved(self):
        book = CommitmentBook([baseline("b1", "s01", "pending", work=10)], [update("u1", "s01", "w4", {"work": 30.0})])
        assert hours_in(book, 4) is None

    def test_a_weekly_update_has_no_effect_in_weeks_before_the_effective_week(self):
        book = CommitmentBook(
            [baseline("b1", "s01", "approved", effective=5, seq=1, work=10)], [update("u1", "s01", "w4", {"work": 30.0})]
        )
        assert hours_in(book, 4) is None

    def test_a_reversed_update_is_ignored(self):
        book = CommitmentBook(
            [baseline("b1", "s01", "approved", effective=1, seq=1, work=10)],
            [update("u1", "s01", "w4", {"work": 30.0}, reversed_=True)],
        )
        assert hours_in(book, 4)["work"] == 10

    def test_reversing_the_latest_update_restores_the_one_before(self):
        book = CommitmentBook(
            [baseline("b1", "s01", "approved", effective=1, seq=1, work=10)],
            [update("u1", "s01", "w4", {"work": 20.0}), update("u2", "s01", "w4", {"work": 40.0}, reversed_=True)],
        )
        assert hours_in(book, 4)["work"] == 20

    def test_a_reset_returns_to_the_baseline(self):
        book = CommitmentBook(
            [baseline("b1", "s01", "approved", effective=1, seq=1, work=10)],
            [update("u1", "s01", "w4", {"work": 30.0}), update("u2", "s01", "w4", None)],
        )
        assert hours_in(book, 4)["work"] == 10

    def test_a_later_approval_replaces_the_old_one_only_from_its_week(self):
        book = CommitmentBook(
            [baseline("b1", "s01", "superseded", effective=1, seq=1, work=10),
             baseline("b2", "s01", "approved", effective=9, seq=2, work=20)],
            [],
        )
        assert hours_in(book, 8)["work"] == 10
        assert hours_in(book, 9)["work"] == 20

    def test_a_pending_baseline_that_was_replaced_never_counts(self):
        book = CommitmentBook([baseline("b1", "s01", "superseded", work=50)], [])
        assert hours_in(book, 5) is None

    def test_students_are_independent(self):
        book = CommitmentBook([baseline("b1", "s01", "approved", effective=1, seq=1, work=10)], [])
        assert hours_in(book, 5, "s02") is None


class TestEditWindow:
    def test_the_current_week_is_found_from_the_date(self):
        assert current_week(W, date(2026, 9, 28)).week_number == 1
        assert current_week(W, date(2026, 10, 4)).week_number == 1  # Sunday still belongs to week 1
        assert current_week(W, date(2026, 10, 5)).week_number == 2

    def test_outside_the_term_there_is_no_current_week(self):
        assert current_week(W, date(2026, 9, 27)) is None
        assert current_week(W, date(2027, 1, 18)) is None

    def test_the_current_and_previous_week_can_be_edited(self):
        assert [w.week_number for w in editable_weeks(W, date(2026, 10, 21))] == [3, 4]

    def test_in_week_one_only_week_one_can_be_edited(self):
        assert [w.week_number for w in editable_weeks(W, date(2026, 9, 30))] == [1]

    def test_the_last_week_runs_seven_days(self):
        assert current_week(W, date(2027, 1, 17)).week_number == 16
        assert editable_weeks(W, date(2027, 1, 18)) == []
