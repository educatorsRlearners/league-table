"""The running app must match openapi.yaml, the contract the frontend is built against."""

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
    return create_app().openapi()


def operations(document, prefix=""):
    return {
        (method, prefix + path): operation
        for path, item in document["paths"].items()
        for method, operation in item.items()
        if method in METHODS
    }


def test_the_spec_is_served_from_the_api_prefix(spec):
    assert spec["servers"][0]["url"] == "/api"


def test_every_documented_operation_exists_and_nothing_extra_does(spec, generated):
    documented = set(operations(spec, "/api"))
    implemented = set(operations(generated))
    assert documented - implemented == set()
    assert implemented - documented == set()


def test_operation_ids_match_so_generated_clients_line_up(spec, generated):
    documented = {key: op["operationId"] for key, op in operations(spec, "/api").items()}
    implemented = {key: op["operationId"] for key, op in operations(generated).items()}
    assert implemented == documented


def test_documented_query_parameters_are_accepted(spec, generated):
    documented = operations(spec, "/api")
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
    documented = operations(spec, "/api")
    implemented = operations(generated)
    for key, operation in documented.items():
        missing = set(operation["responses"]) - set(implemented[key]["responses"])
        assert missing == set(), (key, missing)
