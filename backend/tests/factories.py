"""A tiny hand-built dataset whose scores are easy to calculate by hand.

Criteria (default weights 50 / 30 / 20): homework, attendance, participation.
Students: s01 Ada Lovelace ("Ace"), s02 Ben Carter, s03 Cy Dunn, s04 Di Evans,
s05 Ed Frost (joins in week 2).

Week 1 (percent scores)      hw   att  part   score
    s01 Ada                  100   80   100    94
    s02 Ben                   80  100    60    82   (ties with s04)
    s03 Cy                    60  100   none   75   (participation missing, weights rescaled to 62.5/37.5)
    s04 Di                    80  100    60    82
    s05 Ed                   no entries

Week 2                       hw   att  part   score
    s01 Ada                   80  100    80    86   (ties with s03)
    s02 Ben                  100  100   100   100   (participation is 10 of 10, not 25)
    s03 Cy                   100   80    60    86
    s04 Di                    40  100    60    62
    s05 Ed                    60  100    80    76

Cumulative through week 2 (earned and possible are summed, not percentages averaged):
    s01 90, s02 89.2857 (part = 25/35), s03 79, s04 72, s05 76.
"""

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.datasource import Entry, Student
from app.identity import hash_code
from app.mock_db import MockDatabase
from app.models import Class, Criterion, Week
from app.store import MemoryStore, StoredAccount

INSTRUCTOR = "instructor-passcode"
ADA = "ada-code"
BEN = "ben-code"
CY = "cy-code"

# The tests' FakeClock starts on Friday 15 Jan 2027, which is in week 3 of this term (weeks
# start on Mondays), so weeks 2 and 3 are the ones a student can edit.
WEEK_STARTS = {1: date(2026, 12, 28), 2: date(2027, 1, 4), 3: date(2027, 1, 11)}

_CRITERIA = [
    ("k1", "homework", "Homework", "tasks on time", 50, 0),
    ("k2", "attendance", "Attendance", "sessions", 30, 1),
    ("k3", "participation", "Participation", "points", 20, 2),
]
_KEY_TO_ID = {key: cid for cid, key, *_ in _CRITERIA}

# (student, week, {criterion key: (earned, possible)})
_ENTRIES = [
    ("s01", "w1", {"homework": (5, 5), "attendance": (4, 5), "participation": (25, 25)}),
    ("s02", "w1", {"homework": (4, 5), "attendance": (5, 5), "participation": (15, 25)}),
    ("s03", "w1", {"homework": (3, 5), "attendance": (5, 5)}),
    ("s04", "w1", {"homework": (4, 5), "attendance": (5, 5), "participation": (15, 25)}),
    ("s01", "w2", {"homework": (4, 5), "attendance": (5, 5), "participation": (20, 25)}),
    ("s02", "w2", {"homework": (5, 5), "attendance": (5, 5), "participation": (10, 10)}),
    ("s03", "w2", {"homework": (5, 5), "attendance": (4, 5), "participation": (15, 25)}),
    ("s04", "w2", {"homework": (2, 5), "attendance": (5, 5), "participation": (15, 25)}),
    ("s05", "w2", {"homework": (3, 5), "attendance": (5, 5), "participation": (20, 25)}),
]


def signed_in(app, code) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"code": code})
    assert response.status_code == 200, response.text
    return client


def make_entry(entry_id, student_id, week_id, key, earned, possible):
    return Entry(
        id=entry_id,
        student_id=student_id,
        criterion_id=_KEY_TO_ID[key],
        week_id=week_id,
        earned=earned,
        possible=possible,
        recorded_at="2026-01-09T16:00:00Z",
    )


def build_test_db() -> MockDatabase:
    names = [
        ("s01", "Ada Lovelace", "Ace"),
        ("s02", "Ben Carter", None),
        ("s03", "Cy Dunn", None),
        ("s04", "Di Evans", None),
        ("s05", "Ed Frost", None),
    ]
    entries = []
    for student_id, week_id, scores in _ENTRIES:
        for key, (earned, possible) in scores.items():
            entries.append(
                make_entry(f"e{len(entries) + 1}", student_id, week_id, key, earned, possible)
            )
    return MockDatabase(
        kind="toy",
        label="Demo data",
        classes=[Class(id="c1", external_id="test:c1", name="Test class", term_id="t1")],
        students=[
            Student(
                id=sid,
                external_id=f"test:{sid}",
                class_id="c1",
                display_name=name,
                nickname=nick,
                avatar_url=None,
                active=True,
            )
            for sid, name, nick in names
        ],
        criteria=[
            Criterion(
                id=cid, class_id="c1", key=key, label=label, unit=unit,
                default_weight=weight, sort_order=order,
            )
            for cid, key, label, unit, weight, order in _CRITERIA
        ],
        weeks=[
            Week(id=f"w{n}", term_id="t1", week_number=n, start_date=start, end_date=start + timedelta(days=4))
            for n, start in WEEK_STARTS.items()
        ],
        entries=entries,
    )


def build_test_store() -> MemoryStore:
    return MemoryStore(
        [
            StoredAccount("a1", "instructor", None, "demo:instructor", None),
            StoredAccount("a2", "student", "s01", "demo:ada", hash_code(ADA)),
            StoredAccount("a3", "student", "s02", "demo:ben", hash_code(BEN)),
            StoredAccount("a4", "student", "s03", "demo:cy", hash_code(CY)),
        ]
    )
