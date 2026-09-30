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


# Where Linux distributions keep the system's trusted CAs -- what curl uses.
_SYSTEM_CA_FILES = (
    "/etc/ssl/certs/ca-certificates.crt",
    "/etc/pki/tls/certs/ca-bundle.crt",
    "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem",
    "/etc/ssl/ca-bundle.pem",
    "/etc/ssl/cert.pem",
)
_CA_FILE_VARS = ("API_PROXY_CA_BUNDLE", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE")

PROXY_CA_FILES = []


def _proxy_tls():
    """Trust what the machine trusts, like curl does.

    httpx on its own only trusts certifi's public CAs, and a venv's Python may
    look for the system store somewhere else, so an API behind a company or
    workspace CA fails with CERTIFICATE_VERIFY_FAILED even though curl
    reaches it. Every CA file that exists is loaded; API_PROXY_CA_BUNDLE adds
    a specific one.
    """
    context = ssl.create_default_context()
    candidates = [os.environ.get(v) for v in _CA_FILE_VARS] + list(_SYSTEM_CA_FILES)
    for path in dict.fromkeys(c for c in candidates if c):
        if not os.path.isfile(path):
            continue
        try:
            context.load_verify_locations(cafile=path)
            PROXY_CA_FILES.append(path)
        except (ssl.SSLError, OSError) as exc:
            print(f"could not load CA file {path}: {exc}", file=sys.stderr)
    if os.path.isdir("/etc/ssl/certs"):
        context.load_verify_locations(capath="/etc/ssl/certs")
    return context


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
        print(
            f"trusting CA files: {PROXY_CA_FILES or 'none found, system default only'}",
            file=sys.stderr,
        )
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
