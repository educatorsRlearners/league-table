"""The running app must match openapi.yaml paths, query params and status codes."""

from pathlib import Path

import pytest
import yaml

from app.main import create_app

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"
METHODS = {"get", "put", "post", "delete", "patch"}


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(SPEC_PATH.read_text())


@pytest.fixture(scope="module")
def generated():
    return create_app(frontend_dir=None).openapi()


def operations(document):
    return {
        (method, path): operation
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in METHODS
    }


def test_servers_url_matches_spec(spec, generated):
    assert generated["servers"] == spec["servers"]


def test_global_bearer_auth(spec, generated):
    assert generated["security"] == spec["security"]
    assert "bearerAuth" in generated["components"]["securitySchemes"]


def test_every_documented_operation_exists_and_nothing_extra_does(spec, generated):
    documented = set(operations(spec))
    implemented = set(operations(generated))
    assert documented - implemented == set()
    assert implemented - documented == set()


def test_documented_query_parameters_are_accepted(spec, generated):
    documented = operations(spec)
    implemented = operations(generated)

    def query_names(document, operation):
        names = set()
        for parameter in operation.get("parameters", []):
            if "$ref" in parameter:
                parameter = document["components"]["parameters"][parameter["$ref"].rsplit("/", 1)[-1]]
            if parameter["in"] == "query":
                names.add(parameter["name"])
        return names

    for key, operation in documented.items():
        assert query_names(spec, operation) == query_names(generated, implemented[key]), key


def test_every_documented_status_code_is_declared_by_the_route(spec, generated):
    documented = operations(spec)
    implemented = operations(generated)
    for key, operation in documented.items():
        missing = set(operation["responses"]) - set(implemented[key]["responses"])
        assert missing == set(), (key, missing)
