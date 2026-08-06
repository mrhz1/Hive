"""Serve the built dashboard as a Cloudera AI Application.

Cloudera AI Applications run a command, not a static site, so the React
build cannot be deployed directly -- something has to serve
`frontend/dist`. This is that something, kept deliberately small: no
templating, no session, no state.

    FRONTEND_DIST=frontend/dist python scripts/serve_frontend.py

## Two things it has to get right

**SPA fallback.** TanStack Router uses the history API, so a deep link
like `/patients/abc/files` is a real URL the browser requests from this
server. There is no such file on disk. Every unmatched path therefore
returns index.html and lets the router resolve it -- without this,
reloading any page but `/` is a 404.

**Optional API proxy.** Set `API_PROXY_TARGET` to the FastAPI
Application's URL and `/api/*` is forwarded to it, which makes the
dashboard and the API a single origin. That is worth doing on Cloudera:
the two Applications otherwise sit on different subdomains, so every
request is cross-origin and needs CORS_ORIGINS kept in sync with a
generated hostname. Leave it unset to have the browser call the API
directly (set VITE_API_BASE_URL at build time instead).

## Ports

Cloudera AI injects CDSW_APP_PORT and expects the process to listen on
it. Binding is 127.0.0.1 by default, which is what the platform's proxy
connects to; set CDSW_APP_HOST=0.0.0.0 if your workspace needs it.
"""
import os
import sys
from pathlib import Path

import httpx
from flask import Flask, Response, request, send_from_directory

REPO_ROOT = Path(__file__).resolve().parent.parent

DIST = Path(
    os.environ.get("FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist"))
).resolve()

# Where /api/* is forwarded. Unset = no proxy, browser talks to the API
# directly using the base URL baked in at build time.
API_PROXY_TARGET = os.environ.get("API_PROXY_TARGET", "").rstrip("/")

# Generous: a de-identify trigger is quick, but a PDF download of a
# scanned document is not.
PROXY_TIMEOUT_SECONDS = float(os.environ.get("API_PROXY_TIMEOUT_SECONDS", "120"))

# Hop-by-hop headers are meaningless to forward and actively break the
# response when copied (a Content-Length that no longer matches, a
# Transfer-Encoding this server is not using).
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
    """This server's own liveness. Deliberately does not check the API:
    the dashboard is still correctly served when the API is down, and
    conflating the two makes a backend blip look like a frontend
    outage."""
    return {"status": "ok", "dist": str(DIST)}


if API_PROXY_TARGET:

    @app.route(
        "/api/<path:subpath>",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    def proxy(subpath: str):
        url = f"{API_PROXY_TARGET}/{subpath}"

        # Host must not be forwarded -- it still names this server, and
        # the upstream may route on it.
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_BY_HOP and key.lower() != "host"
        }

        try:
            upstream = httpx.request(
                request.method,
                url,
                params=request.args,
                content=request.get_data(),
                headers=headers,
                timeout=PROXY_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError as exc:
            # 502, not 500: this server is fine, the upstream is not, and
            # the distinction matters when debugging a deployment.
            return {"error": {"code": "bad_gateway", "detail": str(exc)}}, 502

        passthrough = [
            (key, value)
            for key, value in upstream.headers.items()
            if key.lower() not in _HOP_BY_HOP
        ]
        return Response(upstream.content, upstream.status_code, passthrough)


@app.get("/", defaults={"path": ""})
@app.get("/<path:path>")
def spa(path: str):
    """Serve a real file when one exists, index.html otherwise.

    send_from_directory resolves against DIST and refuses to escape it,
    so a crafted path cannot read outside the build output.
    """
    candidate = DIST / path
    if path and candidate.is_file():
        return send_from_directory(DIST, path)
    return send_from_directory(DIST, "index.html")


def main() -> int:
    if not (DIST / "index.html").is_file():
        # The most common deployment mistake by a wide margin: the
        # Application was started without `npm run build` having run, or
        # against the wrong directory. Say so instead of serving 404s.
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

    app.run(host=host, port=port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
