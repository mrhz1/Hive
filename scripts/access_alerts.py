import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _repo_root():
    here = globals().get("__file__")
    candidates = []
    if here:
        own = Path(here).resolve().parent
        candidates += [own, own.parent]
    for var in ("HIVE_REPO_ROOT", "CDSW_PROJECT_DIR"):
        if os.environ.get(var):
            candidates.append(Path(os.environ[var]))
    cwd = Path.cwd().resolve()
    candidates += [cwd, cwd.parent]
    for candidate in candidates:
        if (candidate / "app" / "db.py").is_file():
            return candidate
    raise RuntimeError("Cannot locate the repo root; set HIVE_REPO_ROOT")


sys.path.insert(0, str(_repo_root()))

from app.access_log import AUTH_FAILURE, DENIED, DOWNLOAD, EXPORT  # noqa: E402
from app.crud import access_log as crud  # noqa: E402
from app.db import hive_cursor  # noqa: E402
from app.logging_setup import configure_logging, get_logger  # noqa: E402
from app.mailer import send_email  # noqa: E402

log = get_logger(__name__)

DEFAULT_WINDOW_MINUTES = 60


def _threshold(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def rules():
    return (
        {
            "name": "identified downloads",
            "action": DOWNLOAD,
            "identified_only": True,
            "outcome": None,
            "limit": _threshold("ALERT_DOWNLOAD_LIMIT", 50),
            "why": "Bulk retrieval of identified documents by one account.",
        },
        {
            "name": "metadata exports",
            "action": EXPORT,
            "identified_only": False,
            "outcome": None,
            "limit": _threshold("ALERT_EXPORT_LIMIT", 5),
            "why": "Exports leave with many records at once.",
        },
        {
            "name": "permission denials",
            "action": DENIED,
            "identified_only": False,
            "outcome": "denied",
            "limit": _threshold("ALERT_DENIED_LIMIT", 15),
            "why": "Repeated refusals across resources look like probing.",
        },
        {
            "name": "authentication failures",
            "action": AUTH_FAILURE,
            "identified_only": False,
            "outcome": "failure",
            "limit": _threshold("ALERT_AUTH_FAILURE_LIMIT", 10),
            "why": (
                "Only failures that reached the app are here -- the proxy "
                "sees the rest, and those logs have to be read there."
            ),
        },
    )


def recipients():
    raw = os.environ.get("ALERT_EMAIL_TO") or ""
    return [address.strip() for address in raw.split(",") if address.strip()]


def breaches(cursor, since, day_from):
    found = []

    for rule in rules():
        try:
            rows = crud.count_by_actor(
                cursor,
                action=rule["action"],
                date_from=day_from,
                since=since,
                outcome=rule["outcome"],
                identified_only=rule["identified_only"],
            )
        except Exception as exc:
            log.error("alert_query_failed", rule=rule["name"], error=str(exc))
            continue

        for actor_username, actor_id, hits, patients in rows:
            if hits >= rule["limit"]:
                found.append(
                    {
                        "rule": rule["name"],
                        "why": rule["why"],
                        "actor": actor_username or actor_id or "(unknown)",
                        "hits": int(hits),
                        "patients": int(patients or 0),
                        "limit": rule["limit"],
                    }
                )

    return found


def message(found, window_minutes, since):
    lines = [
        f"{len(found)} threshold(s) crossed in the last {window_minutes} minutes.",
        f"Window opened {since.isoformat(timespec='seconds')}.",
        "",
    ]
    for item in found:
        lines.append(f"* {item['rule']}: {item['actor']}")
        lines.append(
            f"    {item['hits']} events (threshold {item['limit']}), "
            f"{item['patients']} distinct patients"
        )
        lines.append(f"    {item['why']}")
        lines.append("")

    lines += [
        "Check the Access log page, filtered to that account and window.",
        "",
        "-- Hive",
    ]
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--window",
        type=int,
        default=int(os.environ.get("ALERT_WINDOW_MINUTES", DEFAULT_WINDOW_MINUTES)),
        help="How many minutes back to look.",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report to stdout, send nothing."
    )
    args = parser.parse_args(argv)

    configure_logging()

    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=args.window)
    day_from = since.strftime("%Y-%m-%d")

    with hive_cursor() as cursor:
        found = breaches(cursor, since, day_from)

    if not found:
        log.info("access_alerts_clear", window_minutes=args.window)
        print(f"nothing over threshold in the last {args.window} minutes")
        return 0

    body = message(found, args.window, since)
    log.warning(
        "access_alerts_raised",
        window_minutes=args.window,
        breaches=[f"{i['rule']}:{i['actor']}:{i['hits']}" for i in found],
    )
    print(body)

    if args.dry_run:
        return 0

    to = recipients()
    if not to:
        log.error("access_alerts_no_recipients", detail="set ALERT_EMAIL_TO")
        return 1

    send_email(to, f"Hive: {len(found)} access threshold(s) crossed", body)
    return 0


if __name__ == "__main__":
    sys.exit(main())
