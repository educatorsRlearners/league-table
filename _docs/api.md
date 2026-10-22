# API and auth

The endpoints and the demo authentication. [`openapi.yaml`](../openapi.yaml) is the contract.

## API

All endpoints take a Bearer token (see [Auth](#auth) below). The full contract is in [`openapi.yaml`](../openapi.yaml).

| Endpoint | Who | Purpose |
| --- | --- | --- |
| `GET /login/options` | public (no token) | Classes and student rosters (id + display name only) for the login picker |
| `GET /classes` | instructor | Classes the instructor teaches |
| `GET /classes/{id}/bootstrap` | signed in (students: own class) | Weeks, criteria, weights, settings, accounts, source and issues in one call |
| `GET /classes/{id}/ranking?week=&criteria=&window=` | signed in (students: own class; rows scoped) | Ranked adjusted scores for a week, cumulative or rolling window |
| `GET /classes/{id}/students/{sid}/explanation` | instructor, or the student themselves | The full breakdown, including hours, factor and cap |
| `GET /classes/{id}/explainer` | signed in | The formula and current parameters, with no personal data |
| `GET /me/commitments?classId=&studentId=` | instructor, or the student themselves | Active + pending baseline, weekly updates, hours/factor/source by week, and which weeks are editable |
| `PUT /me/commitments/baseline?classId=&studentId=` | the student themselves | Submit/change the semester baseline (0-80h per type, half-hour steps, ≤120 total); pending until an instructor decides |
| `PUT /me/commitments/weeks/{weekNumber}?classId=&studentId=` | the student themselves | Replace one week's hours; only the current or previous calendar week is editable |
| `GET /classes/{id}/commitments/pending` | instructor | Queue of pending baselines awaiting a decision |
| `POST /classes/{id}/commitments/baselines/{baselineId}/decide` | instructor | Approve (picking the effective week) or reject a pending baseline |
| `GET /classes/{id}/commitments/weekly-updates` | instructor | Every weekly update for the class, most recent first |
| `POST /classes/{id}/commitments/weekly-updates/{updateId}/reverse` | instructor | Reverse a weekly update |
| `GET /classes/{id}/commitments/change-log?studentId=` | instructor | Every commitment change (submit, approve, reject, weekly set, reversal) with actor, time and old/new hours (`work_hours`, `childcare_hours`, `eldercare_hours`), newest first; reversing a weekly update restores the value it replaced |
| `GET /instructor/digest?week=` | instructor | New/still/cleared flags across every class, for a chosen week (default: each class's latest complete week) compared against the week before it |
| `GET /classes/{id}/students/{sid}/risk` | instructor (with notes), or the student themselves (notes hidden) | Level, five signals with evidence, metrics, thresholds, history |
| `POST /classes/{id}/students/{sid}/notes` | instructor | Log private outreach (body trimmed, empty rejected) |
| `GET`/`PUT /classes/{id}/risk-settings` | instructor | Per-class risk thresholds and active signals |
| `GET /me/standing?classId=&studentId=` | the student themselves | Own level, active signals and help — nothing else |
| `PUT /classes/{id}/settings` | instructor | Criterion weights and adjustment parameters (weights normalised to 100) |
| `GET /classes/{id}/status`, `POST /classes/{id}/refresh` | signed in | Data freshness and cache refresh (rate-limited, stale fallback) |

## Auth

Every endpoint needs `Authorization: Bearer <token>`; the server derives the role (instructor/student), student ID and class membership from it and enforces ownership with 403s. The app has no real sign-in yet (university sign-in comes later). The frontend's login screen is a demo picker: choose Instructor, Student or Admin and, for Student, a class and a name from the roster. The choice sets the Bearer token client-side. Admin opens the same view as Instructor; it is a role stub, because the spec makes Admin a server-configuration role, not a browser screen. The roster comes from `GET /login/options`, the one endpoint that doesn't require a token. The nav is scoped to the signed-in role, and the choice lasts for the session only; a reload clears it.

The demo accepts opaque tokens:

- `i1` — the instructor
- `s01` — a student in `c1` (likewise any `sNN` → `c1`, `tNN` → `c2`)
- `student:<sid>:<cid>` / `instructor:<iid>` forms (e.g. `student:s01:c1`)

For example:

```sh
curl -H "Authorization: Bearer i1" "http://localhost:8000/classes/c1/ranking?week=w5"
```
