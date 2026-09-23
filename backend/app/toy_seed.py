"""Seeded demo data ported from frontend/services/mockSource.js.

Two classes (c1, c2), 24 students each, 16 weeks, entries through week 12
(week 12 partial). Deterministic via mulberry32.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.datasource import Entry, Student
from app.mock_db import MockDatabase
from app.models import Class, Criterion, Week

CLASSES = [
    {"id": "c1", "instructor_id": "i1", "external_id": "univ:PHYS-204-A",
     "name": "PHYS 204 · Mechanics", "term_id": "t1", "sheet_id": "sheet-phys204"},
    {"id": "c2", "instructor_id": "i1", "external_id": "univ:DATA-118-B",
     "name": "DATA 118 · Intro to Data", "term_id": "t1", "sheet_id": "sheet-data118"},
]

NAMES = {
    "c1": [
        "Amara Okonkwo", "Ben Halvorsen", "Cleo Marchetti", "Dara Whitfield", "Elif Demir",
        "Farid Nasser", "Greta Lindqvist", "Hugo Ferreira", "Imani Blake", "Jonas Reuter",
        "Kiara Mensah", "Liam Donoghue", "Mira Chandra", "Nils Aaltonen", "Odette Laurent",
        "Pablo Guerrero", "Quinn Alderton", "Rosa Ibarra", "Samir Haddad", "Tessa Vermeulen",
        "Ugo Bianchi", "Vera Novak", "Wes Carmichael", "Isla Bennett",
    ],
    "c2": [
        "Adaeze Nwosu", "Bruno Kessler", "Camila Duarte", "Dmitri Volkov", "Esme Fairbairn",
        "Felix Adeyemi", "Gaia Russo", "Henrik Solberg", "Ines Cabrera", "Joon-ho Park",
        "Kavya Raman", "Lucien Berger", "Maeve Dolan", "Noor Rashid", "Otto Lindgren",
        "Priya Venkat", "Rafael Costa", "Saoirse Kelleher", "Tomas Oravec", "Ula Sienkiewicz",
        "Viktor Petrov", "Wren Abbott", "Yara El-Amin", "Zoltan Varga",
    ],
}

NICKNAMES = {
    "Amara Okonkwo": "Ammo", "Ben Halvorsen": "Benno", "Cleo Marchetti": "Clee",
    "Wes Carmichael": "Wez", "Isla Bennett": "Izzy", "Liam Donoghue": "Donny",
    "Adaeze Nwosu": "Ada", "Joon-ho Park": "JP", "Saoirse Kelleher": "Sersh",
    "Zoltan Varga": "Zolt", "Wren Abbott": "Wrennie",
}

CRITERIA: dict[str, list[dict[str, Any]]] = {
    "c1": [
        {"key": "homework", "label": "Homework", "unit": "tasks on time", "default_weight": 25, "possible": 5, "everyWeek": True},
        {"key": "attendance", "label": "Attendance", "unit": "sessions", "default_weight": 20, "possible": 3, "everyWeek": True},
        {"key": "participation", "label": "Participation", "unit": "points", "default_weight": 20, "possible": 15, "everyWeek": True},
        {"key": "project", "label": "Project scores", "unit": "marks", "default_weight": 25, "possible": 100, "weeks": [3, 7, 11, 15]},
        {"key": "quizzes", "label": "Quizzes", "unit": "marks", "default_weight": 10, "possible": 20, "everyWeek": True},
    ],
    "c2": [
        {"key": "homework", "label": "Problem sets", "unit": "sets on time", "default_weight": 30, "possible": 4, "everyWeek": True},
        {"key": "attendance", "label": "Attendance", "unit": "sessions", "default_weight": 15, "possible": 2, "everyWeek": True},
        {"key": "participation", "label": "Participation", "unit": "points", "default_weight": 15, "possible": 10, "everyWeek": True},
        {"key": "project", "label": "Project scores", "unit": "marks", "default_weight": 25, "possible": 100, "weeks": [5, 10, 15]},
        {"key": "reading", "label": "Reading log", "unit": "entries", "default_weight": 15, "possible": 3, "everyWeek": True},
    ],
}

WEEK_COUNT = 16
DATA_THROUGH = 12
PARTIAL_WEEK = 12
PARTIAL_KEYS = ["homework", "attendance"]

TERM_START_MS = 1756080000000  # Date.UTC(2025, 7, 25), Monday 25 Aug 2025 → week 12 is 10–14 Nov


def _mulberry32(seed: int):
    a = seed & 0xFFFFFFFF

    def rnd() -> float:
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = ((t ^ (t >> 15)) * (t | 1)) & 0xFFFFFFFF
        t ^= (t + (((t ^ (t >> 7)) * (t | 61)) & 0xFFFFFFFF)) & 0xFFFFFFFF
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296

    return rnd


def _js_round(v: float) -> int:
    return math.floor(v + 0.5)


def build_weeks() -> list[Week]:
    weeks = []
    for i in range(WEEK_COUNT):

        start_ms = TERM_START_MS + i * 7 * 86400000
        end_ms = TERM_START_MS + (i * 7 + 4) * 86400000
        start = datetime.fromtimestamp(start_ms / 1000, tz=UTC).date()
        end = datetime.fromtimestamp(end_ms / 1000, tz=UTC).date()
        weeks.append(Week(id=f"w{i + 1}", term_id="t1", week_number=i + 1,
                          start_date=start.isoformat(), end_date=end.isoformat()))
    return weeks


def build_students(class_id: str) -> list[Student]:
    prefix = "s" if class_id == "c1" else "t"
    base = 4000 if class_id == "c1" else 5000
    out = []
    for i, name in enumerate(NAMES[class_id]):
        out.append(Student(
            id=f"{prefix}{i + 1:02d}",
            external_id=f"univ:stu-{base + i}",
            class_id=class_id,
            display_name=name,
            nickname=NICKNAMES.get(name),
            avatar_url=None,
            active=True,
            joined_week=4 if i == 23 else 1,
        ))
    return out


def build_entries(class_id: str, students: list[Student], weeks) -> list[Entry]:
    criteria = CRITERIA[class_id]
    rng = _mulberry32(20260706 if class_id == "c1" else 20260707)
    ability: dict[str, dict[str, float]] = {}
    for i, s in enumerate(students):
        ability[s.id] = {}
        base = 0.9 if i <= 1 else 0.55 + rng() * 0.42
        for c in criteria:
            ability[s.id][c["key"]] = min(0.99, max(0.12, base + (rng() - 0.5) * 0.28))
    entries = []
    n = 0
    for w in weeks:
        if w.week_number > DATA_THROUGH:
            continue
        for c in criteria:
            if not c.get("everyWeek") and w.week_number not in c.get("weeks", []):
                continue
            if w.week_number == PARTIAL_WEEK and c["key"] not in PARTIAL_KEYS:
                continue
            for i, s in enumerate(students):
                if w.week_number < s.joined_week:
                    continue
                frac = min(1, max(0, ability[s.id][c["key"]] + (rng() - 0.5) * 0.26))
                if i == 0 and w.week_number == 5:
                    frac = 1
                if i == 1 and w.week_number == 5:
                    frac = 0.92
                if i == 12 and w.week_number == 6:
                    frac = 0
                if i == 17 and c["key"] == "participation" and w.week_number == 7:
                    continue
                n += 1
                entries.append(Entry(
                    id=f"{class_id}-e{n}",
                    student_id=s.id,
                    criterion_id=f"{class_id}-{c['key']}",
                    week_id=w.id,
                    earned=_js_round(frac * c["possible"]),
                    possible=c["possible"],
                    recorded_at=f"{w.end_date}T16:00:00Z",
                    criterion_key=c["key"],
                ))
    a = students[10]
    b = students[11]
    for e in entries:
        if e.week_id == "w9" and e.student_id == b.id:
            twin = next((x for x in entries if x.week_id == "w9" and x.student_id == a.id and x.criterion_key == e.criterion_key), None)
            if twin is not None:
                object.__setattr__(e, "earned", twin.earned)
    return entries


def seed_commitments(class_id: str) -> tuple[list[dict], list[dict]]:
    p = "s" if class_id == "c1" else "t"

    def sid(i: int) -> str:
        return f"{p}{i + 1:02d}"

    baselines = [
        {"id": f"{class_id}-b1", "student_id": sid(0), "work_hours": 12, "childcare_hours": 6, "eldercare_hours": 0, "status": "approved", "effective_from_week": 1, "submitted_at": "2025-08-26T09:12:00Z", "decided_by": "i1", "decided_at": "2025-08-26T17:40:00Z"},
        {"id": f"{class_id}-b2", "student_id": sid(1), "work_hours": 30, "childcare_hours": 10, "eldercare_hours": 5, "status": "approved", "effective_from_week": 1, "submitted_at": "2025-08-26T10:02:00Z", "decided_by": "i1", "decided_at": "2025-08-27T08:15:00Z"},
        {"id": f"{class_id}-b3", "student_id": sid(2), "work_hours": 10, "childcare_hours": 0, "eldercare_hours": 4, "status": "pending", "effective_from_week": None, "submitted_at": "2025-11-07T20:31:00Z", "decided_by": None, "decided_at": None},
        {"id": f"{class_id}-b4", "student_id": sid(3), "work_hours": 40, "childcare_hours": 20, "eldercare_hours": 10, "status": "rejected", "effective_from_week": None, "submitted_at": "2025-09-21T22:05:00Z", "decided_by": "i1", "decided_at": "2025-09-22T09:00:00Z"},
        {"id": f"{class_id}-b5", "student_id": sid(4), "work_hours": 8, "childcare_hours": 0, "eldercare_hours": 0, "status": "approved", "effective_from_week": 6, "submitted_at": "2025-09-27T11:20:00Z", "decided_by": "i1", "decided_at": "2025-09-28T10:00:00Z"},
        {"id": f"{class_id}-b6", "student_id": sid(5), "work_hours": 6, "childcare_hours": 4, "eldercare_hours": 0, "status": "approved", "effective_from_week": 1, "submitted_at": "2025-08-25T18:44:00Z", "decided_by": "i1", "decided_at": "2025-08-26T17:41:00Z"},
        {"id": f"{class_id}-b7", "student_id": sid(6), "work_hours": 10, "childcare_hours": 0, "eldercare_hours": 2, "status": "approved", "effective_from_week": 1, "submitted_at": "2025-08-25T19:10:00Z", "decided_by": "i1", "decided_at": "2025-08-26T17:42:00Z"},
    ]
    updates = [
        {"id": f"{class_id}-u1", "student_id": sid(5), "week_id": "w10", "week_number": 10, "work_hours": 20, "childcare_hours": 4, "eldercare_hours": 0, "entered_at": "2025-10-27T21:00:00Z", "reversed_by": None, "reversed_at": None},
        {"id": f"{class_id}-u2", "student_id": sid(6), "week_id": "w9", "week_number": 9, "work_hours": 46, "childcare_hours": 0, "eldercare_hours": 2, "entered_at": "2025-10-20T23:12:00Z", "reversed_by": "i1", "reversed_at": "2025-10-21T08:30:00Z"},
    ]
    return baselines, updates


def seed_notes() -> list[dict]:
    return [
        {"id": "n1", "instructor_id": "i1", "class_id": "c1", "student_id": "s13",
         "body": "Emailed 3 Nov about the two missed problem sets. No reply yet.", "created_at": "2025-11-03T11:20:00Z"},
        {"id": "n2", "instructor_id": "i1", "class_id": "c1", "student_id": "s13",
         "body": "Met in office hours 7 Nov. Shift pattern changed at work. Follow up in two weeks.", "created_at": "2025-11-07T15:05:00Z"},
    ]


@dataclass
class Toy:
    db: MockDatabase
    seed: dict


def build_toy() -> Toy:
    weeks = build_weeks()
    classes = [Class(**c) for c in CLASSES]
    students: list[Student] = []
    criteria = []
    entries: list[Entry] = []
    baselines: dict[str, list[dict]] = {}
    updates: dict[str, list[dict]] = {}
    for c in CLASSES:
        cid = c["id"]
        studs = build_students(cid)
        students.extend(studs)
        for i, crit in enumerate(CRITERIA[cid]):
            criteria.append(Criterion(id=f"{cid}-{crit['key']}", class_id=cid, key=crit["key"],
                                      label=crit["label"], unit=crit.get("unit"),
                                      default_weight=crit["default_weight"], sort_order=i))
        entries.extend(build_entries(cid, studs, weeks))
        b, u = seed_commitments(cid)
        baselines[cid] = b
        updates[cid] = u
    accounts: list[dict[str, Any]] = [
        {"id": "a1", "role": "instructor", "student_id": None, "class_ids": ["c1", "c2"], "external_id": "demo:instructor"},
        {"id": "a2", "role": "student", "student_id": "s01", "class_ids": ["c1"], "external_id": "demo:amara"},
        {"id": "a3", "role": "student", "student_id": "s18", "class_ids": ["c1"], "external_id": "demo:rosa"},
        {"id": "a4", "role": "student", "student_id": "t03", "class_ids": ["c2"], "external_id": "demo:camila"},
    ]
    db = MockDatabase(kind="toy", label="Demo data", classes=classes, students=students,
                      criteria=criteria, weeks=weeks, entries=entries, accounts=accounts)
    seed = {"baselines": baselines, "weekly_updates": updates, "notes": seed_notes()}
    return Toy(db=db, seed=seed)
