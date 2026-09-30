import os
import ssl
import sys
from pathlib import Path

import httpx
from flask import Flask, Response, request, send_from_directory

REPO_ROOT = Path(__file__).resolve().parent.parent

DIST = Path(
    os.environ.get("FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist"))
).resolve()

API_PROXY_TARGET = os.environ.get("API_PROXY_TARGET", "").rstrip("/")

PROXY_TIMEOUT_SECONDS = float(os.environ.get("API_PROXY_TIMEOUT_SECONDS", "120"))


def _proxy_tls():
    """Trust what the machine trusts, like curl does.

    httpx on its own only trusts certifi's public CAs, so an API behind a
    company or workspace CA fails with CERTIFICATE_VERIFY_FAILED even though
    curl reaches it fine. API_PROXY_CA_BUNDLE points at a specific CA file
    when the system store does not have it either.
    """
    bundle = os.environ.get("API_PROXY_CA_BUNDLE") or os.environ.get("SSL_CERT_FILE")
    if bundle:
        return ssl.create_default_context(cafile=bundle)
    return ssl.create_default_context()


PROXY_TLS = _proxy_tls()

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}

app = Flask(__name__, static_folder=None)


@app.get("/healthz")
def healthz():
    return {"status": "ok", "dist": str(DIST)}


if API_PROXY_TARGET:

    @app.route(
        "/api/<path:subpath>",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    def proxy(subpath: str):
        url = f"{API_PROXY_TARGET}/{subpath}"

        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_BY_HOP and key.lower() != "host"
        }

        forwarded = request.headers.get("X-Forwarded-For")
        client = request.remote_addr or ""
        if client:
            headers["X-Forwarded-For"] = (
                f"{forwarded}, {client}" if forwarded else client
            )
        headers.setdefault(
            "X-Forwarded-Proto", request.headers.get("X-Forwarded-Proto", request.scheme)
        )

        try:
            upstream = httpx.request(
                request.method,
                url,
                params=request.args,
                content=request.get_data(),
                headers=headers,
                timeout=PROXY_TIMEOUT_SECONDS,
                follow_redirects=False,
                verify=PROXY_TLS,
            )
        except httpx.HTTPError as exc:
            print(f"proxy to {url} failed: {exc!r}", file=sys.stderr)
            return {"error": {"code": "bad_gateway", "detail": str(exc)}}, 502

        passthrough = [
            (key, value)
            for key, value in upstream.headers.items()
            if key.lower() not in _HOP_BY_HOP
        ]
        return Response(upstream.content, upstream.status_code, passthrough)


if not API_PROXY_TARGET:

    @app.route(
        "/api/<path:subpath>",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    def no_proxy(subpath: str):
        # Without this, /api/... falls through to index.html and the app gets
        # a page of HTML where it expected JSON.
        return {
            "error": {
                "code": "api_proxy_not_configured",
                "detail": "API_PROXY_TARGET is not set on the dashboard, so "
                "/api is not forwarded to the API. Set it to the API URL "
                "and restart the dashboard.",
            }
        }, 503


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path: str):
    candidate = DIST / path
    if path and candidate.is_file():
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")


def main() -> int:
    if not (DIST / "index.html").is_file():
        print(
            f"No index.html under {DIST}. Run `npm run build` in frontend/ "
            f"first, or set FRONTEND_DIST to the build output.",
            file=sys.stderr,
        )
        return 1

    port = int(os.environ.get("CDSW_APP_PORT", "8090"))
    host = os.environ.get("CDSW_APP_HOST", "127.0.0.1")

    print(f"serving {DIST} on {host}:{port}", file=sys.stderr)
    if API_PROXY_TARGET:
        print(f"proxying /api -> {API_PROXY_TARGET}", file=sys.stderr)
    else:
        print(
            "API_PROXY_TARGET is not set: /api is NOT forwarded to the API. "
            "Set it on this Application if the frontend was built with "
            "VITE_API_BASE_URL=/api.",
            file=sys.stderr,
        )

    app.run(host=host, port=port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
