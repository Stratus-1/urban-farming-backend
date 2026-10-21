import asyncio
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

from app.core.config import Settings
from app.core.errors import AppError


@dataclass(slots=True)
class MailMessage:
    to: str
    subject: str
    text: str
    html: str | None = None
    reply_to: str | None = None


class EmailGateway:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.smtp_host and self.settings.smtp_from_email)

    async def send(self, message: MailMessage) -> None:
        if not self.configured:
            return

        email = EmailMessage()
        email["From"] = f"{self.settings.smtp_from_name} <{self.settings.smtp_from_email}>"
        email["To"] = message.to
        email["Subject"] = message.subject
        if message.reply_to:
            email["Reply-To"] = message.reply_to
        email.set_content(message.text)
        if message.html:
            email.add_alternative(message.html, subtype="html")

        def send_sync() -> None:
            with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=15) as smtp:
                smtp.starttls()
                smtp.ehlo()
                if self.settings.smtp_user and self.settings.smtp_password:
                    password = self.settings.smtp_password
                    if self.settings.smtp_host.casefold() == "smtp.gmail.com":
                        # Google displays app passwords in four-character groups;
                        # copied values may contain spaces that SMTP must not receive.
                        password = "".join(password.split())
                    if (
                        self.settings.smtp_host.casefold() == "smtp.gmail.com"
                        and "PLAIN" in smtp.esmtp_features.get("auth", "").upper().split()
                    ):
                        credentials = (
                            f"\x00{self.settings.smtp_user}\x00{password}"
                        )
                        smtp.auth(
                            "PLAIN",
                            lambda _challenge=None: credentials,
                        )
                    else:
                        smtp.login(self.settings.smtp_user, password)
                smtp.send_message(email)

        try:
            await asyncio.to_thread(send_sync)
        except smtplib.SMTPAuthenticationError as error:
            raise AppError(
                502,
                "email_authentication_failed",
                "The email provider rejected SMTP authentication",
            ) from error
        except (OSError, smtplib.SMTPException) as error:
            raise AppError(502, "email_delivery_failed", "Email delivery failed") from error
