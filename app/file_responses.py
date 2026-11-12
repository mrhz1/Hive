"""Send a file to the browser from local disk or from storage (Ozone)."""

from typing import Mapping, Optional
from urllib.parse import quote

from fastapi.responses import FileResponse, StreamingResponse

from app.blobstore import READ_BUFFER, StoragePath
from app.storage import guess_mime_type


def _disposition(kind: str, filename: str) -> str:
    # Same header Starlette's FileResponse writes, including non-ASCII names.
    quoted = quote(filename)
    if quoted != filename:
        return f"{kind}; filename*=utf-8''{quoted}"
    return f'{kind}; filename="{filename}"'


def file_response(
    path,
    media_type: Optional[str] = None,
    filename: Optional[str] = None,
    content_disposition_type: str = "attachment",
    headers: Optional[Mapping[str, str]] = None,
):
    """FileResponse for a local Path; for a StoragePath the file is streamed
    from the store in 1 MB pieces, never copied to disk first."""
    if not isinstance(path, StoragePath):
        return FileResponse(
            path,
            media_type=media_type,
            filename=filename,
            content_disposition_type=content_disposition_type,
            headers=dict(headers or {}),
        )

    size = path.stat().st_size
    out = dict(headers or {})
    out["Content-Length"] = str(size)
    if filename:
        out["Content-Disposition"] = _disposition(content_disposition_type, filename)

    def chunks():
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(READ_BUFFER)
                if not chunk:
                    return
                yield chunk

    return StreamingResponse(
        chunks(), media_type=media_type or guess_mime_type(path.name, None), headers=out
    )
