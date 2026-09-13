import pytest
from fastapi import APIRouter

from app import main
from app.errors import NotFoundError

ORIGIN = "http://localhost:5173"


def test_an_allowed_origin_gets_the_header(client):
    response = client.get("/health", headers={"Origin": ORIGIN})

    assert response.headers["access-control-allow-origin"] == ORIGIN


def _preflight(client, origin=ORIGIN, headers="remote-user", method="GET"):
    return client.options(
        "/patients",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_a_preflight_is_answered_for_the_identity_header(client):
    response = _preflight(client)

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "remote-user" in response.headers["access-control-allow-headers"].lower()


def test_any_requested_header_is_mirrored_back(client):
    response = _preflight(client, headers="remote-user, x-made-up, content-type")

    allowed = response.headers["access-control-allow-headers"].lower()
    assert "remote-user" in allowed
    assert "x-made-up" in allowed


def test_a_refused_origin_still_names_the_headers_it_would_allow(client):
    response = _preflight(client, origin="http://evil.example")

    assert response.status_code == 400
    assert "origin" in response.text.lower()
    assert "access-control-allow-origin" not in response.headers
    assert "remote-user" in response.headers["access-control-allow-headers"].lower()


def test_an_unlisted_origin_is_not_allowed(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("https://dash.example.org/", ["https://dash.example.org"]),
        ("http://a.org , http://b.org", ["http://a.org", "http://b.org"]),
        ("https://dash.example.org/app/patients", ["https://dash.example.org"]),
    ],
)
def test_an_origin_is_trimmed_to_scheme_host_port(configured, expected, monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", configured)

    assert main._cors_origins() == expected




def test_a_crash_still_carries_the_cors_header(client):
    router = APIRouter()

    @router.get("/boom")
    def boom():
        raise RuntimeError("something nobody caught")

    main.app.include_router(router)
    try:
        response = client.get("/boom", headers={"Origin": ORIGIN})
    finally:
        main.app.router.routes = [
            route
            for route in main.app.router.routes
            if getattr(route, "path", None) != "/boom"
        ]

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["x-request-id"]


def test_a_handled_error_carries_it_too(client):
    router = APIRouter()

    @router.get("/missing-thing")
    def missing():
        raise NotFoundError("no such thing")

    main.app.include_router(router)
    try:
        response = client.get("/missing-thing", headers={"Origin": ORIGIN})
    finally:
        main.app.router.routes = [
            route
            for route in main.app.router.routes
            if getattr(route, "path", None) != "/missing-thing"
        ]

    assert response.status_code == 404
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_the_default_covers_the_ports_vite_falls_back_to(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    origins = main._cors_origins()

    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5180" in origins
