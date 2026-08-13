"""Cross-origin requests, and the failures that masquerade as them.

A browser will not tell you why it refused a response, so every CORS
question here is really 'is the header on it' -- including on the
responses nobody thinks about, which is where the confusing ones come
from.
"""
import pytest
from fastapi import APIRouter

from app import main
from app.errors import NotFoundError

ORIGIN = "http://localhost:5173"


def test_an_allowed_origin_gets_the_header(client):
    response = client.get("/health", headers={"Origin": ORIGIN})

    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_a_preflight_is_answered_for_the_identity_header(client):
    """Sending REMOTE-USER is what makes every request preflighted."""
    response = client.options(
        "/patients",
        headers={
            "Origin": ORIGIN,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "remote-user",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN


def test_an_unlisted_origin_is_not_allowed(client):
    response = client.get("/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers


@pytest.mark.parametrize(
    "configured,expected",
    [
        ("https://dash.example.org/", ["https://dash.example.org"]),
        ("http://a.org , http://b.org", ["http://a.org", "http://b.org"]),
        # A whole URL pasted in, which is the natural thing to do.
        ("https://dash.example.org/app/patients", ["https://dash.example.org"]),
    ],
)
def test_an_origin_is_trimmed_to_scheme_host_port(configured, expected, monkeypatch):
    """A trailing slash makes the browser refuse a response the server
    believes it allowed -- and says nothing about why."""
    monkeypatch.setenv("CORS_ORIGINS", configured)

    assert main._cors_origins() == expected


# ------------------------------------------- the failure that looks like CORS


def test_a_crash_still_carries_the_cors_header(client):
    """Starlette handles a re-raised exception outside the CORS
    middleware, so a 500 used to come back bare and the browser blamed
    CORS -- sending everyone off to check an origin list that was right
    all along."""
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
    # The correlation id is how the response is tied to the traceback.
    assert response.headers["x-request-id"]


def test_a_handled_error_carries_it_too(client):
    """These go through a different path (Starlette's inner exception
    middleware), so they are worth pinning separately."""
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
    """5173 taken by another project is normal; vite silently moves up."""
    monkeypatch.delenv("CORS_ORIGINS", raising=False)

    origins = main._cors_origins()

    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5180" in origins
