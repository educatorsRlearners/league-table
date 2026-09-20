import pytest
from fastapi.testclient import TestClient

from factories import ADA, TEACHER

ACCOUNT_FIELDS = {"id", "role", "student_id", "external_id"}


def google_token(email: str) -> str:
    """The mock identity verifier accepts `demo-google:<email>` tokens."""
    return f"demo-google:{email}"


class TestLogin:
    def test_teacher_signs_in(self, anon):
        response = anon.post("/api/auth/login", json=TEACHER)
        assert response.status_code == 200
        assert response.json() == {
            "id": "a1", "role": "teacher", "student_id": None, "external_id": "demo:teacher",
        }

    def test_student_signs_in_with_their_student_id(self, anon):
        body = anon.post("/api/auth/login", json=ADA).json()
        assert body["role"] == "student"
        assert body["student_id"] == "s01"

    def test_response_never_leaks_credentials(self, anon):
        body = anon.post("/api/auth/login", json=TEACHER).json()
        assert set(body) == ACCOUNT_FIELDS

    def test_sets_an_http_only_session_cookie(self, anon):
        response = anon.post("/api/auth/login", json=TEACHER)
        cookie = response.headers["set-cookie"]
        assert cookie.startswith("session=")
        assert "HttpOnly" in cookie

    def test_wrong_password_is_401(self, anon):
        response = anon.post("/api/auth/login", json={**TEACHER, "password": "nope"})
        assert response.status_code == 401
        assert isinstance(response.json()["detail"], str)
        assert "set-cookie" not in response.headers

    def test_unknown_email_is_401(self, anon):
        response = anon.post("/api/auth/login", json={"email": "who@demo.test", "password": "x"})
        assert response.status_code == 401

    @pytest.mark.parametrize("body", [{}, {"email": "teacher@demo.test"}, {"password": "x"}])
    def test_missing_fields_are_422(self, anon, body):
        response = anon.post("/api/auth/login", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)

    def test_malformed_email_is_422(self, anon):
        response = anon.post("/api/auth/login", json={"email": "not-an-email", "password": "x"})
        assert response.status_code == 422


class TestGoogleLogin:
    def test_email_on_the_roster_signs_in(self, anon):
        response = anon.post("/api/auth/google", json={"id_token": google_token(ADA["email"])})
        assert response.status_code == 200
        assert response.json()["student_id"] == "s01"
        assert "session=" in response.headers["set-cookie"]

    def test_email_match_ignores_case(self, anon):
        response = anon.post("/api/auth/google", json={"id_token": google_token("ADA@Demo.test")})
        assert response.status_code == 200

    def test_email_not_on_the_roster_is_403(self, anon):
        response = anon.post("/api/auth/google", json={"id_token": google_token("stranger@school.test")})
        assert response.status_code == 403

    def test_invalid_token_is_401(self, anon):
        response = anon.post("/api/auth/google", json={"id_token": "garbage"})
        assert response.status_code == 401

    def test_missing_token_is_422(self, anon):
        assert anon.post("/api/auth/google", json={}).status_code == 422


class TestSession:
    def test_me_without_a_session_is_401(self, anon):
        response = anon.get("/api/auth/me")
        assert response.status_code == 401
        assert isinstance(response.json()["detail"], str)

    def test_me_returns_the_signed_in_account(self, ada):
        response = ada.get("/api/auth/me")
        assert response.status_code == 200
        assert response.json() == {
            "id": "a2", "role": "student", "student_id": "s01", "external_id": "demo:ada",
        }

    def test_a_forged_cookie_is_401(self, app):
        client = TestClient(app, cookies={"session": "forged"})
        assert client.get("/api/auth/me").status_code == 401

    def test_sessions_are_independent(self, teacher, ada):
        assert teacher.get("/api/auth/me").json()["role"] == "teacher"
        assert ada.get("/api/auth/me").json()["role"] == "student"

    def test_logout_ends_the_session(self, ada):
        response = ada.post("/api/auth/logout")
        assert response.status_code == 204
        assert response.content == b""
        assert ada.get("/api/auth/me").status_code == 401

    def test_logout_invalidates_the_token_on_the_server(self, app, ada):
        token = ada.cookies["session"]
        ada.post("/api/auth/logout")
        replay = TestClient(app, cookies={"session": token})
        assert replay.get("/api/auth/me").status_code == 401

    def test_logout_without_a_session_is_401(self, anon):
        assert anon.post("/api/auth/logout").status_code == 401


class TestDemoAccounts:
    def test_lists_accounts_with_credentials_and_needs_no_session(self, anon):
        response = anon.get("/api/demo/accounts")
        assert response.status_code == 200
        accounts = response.json()
        assert [a["role"] for a in accounts] == ["teacher", "student", "student"]
        for account in accounts:
            assert set(account) == ACCOUNT_FIELDS | {"email", "password"}
        assert {"email": TEACHER["email"], "password": TEACHER["password"]}.items() <= accounts[0].items()

    def test_listed_credentials_work_for_login(self, anon):
        for account in anon.get("/api/demo/accounts").json():
            response = anon.post(
                "/api/auth/login", json={"email": account["email"], "password": account["password"]}
            )
            assert response.status_code == 200

    def test_404_when_the_source_is_not_demo_data(self, anon, db):
        db.kind = "sheets"
        response = anon.get("/api/demo/accounts")
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)


PROTECTED = [
    ("GET", "/api/classes/c1"),
    ("GET", "/api/classes/c1/weeks"),
    ("GET", "/api/classes/c1/criteria"),
    ("GET", "/api/classes/c1/weights"),
    ("PUT", "/api/classes/c1/weights"),
    ("GET", "/api/classes/c1/ranking?week=w1"),
    ("GET", "/api/classes/c1/students/s01/explanation?week=w1"),
    ("GET", "/api/classes/c1/status"),
    ("POST", "/api/classes/c1/refresh"),
]


@pytest.mark.parametrize("method,url", PROTECTED)
def test_every_class_endpoint_needs_a_session(anon, method, url):
    response = anon.request(method, url, json={"weights": {"homework": 1}} if method == "PUT" else None)
    assert response.status_code == 401
    assert isinstance(response.json()["detail"], str)
