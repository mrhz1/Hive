"""Outbound email, over the relay Cloudera gives every workload on port 25.

The relay wants no credentials and no TLS -- it is reachable only from
inside the cluster network -- so the default configuration is exactly the
snippet the platform team hand out:

    server = smtplib.SMTP(HOST, 25)
    server.sendmail(sender, recipients, message)

SMTP_USER / SMTP_STARTTLS exist for the environments that do want them
(a laptop pointed at a real provider), not because production needs them.

Nothing here raises. An upload that succeeded must not be reported as
failed because a mail server was down, so every send returns a bool and
logs what happened.
"""
import os
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from typing import Iterable, List, Optional, Sequence

from app.logging_setup import get_logger

log = get_logger(__name__)

DEFAULT_PORT = 25

DEFAULT_TIMEOUT = 15.0


def _host() -> str:
    return (os.environ.get("SMTP_HOST") or "").strip()


def _port() -> int:
    try:
        return int(os.environ.get("SMTP_PORT", DEFAULT_PORT))
    except ValueError:
        log.warning("smtp_port_invalid", value=os.environ.get("SMTP_PORT"))
        return DEFAULT_PORT


def _timeout() -> float:
    try:
        return float(os.environ.get("SMTP_TIMEOUT", DEFAULT_TIMEOUT))
    except ValueError:
        return DEFAULT_TIMEOUT


def _sender() -> str:
    """The envelope sender, defaulted so a missing setting is not fatal."""
    return (os.environ.get("SMTP_FROM") or "hive-noreply@localhost").strip()


def _sender_name() -> str:
    return (os.environ.get("SMTP_FROM_NAME") or "Hive").strip()


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def is_configured() -> bool:
    """False when SMTP_HOST is unset -- sending is then a no-op, not an error."""
    return bool(_host())


def _clean_recipients(recipients: Iterable[Optional[str]]) -> List[str]:
    """Unique, non-blank addresses, in the order first seen."""
    seen: List[str] = []
    for address in recipients:
        value = (address or "").strip()
        if value and "@" in value and value not in seen:
            seen.append(value)
    return seen


def _build(
    to: Sequence[str], subject: str, body: str, html: Optional[str]
) -> EmailMessage:
    message = EmailMessage()
    message["From"] = formataddr((_sender_name(), _sender()))
    message["To"] = ", ".join(to)
    message["Subject"] = subject
    message.set_content(body)
    if html:
        message.add_alternative(html, subtype="html")
    return message


def send_email(
    to: Iterable[Optional[str]],
    subject: str,
    body: str,
    html: Optional[str] = None,
) -> bool:
    """Send one message. True when the relay accepted it."""
    recipients = _clean_recipients(to)
    if not recipients:
        log.info("email_skipped_no_recipient", subject=subject)
        return False

    host = _host()
    if not host:
        log.info("email_skipped_not_configured", subject=subject, to=recipients)
        return False

    message = _build(recipients, subject, body, html)

    try:
        server = smtplib.SMTP(host, _port(), timeout=_timeout())
        try:
            if _flag("SMTP_STARTTLS"):
                server.starttls()
            user = os.environ.get("SMTP_USER")
            if user:
                server.login(user, os.environ.get("SMTP_PASSWORD", ""))
            server.send_message(message)
        finally:
            try:
                server.quit()
            except Exception:  # pragma: no cover - the message already went
                server.close()
    except Exception as exc:
        log.error(
            "email_send_failed",
            subject=subject,
            to=recipients,
            host=host,
            port=_port(),
            error=str(exc),
        )
        return False

    log.info("email_sent", subject=subject, to=recipients, host=host)
    return True
