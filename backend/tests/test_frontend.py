"""The backend serves the frontend so the page and the API share an origin (and a session cookie)."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import FRONTEND_DIR, create_app


def test_the_default_frontend_dir_is_the_repos_frontend_folder():
    assert FRONTEND_DIR == Path(__file__).resolve().parents[2] / "frontend"
    assert (FRONTEND_DIR / "League Table.dc.html").is_file()


def test_serves_the_page(anon):
    response = anon.get("/League%20Table.dc.html")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]


def test_serves_the_services_as_javascript_modules(anon):
    response = anon.get("/services/api.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]


def test_the_root_redirects_to_the_page(anon):
    response = anon.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"] == "/League%20Table.dc.html"


def test_the_api_is_not_shadowed_by_the_static_files(anon):
    assert anon.get("/api/auth/me").status_code == 401
    assert anon.get("/api/demo/accounts").status_code == 200


def test_an_unknown_api_path_is_a_json_404(anon):
    response = anon.get("/api/nope")
    assert response.status_code == 404
    assert isinstance(response.json()["detail"], str)


def test_can_be_left_out(db, store, clock):
    client = TestClient(create_app(db=db, store=store, clock=clock, instructor_passcode="x", frontend_dir=None))
    assert client.get("/League%20Table.dc.html").status_code == 404
    assert client.get("/api/demo/accounts").status_code == 200
