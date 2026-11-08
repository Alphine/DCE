"""Outgoing email for account recovery over SMTP (STARTTLS). Used only for password reset links.

The SMTP password, reset tokens, and message bodies are never logged. A failure raises MailError without the
underlying SMTP text, because SMTP errors can echo the account name.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from typing import Protocol

from app.config import Settings

logger = logging.getLogger("dce.mail")


class MailError(Exception):
    """The message could not be sent. The text is safe to show to a caller."""


class Mailer(Protocol):
    def send(self, to: str, subject: str, body: str) -> None: ...


class SmtpMailer:
    def __init__(self, settings: Settings) -> None:
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._user = settings.smtp_user
        self._password = settings.smtp_password
        self._from = settings.smtp_from or settings.smtp_user

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=20) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(self._user, self._password.get_secret_value())
                smtp.send_message(message)
        except (smtplib.SMTPException, OSError):
            logger.error("SMTP send failed (host=%s port=%s)", self._host, self._port)
            raise MailError("The email could not be sent. Try again later or ask an Admin.") from None
