"""The seeded demo class: a port of frontend/services/mockSource.js.

The random generator and the order it is consumed in match the JavaScript, so the
frontend's toy data and this backend's are the same class. No real student data
ever lives here.
"""

import math
from datetime import date, timedelta

from app.datasource import Entry, Student
from app.mock_db import MockAccount, MockDatabase
from app.models import Class, Criterion, Week

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
    "Ugo Bianchi", "Vera Novak", "Wes Carmichael", "Xanthe Poulos", "Yusuf Kaya",
    "Zara Mbeki", "Aiden Rourke", "Bianca Serrano", "Caspar Wendt", "Delphine Roy",
    "Eero Virtanen", "Freya Ashdown", "Gideon Stark", "Hana Yamashita", "Isla Bennett",
]

NICKNAMES = {
    "Amara Okonkwo": "Ammo", "Ben Halvorsen": "Benno", "Cleo Marchetti": "Clee",
    "Wes Carmichael": "Wez", "Zara Mbeki": "Z", "Isla Bennett": "Izzy",
}

# key, label, unit, default weight, points possible, weeks it is recorded (None = every week)
CRITERIA = [
    ("homework", "Homework", "tasks on time", 25, 5, None),
    ("attendance", "Attendance", "sessions", 20, 5, None),
    ("participation", "Participation", "points", 20, 25, None),
    ("project", "Project scores", "marks", 25, 100, {2, 5, 8, 10}),
    ("quizzes", "Quizzes", "marks", 10, 20, None),
]

CLASS = Class(id="c1", external_id="clever:sec-4821", name="Year 10 Physics · Set B", term_id="t1")
WEEK_COUNT = 10
TERM_START = date(2026, 1, 5)
LATE_JOINER = "Isla Bennett"  # joins in week 4


def _weeks() -> list[Week]:
    weeks = []
    for i in range(WEEK_COUNT):
        start = TERM_START + timedelta(days=7 * i)
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
            external_id=f"clever:stu-{4000 + i}",
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
                if student.display_name == "Amara Okonkwo" and week.week_number == 5:
                    frac = 1.0  # a perfect week
                if student.display_name == "Gideon Stark" and week.week_number == 6:
                    frac = 0.0  # a zero week
                earned = js_round(frac * possible)
                # A missing entry: Rosa Ibarra has no participation recorded in week 7
                if student.display_name == "Rosa Ibarra" and key == "participation" and week.week_number == 7:
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

    # A seeded exact tie in week 9: Liam Donoghue mirrors Ben Halvorsen.
    ben = next(s.id for s in students if s.display_name == "Ben Halvorsen")
    liam = next(s.id for s in students if s.display_name == "Liam Donoghue")
    ben_w9 = {r["criterion_id"]: r["earned"] for r in rows if r["week_id"] == "w9" and r["student_id"] == ben}
    for row in rows:
        if row["week_id"] == "w9" and row["student_id"] == liam and row["criterion_id"] in ben_w9:
            row["earned"] = ben_w9[row["criterion_id"]]

    return [Entry(**row) for row in rows]


def build_toy_database() -> MockDatabase:
    weeks = _weeks()
    students = _students()
    return MockDatabase(
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
        accounts=[
            MockAccount("a1", "teacher", None, "demo:teacher", "teacher@demo.test", "demo-teacher-1"),
            MockAccount("a2", "student", "s01", "demo:amara", "amara@demo.test", "demo-student-1"),
            MockAccount("a3", "student", "s18", "demo:rosa", "rosa@demo.test", "demo-student-2"),
        ],
    )
