"""Read-write AppStore matching frontend createToyAppStore contract.

League settings: {weights|None, typeWeights, rate, cap, tieBreakers}
Baselines: {id, student_id, work_hours, childcare_hours, eldercare_hours,
  status, effective_from_week, submitted_at, decided_by, decided_at}
Weekly updates: {id, student_id, week_id, week_number, work_hours,
  childcare_hours, eldercare_hours, entered_at, reversed_by, reversed_at}
Risk settings: {thresholds, active}; risk snapshots: evaluation payloads.
Notes: {id, instructor_id, class_id, student_id, body, created_at}.
"""

from __future__ import annotations

import threading
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol

from app.risk import DEFAULT_ACTIVE, DEFAULT_THRESHOLDS


def default_league_settings() -> dict:
    return {
        "typeWeights": {"work": 1, "childcare": 1, "eldercare": 1},
        "rate": 0.01,
        "cap": 1.25,
        "tieBreakers": ["attendance", "homework"],
    }


def default_risk_settings() -> dict:
    return {"thresholds": dict(DEFAULT_THRESHOLDS), "active": dict(DEFAULT_ACTIVE)}


class AppStore(Protocol):
    kind: str
    label: str

    def get_league_settings(self, class_id: str) -> dict: ...
    def save_league_settings(self, class_id: str, patch: dict) -> dict: ...
    def list_baselines(self, class_id: str) -> list[dict]: ...
    def list_weekly_updates(self, class_id: str) -> list[dict]: ...
    def get_commitments(self, class_id: str, student_id: str) -> dict: ...
    def get_risk_settings(self, class_id: str) -> dict: ...
    def save_risk_settings(self, class_id: str, patch: dict) -> dict: ...
    def add_note(self, *, class_id: str, student_id: str, instructor_id: str, body: str, at: str | None = None) -> dict: ...
    def list_notes(self, class_id: str, student_id: str | None, instructor_id: str) -> list[dict]: ...


class MemoryStore:
    kind = "memory"
    label = "In memory"

    def __init__(self, class_ids: list[str] | None = None, seed: dict | None = None) -> None:
        self._lock = threading.RLock()
        seed = seed or {}
        self._settings: dict[str, dict] = {}
        self._weights: dict[str, dict | None] = {}
        self._baselines: dict[str, list[dict]] = {}
        self._updates: dict[str, list[dict]] = {}
        self._risk_settings: dict[str, dict] = {}
        self._notes: list[dict] = []
        self._note_seq = 0
        for cid in class_ids or []:
            self._settings[cid] = deepcopy(seed.get("settings", {}).get(cid, default_league_settings()))
            self._weights[cid] = deepcopy(seed.get("weights", {}).get(cid))
            self._baselines[cid] = deepcopy(seed.get("baselines", {}).get(cid, []))
            self._updates[cid] = deepcopy(seed.get("weekly_updates", {}).get(cid, []))
            self._risk_settings[cid] = deepcopy(seed.get("risk_settings", {}).get(cid, default_risk_settings()))
        for n in seed.get("notes", []):
            self._notes.append(deepcopy(n))
            try:
                num = int(str(n.get("id", "n0"))[1:])
                self._note_seq = max(self._note_seq, num)
            except ValueError:
                pass

    def _league(self, class_id: str) -> dict:
        if class_id not in self._settings:
            self._settings[class_id] = default_league_settings()
            self._weights[class_id] = None
            self._baselines.setdefault(class_id, [])
            self._updates.setdefault(class_id, [])
            self._risk_settings.setdefault(class_id, default_risk_settings())
        base = dict(self._settings[class_id])
        base["weights"] = deepcopy(self._weights.get(class_id))
        return base

    # league settings

    def get_league_settings(self, class_id: str) -> dict:
        with self._lock:
            return self._league(class_id)

    def save_league_settings(self, class_id: str, patch: dict) -> dict:
        with self._lock:
            self._league(class_id)
            if "weights" in patch and patch["weights"] is not None:
                self._weights[class_id] = dict(patch["weights"])
            rest = {k: v for k, v in patch.items() if k != "weights"}
            self._settings[class_id] = {**self._settings[class_id], **rest}
            return self._league(class_id)

    # commitments

    def list_baselines(self, class_id: str) -> list[dict]:
        with self._lock:
            return deepcopy(self._baselines.get(class_id, []))

    def list_weekly_updates(self, class_id: str) -> list[dict]:
        with self._lock:
            return deepcopy(self._updates.get(class_id, []))

    def get_commitments(self, class_id: str, student_id: str) -> dict:
        with self._lock:
            baselines = [b for b in self._baselines.get(class_id, []) if b["student_id"] == student_id and b["status"] != "superseded"]
            baseline = baselines[-1] if baselines else None
            updates = [u for u in self._updates.get(class_id, []) if u["student_id"] == student_id]
            return {"baseline": deepcopy(baseline), "weeklyUpdates": deepcopy(updates)}

    # risk

    def get_risk_settings(self, class_id: str) -> dict:
        with self._lock:
            if class_id not in self._risk_settings:
                self._risk_settings[class_id] = default_risk_settings()
            return deepcopy(self._risk_settings[class_id])

    def save_risk_settings(self, class_id: str, patch: dict) -> dict:
        with self._lock:
            current = self.get_risk_settings(class_id)
            merged = {
                "thresholds": {**current["thresholds"], **(patch.get("thresholds") or {})},
                "active": {**current["active"], **(patch.get("active") or {})},
            }
            self._risk_settings[class_id] = merged
            return deepcopy(merged)

    # notes

    def add_note(self, *, class_id: str, student_id: str, instructor_id: str, body: str, at: str | None = None) -> dict:
        with self._lock:
            self._note_seq += 1
            note = {
                "id": f"n{self._note_seq}",
                "instructor_id": instructor_id,
                "class_id": class_id,
                "student_id": student_id,
                "body": body,
                "created_at": at or datetime.now(UTC).isoformat(),
            }
            self._notes.append(note)
            return deepcopy(note)

    def list_notes(self, class_id: str, student_id: str | None, instructor_id: str) -> list[dict]:
        with self._lock:
            return deepcopy([
                n for n in self._notes
                if n["class_id"] == class_id and n["instructor_id"] == instructor_id
                and (not student_id or n["student_id"] == student_id)
            ])
