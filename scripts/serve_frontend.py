"""Serve the built dashboard as a Cloudera AI Application."""
import os
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
    """This server's own liveness."""
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
    """Serve a real file when one exists, index.html otherwise."""
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

    app.run(host=host, port=port, debug=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
