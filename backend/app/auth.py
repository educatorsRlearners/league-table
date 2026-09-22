"""Bearer auth with opaque demo tokens (per spec, Bearer JWT identity).

Token forms accepted (all map to a Caller):
  instructor: "i1", "instructor", "instructor-i1", "instructor:i1", "a1", "demo-instructor"
  student:    "s01", "student-s01", "s01:c1", "student-s01-c1", "student:s01:c1", "a2"...
Student class defaults: s* -> c1, t* -> c2. Tokens "a2"/"a3"/"a4" map via demo accounts.
Anything else -> 401.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

bearer = HTTPBearer(scheme_name="bearerAuth", auto_error=False,
                    description="JWT identifying the caller. Server derives role, studentId and class membership.")

DEMO_ACCOUNT_TOKENS = {
    "a1": ("instructor", None, None, "i1"),
    "a2": ("student", "s01", "c1", None),
    "a3": ("student", "s18", "c1", None),
    "a4": ("student", "t03", "c2", None),
    "demo-instructor": ("instructor", None, None, "i1"),
    "demo-amara": ("student", "s01", "c1", None),
    "demo-rosa": ("student", "s18", "c1", None),
    "demo-camila": ("student", "t03", "c2", None),
}


@dataclass(frozen=True, slots=True)
class Caller:
    role: str  # instructor | student
    studentId: str | None = None
    classId: str | None = None
    instructorId: str | None = None


def parse_token(token: str) -> Caller | None:
    t = (token or "").strip()
    if not t:
        return None
    if t in DEMO_ACCOUNT_TOKENS:
        role, sid, cid, iid = DEMO_ACCOUNT_TOKENS[t]
        return Caller(role=role, studentId=sid, classId=cid, instructorId=iid)
    low = t.lower()
    if low in ("i1", "instructor", "instructor-i1", "instructor:i1"):
        return Caller(role="instructor", instructorId="i1")
    if low.startswith("instructor-") or low.startswith("instructor:"):
        iid = t.split("-", 1)[-1].split(":", 1)[-1] or "i1"
        return Caller(role="instructor", instructorId=iid)
    # student forms
    body = t
    for prefix in ("student:", "student-", "student_"):
        if low.startswith(prefix):
            body = t[len(prefix):]
            break
    # body like s01:c1, s01-c1, s01@c1, or bare s01
    sid, cid = body, None
    for sep in (":", "-", "@", "/"):
        if sep in body:
            parts = body.replace("@", ":").replace("/", ":").replace("-", ":").split(":")
            parts = [p for p in parts if p]
            if len(parts) >= 2:
                sid, cid = parts[0], parts[1]
            else:
                sid = parts[0]
            break
    sid = sid.strip()
    if not sid:
        return None
    # must look like a student id (sNN / tNN) to accept
    if not (sid[0] in ("s", "t") and sid[1:].isdigit()):
        return None
    if cid is None:
        cid = "c1" if sid.startswith("s") else "c2"
    return Caller(role="student", studentId=sid, classId=cid)


def get_caller(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)) -> Caller:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing Bearer token.")
    caller = parse_token(credentials.credentials)
    if caller is None:
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token.")
    return caller


def require_instructor(caller: Caller = Depends(get_caller)) -> Caller:
    if caller.role != "instructor":
        raise HTTPException(status_code=403, detail="Instructor only.")
    return caller


def instructor_id_of(caller: Caller) -> str:
    return caller.instructorId or "i1"
