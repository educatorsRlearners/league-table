"""The seeded demo class: 24 students, 16 weeks and 5 criteria, plus demo commitments.

Reproducible: the scores come from a seeded generator, and the term is anchored to the day
you give it (today is in week 16) so the edit window works on a real clock. No real student
data ever lives here, and toy mode only ever uses the in-memory store.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from app.datasource import Entry, Student
from app.identity import hash_code
from app.mock_db import MockDatabase
from app.models import Class, Criterion, DemoAccount, Week
from app.store import AdjustmentSettings, LogEntry, MemoryStore, StoredAccount

MASK = 0xFFFFFFFF


def mulberry32(seed: int):
    state = seed & MASK

    def next_float() -> float:
        nonlocal state
        state = (state + 0x6D2B79F5) & MASK
        t = state
        t = ((t ^ (t >> 15)) * (t | 1)) & MASK
        t ^= (t + ((t ^ (t >> 7)) * (t | 61))) & MASK
        return ((t ^ (t >> 14)) & MASK) / 4294967296

    return next_float


def js_round(value: float) -> int:
    """Math.round: halves round up, unlike Python's banker's rounding."""
    return math.floor(value + 0.5)


NAMES = [
    "Amara Okonkwo", "Ben Halvorsen", "Cleo Marchetti", "Dara Whitfield", "Elif Demir",
    "Farid Nasser", "Greta Lindqvist", "Hugo Ferreira", "Imani Blake", "Jonas Reuter",
    "Kiara Mensah", "Liam Donoghue", "Mira Chandra", "Nils Aaltonen", "Odette Laurent",
    "Pablo Guerrero", "Quinn Alderton", "Rosa Ibarra", "Samir Haddad", "Tessa Vermeulen",
    "Ugo Bianchi", "Vera Novak", "Wes Carmichael", "Xanthe Poulos",
]

NICKNAMES = {
    "Amara Okonkwo": "Ammo", "Ben Halvorsen": "Benno", "Cleo Marchetti": "Clee", "Wes Carmichael": "Wez",
}

# key, label, unit, default weight, points possible, weeks it is recorded (None = every week)
CRITERIA = [
    ("homework", "Homework", "tasks on time", 25, 5, None),
    ("attendance", "Attendance", "sessions", 20, 5, None),
    ("participation", "Participation", "points", 20, 25, None),
    ("project", "Project scores", "marks", 25, 100, {4, 8, 12, 16}),
    ("quizzes", "Quizzes", "marks", 10, 20, None),
]

CLASS = Class(id="c1", external_id="demo:phys101-b", name="Introductory Physics · Group B", term_id="t1")
WEEK_COUNT = 16
LATE_JOINER = "Xanthe Poulos"  # joins in week 4
ZERO_WEEK = ("Pablo Guerrero", 6)
PERFECT_WEEK = ("Amara Okonkwo", 5)
MISSING_ENTRY = ("Rosa Ibarra", "participation", 7)
TIE_WEEK = 9  # Liam Donoghue mirrors Farid Nasser; neither has commitments

FLAG_HOURS = AdjustmentSettings().flag_hours
INSTRUCTOR_PASSCODE = "demo-instructor"
INSTRUCTOR_ID = "a1"
UTC = timezone.utc


def term_start(today: date) -> date:
    """The Monday of week 1, so that `today` falls in week 16."""
    return today - timedelta(days=today.weekday()) - timedelta(weeks=WEEK_COUNT - 1)


def _weeks(start_of_term: date) -> list[Week]:
    weeks = []
    for i in range(WEEK_COUNT):
        start = start_of_term + timedelta(days=7 * i)
        weeks.append(
            Week(
                id=f"w{i + 1}", term_id="t1", week_number=i + 1,
                start_date=start, end_date=start + timedelta(days=4),
            )
        )
    return weeks


def _students() -> list[Student]:
    return [
        Student(
            id=f"s{i + 1:02d}",
            external_id=f"demo:stu-{4000 + i}",
            class_id="c1",
            display_name=name,
            nickname=NICKNAMES.get(name),
            avatar_url=None,
            active=True,
        )
        for i, name in enumerate(NAMES)
    ]


def _entries(students: list[Student], weeks: list[Week]) -> list[Entry]:
    rng = mulberry32(20260920)

    # A stable per-student, per-criterion ability, plus week-to-week noise, so the
    # table has a believable order that still moves.
    ability: dict[str, dict[str, float]] = {}
    for student in students:
        base = 0.45 + rng() * 0.5
        ability[student.id] = {
            key: min(0.99, max(0.15, base + (rng() - 0.5) * 0.3)) for key, *_ in CRITERIA
        }

    rows: list[dict] = []
    for week in weeks:
        for key, _label, _unit, _weight, possible, only_weeks in CRITERIA:
            if only_weeks is not None and week.week_number not in only_weeks:
                continue
            for student in students:
                if student.display_name == LATE_JOINER and week.week_number < 4:
                    continue
                noise = (rng() - 0.5) * 0.28
                frac = min(1.0, max(0.0, ability[student.id][key] + noise))
                # Seeded edge cases
                if (student.display_name, week.week_number) == PERFECT_WEEK:
                    frac = 1.0
                if (student.display_name, week.week_number) == ZERO_WEEK:
                    frac = 0.0
                earned = js_round(frac * possible)
                if (student.display_name, key, week.week_number) == MISSING_ENTRY:
                    continue
                rows.append(
                    {
                        "id": f"e{len(rows) + 1}",
                        "student_id": student.id,
                        "criterion_id": key,
                        "week_id": week.id,
                        "earned": earned,
                        "possible": possible,
                        "recorded_at": f"{week.end_date.isoformat()}T16:00:00Z",
                    }
                )

    # A seeded exact tie: Liam Donoghue mirrors Farid Nasser. Neither has commitments,
    # so their adjusted scores match too.
    farid = next(s.id for s in students if s.display_name == "Farid Nasser")
    liam = next(s.id for s in students if s.display_name == "Liam Donoghue")
    tie_week = f"w{TIE_WEEK}"
    farid_scores = {r["criterion_id"]: r["earned"] for r in rows if r["week_id"] == tie_week and r["student_id"] == farid}
    for row in rows:
        if row["week_id"] == tie_week and row["student_id"] == liam and row["criterion_id"] in farid_scores:
            row["earned"] = farid_scores[row["criterion_id"]]

    return [Entry(**row) for row in rows]


def _account_code(name: str) -> str:
    return f"demo-{name.split()[0].lower()}"


# Students shown on the sign-in screen, each chosen to show a different commitments state.
DEMO_STUDENTS = {
    "Amara Okonkwo": "approved baseline and a weekly update this week",
    "Ben Halvorsen": "approved baseline, factor at the cap",
    "Cleo Marchetti": "baseline pending approval",
    "Dara Whitfield": "baseline rejected",
    "Rosa Ibarra": "no commitments entered",
}


@dataclass
class Toy:
    db: MockDatabase
    store: MemoryStore
    demo_accounts: list[DemoAccount]
    instructor_passcode: str


def build_toy(today: date) -> Toy:
    """The demo class with `today` in week 16, and the in-memory store seeded to match."""
    start = term_start(today)
    weeks = _weeks(start)
    students = _students()
    db = MockDatabase(
        kind="toy",
        label="Demo data",
        classes=[CLASS.model_copy()],
        students=students,
        criteria=[
            Criterion(
                id=key, class_id="c1", key=key, label=label, unit=unit,
                default_weight=weight, sort_order=order,
            )
            for order, (key, label, unit, weight, _possible, _weeks_) in enumerate(CRITERIA)
        ],
        weeks=weeks,
        entries=_entries(students, weeks),
    )

    accounts = [StoredAccount(INSTRUCTOR_ID, "instructor", None, "demo:instructor", None)]
    accounts += [
        StoredAccount(f"a{i + 2}", "student", s.id, f"demo:{s.display_name.split()[0].lower()}",
                      hash_code(_account_code(s.display_name)))
        for i, s in enumerate(students)
    ]
    store = MemoryStore(accounts)
    _seed_commitments(store, start, students, accounts)

    by_name = {s.display_name: s for s in students}
    demo = [
        DemoAccount(id=INSTRUCTOR_ID, role="instructor", student_id=None, external_id="demo:instructor",
                    name="Instructor", code=INSTRUCTOR_PASSCODE)
    ]
    for name in DEMO_STUDENTS:
        account = next(a for a in accounts if a.student_id == by_name[name].id)
        demo.append(
            DemoAccount(id=account.id, role="student", student_id=account.student_id,
                        external_id=account.external_id, name=name, code=_account_code(name))
        )
    return Toy(db, store, demo, INSTRUCTOR_PASSCODE)


def _seed_commitments(store: MemoryStore, start: date, students: list[Student], accounts: list[StoredAccount]) -> None:
    """One student in each commitments state the spec lists, written through the store so the
    change log is complete."""
    student_id = {s.display_name: s.id for s in students}
    account_id = {a.student_id: a.id for a in accounts if a.student_id}

    def at(week: int, day: int = 0, hour: int = 9) -> str:
        moment = datetime.combine(start + timedelta(weeks=week - 1, days=day), time(hour), tzinfo=UTC)
        return moment.isoformat()

    def submit(name: str, hours: dict, week: int) -> str:
        sid = student_id[name]
        stamp = at(week)
        baseline = store.save_baseline(
            sid, hours, stamp, LogEntry("", account_id[sid], "baseline_submitted", sid, None, None, {"hours": hours}, stamp)
        )
        return baseline.id

    def decide(baseline_id: str, name: str, approve: bool, effective: int | None, week: int) -> None:
        sid = student_id[name]
        stamp = at(week, 1)
        new = {"status": "approved", "effective_from_week": effective} if approve else {"status": "rejected"}
        store.decide_baseline(
            baseline_id, status="approved" if approve else "rejected", effective_from_week=effective,
            decided_by=INSTRUCTOR_ID, at=stamp,
            entry=LogEntry("", INSTRUCTOR_ID, "baseline_approved" if approve else "baseline_rejected",
                           sid, None, {"status": "pending"}, new, stamp),
        )

    def weekly(name: str, week: int, hours: dict, old: dict | None) -> str:
        sid = student_id[name]
        stamp = at(week, 2)
        update = store.save_weekly_update(
            sid, f"w{week}", hours, stamp,
            LogEntry("", account_id[sid], "weekly_update", sid, f"w{week}",
                     None if old is None else {"hours": old}, {"hours": hours}, stamp,
                     flagged=old is not None and abs(sum(hours.values()) - sum(old.values())) > FLAG_HOURS),
        )
        return update.id

    # Amara: approved from week 3, and a bigger week now. The change stays under the review threshold.
    amara = {"work": 12.0, "childcare": 6.0, "eldercare": 0.0}
    decide(submit("Amara Okonkwo", amara, 1), "Amara Okonkwo", True, 3, 1)
    weekly("Amara Okonkwo", WEEK_COUNT, {"work": 16.0, "childcare": 6.0, "eldercare": 0.0}, amara)

    # Ben: 30 weighted hours would be x1.30, so the factor stops at the x1.25 cap.
    decide(submit("Ben Halvorsen", {"work": 30.0, "childcare": 0.0, "eldercare": 0.0}, 1), "Ben Halvorsen", True, 1, 1)

    # Cleo: waiting for the instructor.
    submit("Cleo Marchetti", {"work": 10.0, "childcare": 10.0, "eldercare": 5.0}, WEEK_COUNT)

    # Dara: rejected.
    decide(submit("Dara Whitfield", {"work": 60.0, "childcare": 40.0, "eldercare": 20.0}, 2), "Dara Whitfield", False, None, 2)

    # Elif: approved from week 5; a large weekly update in week 15 was flagged and reversed.
    elif_hours = {"work": 8.0, "childcare": 0.0, "eldercare": 10.0}
    decide(submit("Elif Demir", elif_hours, 3), "Elif Demir", True, 5, 3)
    update_id = weekly("Elif Demir", WEEK_COUNT - 1, {"work": 40.0, "childcare": 0.0, "eldercare": 10.0}, elif_hours)
    stamp = at(WEEK_COUNT - 1, 3)
    store.reverse_weekly_update(
        update_id, reversed_by=INSTRUCTOR_ID, at=stamp,
        entry=LogEntry("", INSTRUCTOR_ID, "weekly_reversed", student_id["Elif Demir"], f"w{WEEK_COUNT - 1}",
                       {"hours": {"work": 40.0, "childcare": 0.0, "eldercare": 10.0}}, {"hours": elif_hours}, stamp),
    )

    # Greta: a baseline change part-way through. Earlier weeks keep the first factor.
    greta_1 = {"work": 10.0, "childcare": 0.0, "eldercare": 0.0}
    decide(submit("Greta Lindqvist", greta_1, 1), "Greta Lindqvist", True, 1, 1)
    decide(submit("Greta Lindqvist", {"work": 20.0, "childcare": 0.0, "eldercare": 0.0}, 8), "Greta Lindqvist", True, 9, 8)
