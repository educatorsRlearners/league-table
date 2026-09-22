"""The running app must match openapi.yaml paths, query params and status codes."""

import copy
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

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


# --- Response body schemas, not just routes --------------------------------

SPEC_URI = "urn:league-table-openapi"


def _nullable_to_jsonschema(node):
    """Rewrite OpenAPI 3.0 ``nullable: true`` into JSON-Schema type unions."""
    if isinstance(node, dict):
        node = dict(node)
        if node.pop("nullable", False) and "type" in node and node["type"] != "null":
            node["type"] = [node["type"], "null"]
        return {k: _nullable_to_jsonschema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_nullable_to_jsonschema(v) for v in node]
    return node


@pytest.fixture(scope="module")
def registry(spec):
    normalised = _nullable_to_jsonschema(spec)
    resource = Resource.from_contents(normalised, default_specification=DRAFT202012)
    return Registry().with_resource(SPEC_URI, resource)


@pytest.fixture(scope="module")
def authed():
    client = TestClient(create_app(frontend_dir=None))
    client.headers.update({"Authorization": "Bearer i1"})
    return client


def validate_body(registry, schema_name, payload):
    validator = Draft202012Validator(
        {"$ref": f"{SPEC_URI}#/components/schemas/{schema_name}"}, registry=registry
    )
    validator.validate(payload)


def test_response_bodies_match_declared_schemas(registry, authed):
    checks = [
        ("Bootstrap", authed.get("/classes/c1/bootstrap")),
        ("RankingResponse", authed.get("/classes/c1/ranking", params={"week": "w5"})),
        ("Explainer", authed.get("/classes/c1/explainer")),
    ]
    for schema_name, res in checks:
        assert res.status_code == 200, schema_name
        validate_body(registry, schema_name, res.json())

    not_found = authed.get("/classes/no-such-class/bootstrap")
    assert not_found.status_code == 404
    validate_body(registry, "Error", not_found.json())


def test_schema_check_catches_drift(registry, authed):
    """The check above is only useful if it fails on a mismatched field."""
    good = authed.get("/classes/c1/ranking", params={"week": "w5"}).json()
    validate_body(registry, "RankingResponse", good)

    renamed = copy.deepcopy(good)
    renamed["rows"][0]["socre"] = renamed["rows"][0].pop("score")
    with pytest.raises(ValidationError):
        validate_body(registry, "RankingResponse", renamed)

    retyped = copy.deepcopy(good)
    retyped["weekCount"] = "one"
    with pytest.raises(ValidationError):
        validate_body(registry, "RankingResponse", retyped)
