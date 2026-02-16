"""Email notification service for collection lifecycle events.

Sends transactional emails for:
- Collection run failures (per-arena or whole-run).
- Successful batch run completion.
- Low credit-balance warnings after settlement.

All send methods are ``async`` and should be dispatched fire-and-forget
via ``asyncio.create_task()`` from HTTP route handlers so they never delay
the HTTP response.

When ``smtp_host`` is not configured in :class:`~issue_observatory.config.settings.Settings`,
every send method silently no-ops and logs at ``DEBUG`` level.  This means
the service is safe to import and instantiate in all environments, including
CI and local development without an SMTP server.

Usage in a FastAPI route::

    from issue_observatory.core.email_service import get_email_service

    @router.post("/collections/")
    async def create_run(
        ...
        email_svc: Annotated[EmailService, Depends(get_email_service)],
    ):
        ...
        if run.status == "failed":
            asyncio.create_task(
                email_svc.send_collection_failure(
                    user_email=current_user.email,
                    run_id=run.id,
                    arena="all",
                    error="Orchestration error",
                )
            )

Decision record: ``/docs/decisions/0003-fastapi-mail.md``.
"""

from __future__ import annotations

import logging
import uuid
from functools import lru_cache
from typing import Optional

import structlog

from issue_observatory.config.settings import Settings, get_settings

logger = structlog.get_logger(__name__)
_stdlib_logger = logging.getLogger(__name__)


class EmailService:
    """Sends transactional notification emails via SMTP using ``fastapi-mail``.

    The service is intentionally lazy: it does not open any network connection
    at construction time.  :class:`fastapi_mail.FastMail` handles connection
    pooling internally.

    When ``smtp_host`` is ``None`` (the default), :meth:`is_configured` returns
    ``False`` and all send methods immediately return without raising.

    Args:
        settings: Application settings instance.  Defaults to the global
            cached settings singleton if omitted.
    """

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._mail: object = None  # FastMail instance or None

        if self._settings.smtp_host:
            try:
                from fastapi_mail import ConnectionConfig, FastMail  # noqa: PLC0415

                config = ConnectionConfig(
                    MAIL_USERNAME=self._settings.smtp_username or "",
                    MAIL_PASSWORD=self._settings.smtp_password or "",
                    MAIL_FROM=self._settings.smtp_from_address,
                    MAIL_PORT=self._settings.smtp_port,
                    MAIL_SERVER=self._settings.smtp_host,
                    MAIL_STARTTLS=self._settings.smtp_starttls,
                    MAIL_SSL_TLS=self._settings.smtp_ssl,
                    USE_CREDENTIALS=bool(self._settings.smtp_username),
                    VALIDATE_CERTS=True,
                )
                self._mail = FastMail(config)
            except ImportError:
                _stdlib_logger.warning(
                    "email_service: fastapi-mail is not installed; "
                    "email notifications are disabled.  "
                    "Run: pip install 'issue-observatory[email]' or "
                    "pip install fastapi-mail>=1.4,<2.0"
                )

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def is_configured(self) -> bool:
        """Return ``True`` if SMTP is configured and fastapi-mail is available.

        Returns:
            ``True`` when the service can send emails; ``False`` otherwise.
        """
        return self._mail is not None

    async def send_collection_failure(
        self,
        user_email: str,
        run_id: uuid.UUID,
        arena: str,
        error: str,
    ) -> None:
        """Notify a user that a collection run (or arena task) has failed.

        Silently no-ops if SMTP is not configured.

        Args:
            user_email: Recipient email address.
            run_id: UUID of the failed collection run.
            arena: Name of the arena that failed, or ``"all"`` for a
                whole-run failure.
            error: Human-readable error description.
        """
        if not self.is_configured():
            _stdlib_logger.debug(
                "email_service: SMTP not configured — skipping send_collection_failure "
                "run_id=%s arena=%s",
                run_id,
                arena,
            )
            return

        subject = f"[Issue Observatory] Collection run failed — {arena}"
        body = (
            f"Your collection run has encountered an error.\n\n"
            f"Run ID : {run_id}\n"
            f"Arena  : {arena}\n"
            f"Error  : {error}\n\n"
            f"Log in to the Issue Observatory to review the run details "
            f"and retry or adjust your query design."
        )
        await self._send(recipient=user_email, subject=subject, body=body)
        logger.info(
            "email_service: sent collection_failure",
            run_id=str(run_id),
            arena=arena,
            recipient=user_email,
        )

    async def send_low_credit_warning(
        self,
        user_email: str,
        remaining_credits: int,
        threshold: int,
    ) -> None:
        """Notify a user that their credit balance has fallen below the threshold.

        Silently no-ops if SMTP is not configured.

        Args:
            user_email: Recipient email address.
            remaining_credits: Current credit balance after settlement.
            threshold: The configured warning threshold that was crossed.
        """
        if not self.is_configured():
            _stdlib_logger.debug(
                "email_service: SMTP not configured — skipping send_low_credit_warning "
                "remaining=%d threshold=%d",
                remaining_credits,
                threshold,
            )
            return

        subject = "[Issue Observatory] Low credit balance warning"
        body = (
            f"Your Issue Observatory credit balance is running low.\n\n"
            f"Remaining credits : {remaining_credits}\n"
            f"Warning threshold : {threshold}\n\n"
            f"Please contact your project administrator to allocate additional "
            f"credits before your next collection run."
        )
        await self._send(recipient=user_email, subject=subject, body=body)
        logger.info(
            "email_service: sent low_credit_warning",
            remaining=remaining_credits,
            threshold=threshold,
            recipient=user_email,
        )

    async def send_collection_complete(
        self,
        user_email: str,
        run_id: uuid.UUID,
        records_collected: int,
    ) -> None:
        """Notify a user that a batch collection run has completed successfully.

        Silently no-ops if SMTP is not configured.

        Args:
            user_email: Recipient email address.
            run_id: UUID of the completed collection run.
            records_collected: Total records collected across all arenas.
        """
        if not self.is_configured():
            _stdlib_logger.debug(
                "email_service: SMTP not configured — skipping send_collection_complete "
                "run_id=%s records=%d",
                run_id,
                records_collected,
            )
            return

        subject = "[Issue Observatory] Collection run complete"
        body = (
            f"Your collection run has finished.\n\n"
            f"Run ID           : {run_id}\n"
            f"Records collected: {records_collected:,}\n\n"
            f"Log in to the Issue Observatory to browse and export your data."
        )
        await self._send(recipient=user_email, subject=subject, body=body)
        logger.info(
            "email_service: sent collection_complete",
            run_id=str(run_id),
            records=records_collected,
            recipient=user_email,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send(self, recipient: str, subject: str, body: str) -> None:
        """Send a plain-text email via fastapi-mail.

        Failures are caught, logged at WARNING level, and swallowed so that
        an SMTP outage never propagates to the HTTP response layer.

        Args:
            recipient: Destination email address.
            subject: Email subject line.
            body: Plain-text message body.
        """
        try:
            from fastapi_mail import MessageSchema, MessageType  # noqa: PLC0415

            message = MessageSchema(
                subject=subject,
                recipients=[recipient],
                body=body,
                subtype=MessageType.plain,
            )
            await self._mail.send_message(message)  # type: ignore[union-attr]
        except Exception as exc:  # noqa: BLE001
            _stdlib_logger.warning(
                "email_service: failed to send email to %s subject=%r: %s",
                recipient,
                subject,
                exc,
            )


# ---------------------------------------------------------------------------
# FastAPI dependency
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _get_email_service_singleton() -> EmailService:
    """Return the cached EmailService singleton.

    The singleton is safe because ``EmailService`` holds no mutable per-request
    state — fastapi-mail's connection pool is internally thread/coroutine-safe.

    Returns:
        The application-wide ``EmailService`` instance.
    """
    return EmailService(settings=get_settings())


def get_email_service() -> EmailService:
    """FastAPI dependency that returns the shared ``EmailService`` singleton.

    Usage::

        @router.post("/collections/")
        async def create_run(
            email_svc: Annotated[EmailService, Depends(get_email_service)],
        ):
            ...

    Returns:
        The cached :class:`EmailService` instance.
    """
    return _get_email_service_singleton()
