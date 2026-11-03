"""Researcher projects in Cloudera AI (CAI).

The staging project (owned by the service account) holds the Zone 2 safe
copies, one folder per release: ``<project code>/<release id>/``. For each
researcher we fork staging into a new private project, delete everything the
researcher may not see, check that exactly the allowed files are left, and
only then add the researcher as a collaborator. Any failure before that last
step deletes the new project, so a half-pruned copy is never handed out.

This must run with Cloudera's "Run as <service account>" setting, so that
``cmlapi.default_client()`` acts as the service account. The cmlapi in this
workspace is the old swagger-codegen client; errors are
``cmlapi.rest.ApiException`` with ``status`` and ``body``.

Nothing here reads file contents. Logs carry counts and file_refs (see
app.logging_setup.ref), never file names, following the rest of the app.
"""

import mimetypes
import os
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

from app.logging_setup import get_logger, ref

log = get_logger(__name__)

WRITE = "write"
TEMPLATE = "blank"
ENGINE = "ml_runtime"

Tree = Dict[str, bool]


class ProvisioningError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        self.status = status
        self.body = body
        super().__init__(message)


def staging_project_id() -> str:
    value = (os.environ.get("STAGING_PROJECT_ID") or "").strip()
    if not value:
        raise ProvisioningError("STAGING_PROJECT_ID is not set")
    return value


def base_url() -> str:
    value = (os.environ.get("CAI_BASE_URL") or "").strip()
    if not value and os.environ.get("CDSW_DOMAIN"):
        value = f"https://{os.environ['CDSW_DOMAIN']}"
    if not value:
        raise ProvisioningError("CAI_BASE_URL is not set")
    return value.rstrip("/")


def _float_env(name: str, default: float) -> float:
    try:
        return max(1.0, float(os.environ.get(name, default)))
    except ValueError:
        return default


def fork_timeout() -> float:
    return _float_env("CAI_FORK_TIMEOUT_SECONDS", 300)


def poll_interval() -> float:
    return _float_env("CAI_FORK_POLL_SECONDS", 5)


def client():
    try:
        import cmlapi
    except ImportError as exc:
        raise ProvisioningError(
            "cmlapi is not installed; researcher projects can only be made "
            "from inside Cloudera AI"
        ) from exc
    return cmlapi.default_client()


def _is_api_error(exc: Exception) -> bool:
    return type(exc).__name__ == "ApiException" and hasattr(exc, "status")


def _call(action: str, fn: Callable, *args):
    try:
        return fn(*args)
    except Exception as exc:
        if not _is_api_error(exc):
            raise
        status = getattr(exc, "status", None)
        body = str(getattr(exc, "body", "") or getattr(exc, "reason", "") or "")[:500]
        log.warning("cai_api_error", action=action, status=status, body=body)
        raise ProvisioningError(
            f"Cloudera AI could not {action} ({status}): {body or 'no detail'}",
            status=status,
            body=body,
        ) from exc


def _norm(path: str) -> str:
    text = str(path or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.strip("/")


def clean_keep_paths(keep_paths: Iterable[str]) -> List[str]:
    out = []
    for raw in keep_paths:
        path = _norm(raw)
        if not path or any(part in ("", ".", "..") for part in path.split("/")):
            raise ProvisioningError(f"'{raw}' is not a valid path")
        if path not in out:
            out.append(path)
    if not out:
        raise ProvisioningError("No files were chosen for the researcher")
    return out


def _covered(path: str, keep: List[str]) -> bool:
    return any(path == k or path.startswith(k + "/") for k in keep)


def _is_ancestor(path: str, keep: List[str]) -> bool:
    return any(k.startswith(path + "/") for k in keep)


def _allowed(path: str, is_dir: bool, keep: List[str]) -> bool:
    return _covered(path, keep) or (is_dir and _is_ancestor(path, keep))


def list_tree(api, project_id: str, start: str = "") -> Tree:
    """Every file and folder of a project (or under `start`), as {path: is_dir}."""
    tree: Tree = {}
    start = _norm(start)
    pending = [start]
    while pending:
        folder = pending.pop()
        try:
            response = _call("list the project's files", api.list_project_files, project_id, folder or "/")
        except ProvisioningError as exc:
            if start and folder == start and exc.status == 404:
                return tree  # the folder isn't there yet
            raise
        for entry in getattr(response, "files", None) or []:
            name = _norm(getattr(entry, "path", ""))
            if folder and not name.startswith(folder + "/"):
                name = f"{folder}/{name}" if name else ""
            if not name or name == folder or name in tree:
                continue
            is_dir = bool(getattr(entry, "is_dir", False))
            tree[name] = is_dir
            if is_dir:
                pending.append(name)
    return tree


def expected_tree(staging: Tree, keep: List[str]) -> Tree:
    return {p: d for p, d in staging.items() if _allowed(p, d, keep)}


def files_of(tree: Tree) -> List[str]:
    return sorted(p for p, is_dir in tree.items() if not is_dir)


def list_staging_files(staging_id: Optional[str] = None, api=None) -> List[dict]:
    api = api or client()
    tree = list_tree(api, staging_id or staging_project_id())
    return [{"path": p, "is_dir": tree[p]} for p in sorted(tree)]


UPLOAD_TIMEOUT_SECONDS = 600


def _upload_one(api, project_id: str, remote_path: str, local_path: Path) -> None:
    """Upload one file to `remote_path` in the project.

    cmlapi's upload_file(project_id, file=<local path>) names the upload after
    the file's basename, which would land everything in the project root. The
    endpoint takes the multipart filename as the path, so we call the same
    endpoint (POST /api/v2/projects/{id}/files) with the filename we want.
    """
    mime = mimetypes.guess_type(remote_path)[0] or "application/octet-stream"
    data = local_path.read_bytes()

    def send():
        return api.api_client.call_api(
            "/api/v2/projects/{project_id}/files", "POST",
            path_params={"project_id": project_id},
            query_params=[],
            header_params={"Content-Type": "multipart/form-data"},
            post_params=[("file", (remote_path, data, mime))],
            files={},
            response_type=None,
            auth_settings=[],
            _return_http_data_only=True,
            _preload_content=True,
            _request_timeout=UPLOAD_TIMEOUT_SECONDS,
            collection_formats={},
        )

    _call("upload a file to staging", send)


def upload_folder(local_dir: Path, remote_folder: str, staging_id: Optional[str] = None, api=None) -> dict:
    """Copy every file under `local_dir` to `remote_folder/` in staging.

    Files already in staging at the same path are skipped, so this is safe to
    run again after a failure. Afterwards every file must be at its exact path;
    if Cloudera AI put an upload anywhere else (e.g. the project root), the
    stray copy is deleted and this fails rather than leave a mess in staging.
    """
    local_dir = Path(local_dir)
    remote_folder = clean_keep_paths([remote_folder])[0]
    if not local_dir.is_dir():
        raise ProvisioningError(f"The release folder is not on the API's disk: {local_dir}")
    wanted = {
        f"{remote_folder}/{p.relative_to(local_dir).as_posix()}": p
        for p in sorted(local_dir.rglob("*"))
        if p.is_file()
    }
    if not wanted:
        raise ProvisioningError("The release folder holds no files")

    staging_id = staging_id or staging_project_id()
    api = api or client()
    before_root = {p for p, is_dir in list_tree_level(api, staging_id, "").items() if not is_dir}
    present = list_tree(api, staging_id, remote_folder)
    todo = [path for path in wanted if path not in present]
    for path in todo:
        _upload_one(api, staging_id, path, wanted[path])

    after = list_tree(api, staging_id, remote_folder)
    missing = [path for path in wanted if after.get(path) is not False]
    if missing:
        strays = [
            p for p, is_dir in list_tree_level(api, staging_id, "").items()
            if not is_dir and p not in before_root
        ]
        for stray in strays:
            try:
                _delete(api, staging_id, stray)
            except ProvisioningError:
                log.error("cai_stray_upload_left", staging_id=staging_id, file_ref=ref(stray))
        raise ProvisioningError(
            f"{len(missing)} file(s) did not arrive at their path in staging"
            + (f"; Cloudera AI put {len(strays)} in the project root (removed)" if strays else "")
        )
    log.info("cai_staging_synced", files=len(wanted), uploaded=len(todo), folder_ref=ref(remote_folder))
    return {"uploaded": len(todo), "skipped": len(wanted) - len(todo), "files": len(wanted)}


def list_tree_level(api, project_id: str, folder: str) -> Tree:
    """The entries directly inside one folder, without recursing."""
    response = _call("list the project's files", api.list_project_files, project_id, _norm(folder) or "/")
    out: Tree = {}
    for entry in getattr(response, "files", None) or []:
        name = _norm(getattr(entry, "path", ""))
        if folder and name and not name.startswith(_norm(folder) + "/"):
            name = f"{_norm(folder)}/{name}"
        if name:
            out[name] = bool(getattr(entry, "is_dir", False))
    return out


def in_staging(path: str, staging_id: Optional[str] = None, api=None) -> bool:
    """Whether a folder or file exists in staging, listing only its parent folder."""
    target = _norm(path)
    if not target:
        return False
    api = api or client()
    parent = target.rsplit("/", 1)[0] if "/" in target else ""
    try:
        response = _call(
            "list the staging files", api.list_project_files,
            staging_id or staging_project_id(), parent or "/",
        )
    except ProvisioningError as exc:
        if exc.status == 404:  # the parent folder isn't there, so neither is the target
            return False
        raise
    for entry in getattr(response, "files", None) or []:
        name = _norm(getattr(entry, "path", ""))
        if name == target or (parent and f"{parent}/{name}" == target):
            return True
    return False


def _wait_for_fork(api, project_id: str, staging: Tree, timeout: float, interval: float,
                   sleep: Callable = time.sleep, clock: Callable = time.monotonic) -> Tree:
    wanted = set(staging)
    deadline = clock() + timeout
    seen = 0
    while True:
        try:
            tree = list_tree(api, project_id)
        except ProvisioningError as exc:
            if exc.status not in (404, 409, 500, 502, 503):
                raise
            tree = {}
        seen = len(wanted & set(tree))
        if seen == len(wanted):
            return tree
        if clock() >= deadline:
            raise ProvisioningError(
                f"The fork did not finish copying in {int(timeout)} seconds "
                f"({seen} of {len(wanted)} items arrived)"
            )
        sleep(interval)


def _delete(api, project_id: str, path: str) -> None:
    _call(f"delete file {ref(path)}", api.delete_project_file, project_id, path)


def _prune(api, project_id: str, tree: Tree, keep: List[str]) -> int:
    """Delete what the researcher may not have. Top-down, so a whole folder goes in one call."""
    gone: List[str] = []
    deleted = 0
    for path in sorted(tree, key=lambda p: (p.count("/"), p)):
        if _allowed(path, tree[path], keep):
            continue
        if any(path.startswith(d + "/") for d in gone):
            continue
        try:
            _delete(api, project_id, path)
        except ProvisioningError:
            if not tree[path]:
                raise
            # The API may refuse a non-empty folder: empty it deepest-first, then retry.
            inside = [p for p in tree if p.startswith(path + "/")]
            for child in sorted(inside, key=lambda p: -p.count("/")):
                _delete(api, project_id, child)
            _delete(api, project_id, path)
        if tree[path]:
            gone.append(path)
        deleted += 1
    return deleted


def _verify(final: Tree, expected: Tree) -> None:
    extra = sorted(p for p in final if p not in expected)
    missing = sorted(p for p in expected if p not in final)
    wrong = sorted(p for p in expected if p in final and final[p] != expected[p])
    if extra or missing or wrong:
        log.error(
            "cai_verify_failed",
            extra=len(extra), missing=len(missing), wrong_kind=len(wrong),
            extra_refs=[ref(p) for p in extra[:10]], missing_refs=[ref(p) for p in missing[:10]],
        )
        raise ProvisioningError(
            "The new project does not hold exactly the chosen files "
            f"({len(extra)} unexpected, {len(missing)} missing, {len(wrong)} changed kind); "
            "it was deleted"
        )


def _owner(project) -> str:
    owner = getattr(project, "owner", None)
    return getattr(owner, "username", None) or (os.environ.get("CAI_PROJECT_OWNER") or "").strip()


def project_url(project) -> str:
    owner, slug = _owner(project), getattr(project, "slug", "") or ""
    if not owner or not slug:
        return ""
    return f"{base_url()}/{owner}/{slug}"


def _rollback(api, project_id: str, reason: str) -> None:
    try:
        _call("delete the half-made project", api.delete_project, project_id)
        log.warning("cai_provision_rolled_back", cai_project_id=project_id, reason=reason)
    except Exception as exc:
        # The researcher was never added, so nobody but the service account can open it.
        log.error("cai_rollback_failed", cai_project_id=project_id, reason=reason, error=str(exc))


def provision_researcher(
    username: str,
    project_name: str,
    keep_paths: Iterable[str],
    staging_id: Optional[str] = None,
    description: str = "",
    api=None,
    sleep: Callable = time.sleep,
    clock: Callable = time.monotonic,
) -> dict:
    username = (username or "").strip()
    if not username:
        raise ProvisioningError("A Cloudera AI username is required")
    keep = clean_keep_paths(keep_paths)
    staging_id = staging_id or staging_project_id()
    api = api or client()

    staging = list_tree(api, staging_id)
    unknown = [k for k in keep if k not in staging]
    if unknown:
        raise ProvisioningError("Not in the staging project: " + ", ".join(unknown[:10]))
    expected = expected_tree(staging, keep)
    if not files_of(expected):
        raise ProvisioningError("The chosen folders hold no files")

    import cmlapi

    request = cmlapi.CreateProjectRequest(
        name=project_name,
        description=description,
        visibility="private",
        template=TEMPLATE,
        default_project_engine_type=ENGINE,
        parent_project=staging_id,
    )
    project = _call("create the project", api.create_project, request)
    project_id = project.id
    log.info("cai_fork_started", cai_project_id=project_id, username=username, keep=len(keep))

    try:
        tree = _wait_for_fork(api, project_id, staging, fork_timeout(), poll_interval(), sleep, clock)
        deleted = _prune(api, project_id, tree, keep)
        final = list_tree(api, project_id)
        _verify(final, expected)
        if not getattr(project, "slug", None) or not _owner(project):
            project = _call("read the project", api.get_project, project_id)
        # When the API runs as the researcher themselves (testing without the
        # service account), they already own the copy and CAI refuses to add an
        # owner as a collaborator.
        if _owner(project).lower() != username.lower():
            _call(
                f"add '{username}' to the project",
                api.add_project_collaborator,
                cmlapi.AddProjectCollaboratorRequest(permission=WRITE),
                project_id,
                username,
            )
    except BaseException as exc:
        _rollback(api, project_id, str(exc)[:200])
        raise

    files = files_of(final)
    log.info(
        "cai_provisioned", cai_project_id=project_id, username=username,
        files=len(files), deleted=deleted,
    )
    return {
        "project_id": project_id,
        "slug": getattr(project, "slug", "") or "",
        "url": project_url(project),
        "files": files,
    }


def deprovision(project_id: str, api=None) -> bool:
    """Delete a researcher project. False if it was already gone."""
    api = api or client()
    try:
        _call("delete the project", api.delete_project, project_id)
    except ProvisioningError as exc:
        if exc.status == 404:
            log.info("cai_deprovision_already_gone", cai_project_id=project_id)
            return False
        raise
    log.info("cai_deprovisioned", cai_project_id=project_id)
    return True
