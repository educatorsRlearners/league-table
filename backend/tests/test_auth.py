import pytest
from fastapi.testclient import TestClient

from app.identity import hash_code
from factories import ADA, INSTRUCTOR

ACCOUNT_FIELDS = {"id", "role", "student_id", "external_id"}


class TestLogin:
    def test_the_instructor_signs_in_with_the_passcode(self, anon):
        response = anon.post("/api/auth/login", json={"code": INSTRUCTOR})
        assert response.status_code == 200
        assert response.json() == {
            "id": "a1", "role": "instructor", "student_id": None, "external_id": "demo:instructor",
        }

    def test_a_student_signs_in_with_their_access_code(self, anon):
        body = anon.post("/api/auth/login", json={"code": ADA}).json()
        assert body["role"] == "student"
        assert body["student_id"] == "s01"

    def test_surrounding_spaces_are_ignored(self, anon):
        assert anon.post("/api/auth/login", json={"code": f"  {ADA}\n"}).status_code == 200

    def test_response_never_leaks_credentials(self, anon):
        body = anon.post("/api/auth/login", json={"code": ADA}).json()
        assert set(body) == ACCOUNT_FIELDS

    def test_sets_an_http_only_session_cookie(self, anon):
        cookie = anon.post("/api/auth/login", json={"code": ADA}).headers["set-cookie"]
        assert cookie.startswith("session=")
        assert "HttpOnly" in cookie

    @pytest.mark.parametrize("code", ["nope", "ADA-CODE", "", "demo:ada"])
    def test_a_wrong_code_is_401_and_sets_no_cookie(self, anon, code):
        response = anon.post("/api/auth/login", json={"code": code})
        assert response.status_code in (401, 422)
        assert "set-cookie" not in response.headers

    def test_a_wrong_code_says_so_in_words(self, anon):
        response = anon.post("/api/auth/login", json={"code": "nope"})
        assert response.status_code == 401
        assert isinstance(response.json()["detail"], str)

    def test_a_students_hash_is_not_a_code(self, anon):
        assert anon.post("/api/auth/login", json={"code": hash_code(ADA)}).status_code == 401

    def test_the_passcode_is_not_matched_by_a_prefix(self, anon):
        assert anon.post("/api/auth/login", json={"code": INSTRUCTOR[:-1]}).status_code == 401

    @pytest.mark.parametrize("body", [{}, {"email": "a@b.test", "password": "x"}])
    def test_missing_code_is_422(self, anon, body):
        response = anon.post("/api/auth/login", json=body)
        assert response.status_code == 422
        assert isinstance(response.json()["detail"], list)


class TestStoredCodes:
    def test_only_a_hash_of_each_code_is_stored(self, store):
        for account in store.list_accounts():
            assert account.access_code_hash is None or len(account.access_code_hash) == 64
            assert ADA not in repr(account)

    def test_the_instructor_has_no_stored_code(self, store):
        assert store.get_account("a1").access_code_hash is None


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

    def test_sessions_are_independent(self, instructor, ada):
        assert instructor.get("/api/auth/me").json()["role"] == "instructor"
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


class TestPasscodeConfiguration:
    def test_the_app_refuses_to_start_without_an_instructor_passcode(self, db, store, monkeypatch):
        from app.main import create_app

        monkeypatch.delenv("INSTRUCTOR_PASSCODE", raising=False)
        with pytest.raises(RuntimeError, match="INSTRUCTOR_PASSCODE"):
            create_app(db=db, store=store)

    def test_the_passcode_can_come_from_the_environment(self, db, store, monkeypatch):
        from app.main import create_app

        monkeypatch.setenv("INSTRUCTOR_PASSCODE", "from-the-environment")
        client = TestClient(create_app(db=db, store=store))
        assert client.post("/api/auth/login", json={"code": "from-the-environment"}).status_code == 200


class TestDemoAccounts:
    def test_lists_accounts_with_codes_and_needs_no_session(self, toy_app):
        response = TestClient(toy_app).get("/api/demo/accounts")
        assert response.status_code == 200
        accounts = response.json()
        assert [a["role"] for a in accounts] == ["instructor"] + ["student"] * 5
        for account in accounts:
            assert set(account) == ACCOUNT_FIELDS | {"name", "code"}
        assert accounts[0]["code"] == "demo-instructor"

    def test_listed_codes_work_for_login(self, toy_app):
        client = TestClient(toy_app)
        for account in client.get("/api/demo/accounts").json():
            response = client.post("/api/auth/login", json={"code": account["code"]})
            assert response.status_code == 200
            assert response.json()["id"] == account["id"]

    def test_404_when_the_source_is_not_demo_data(self, anon, db):
        db.kind = "sheets"
        response = anon.get("/api/demo/accounts")
        assert response.status_code == 404
        assert isinstance(response.json()["detail"], str)


PROTECTED = [
    ("GET", "/api/classes/c1"),
    ("GET", "/api/classes/c1/weeks"),
    ("GET", "/api/classes/c1/criteria"),
    ("GET", "/api/classes/c1/settings"),
    ("PUT", "/api/classes/c1/settings"),
    ("GET", "/api/classes/c1/explainer"),
    ("GET", "/api/classes/c1/ranking?week=w1"),
    ("GET", "/api/classes/c1/students/s01/explanation?week=w1"),
    ("GET", "/api/classes/c1/status"),
    ("POST", "/api/classes/c1/refresh"),
    ("GET", "/api/classes/c1/approvals"),
    ("POST", "/api/classes/c1/approvals/b1"),
    ("GET", "/api/classes/c1/change-log"),
    ("GET", "/api/classes/c1/commitments"),
    ("POST", "/api/classes/c1/students/s01/weeks/3/reverse"),
    ("GET", "/api/me/commitments"),
    ("PUT", "/api/me/commitments/baseline"),
    ("PUT", "/api/me/commitments/weeks/3"),
    ("DELETE", "/api/me/commitments/weeks/3"),
    ("POST", "/api/me/commitments/preview"),
]


@pytest.mark.parametrize("method,url", PROTECTED)
def test_every_endpoint_but_sign_in_needs_a_session(anon, method, url):
    response = anon.request(method, url, json={})
    assert response.status_code == 401
    assert isinstance(response.json()["detail"], str)
