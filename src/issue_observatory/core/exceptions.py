"""Application-wide exception hierarchy for Issue Observatory.

All custom exceptions subclass ``IssueObservatoryError``, enabling
consistent error handling and structured logging across the application.

Hierarchy::

    IssueObservatoryError
    ├── ArenaCollectionError
    ├── ArenaRateLimitError      (retry_after: float)
    ├── ArenaAuthError
    ├── NoCredentialAvailableError
    ├── CreditError
    │   ├── InsufficientCreditError
    │   └── CreditReservationError
    ├── NormalizationError
    └── EntityResolutionError
"""

from __future__ import annotations


class IssueObservatoryError(Exception):
    """Base class for all Issue Observatory exceptions.

    All application-specific exceptions inherit from this class so that
    callers can catch the entire hierarchy with a single ``except`` clause
    when needed.
    """


# ---------------------------------------------------------------------------
# Arena exceptions
# ---------------------------------------------------------------------------


class ArenaCollectionError(IssueObservatoryError):
    """Raised when an arena collector fails during data collection.

    Args:
        message: Human-readable description of the failure.
        arena: Name of the arena that failed (e.g. ``"google_search"``).
        platform: Platform identifier (e.g. ``"google"``).
    """

    def __init__(
        self,
        message: str,
        arena: str | None = None,
        platform: str | None = None,
    ) -> None:
        super().__init__(message)
        self.arena = arena
        self.platform = platform


class ArenaRateLimitError(ArenaCollectionError):
    """Raised when an arena hits a rate limit from an upstream API.

    Args:
        message: Human-readable description of the rate limit.
        retry_after: Seconds to wait before retrying. Defaults to 60.
        arena: Name of the arena that was rate-limited.
        platform: Platform identifier.
    """

    def __init__(
        self,
        message: str,
        retry_after: float = 60.0,
        arena: str | None = None,
        platform: str | None = None,
    ) -> None:
        super().__init__(message, arena=arena, platform=platform)
        self.retry_after = retry_after


class ArenaAuthError(ArenaCollectionError):
    """Raised when authentication with an upstream API fails.

    This typically indicates an invalid or expired API credential. The
    credential pool should mark the credential as errored and attempt
    rotation to an alternative.
    """


# ---------------------------------------------------------------------------
# Credential exceptions
# ---------------------------------------------------------------------------


class NoCredentialAvailableError(IssueObservatoryError):
    """Raised when the credential pool has no usable credential for a request.

    This may occur because all credentials are exhausted, on cooldown, or
    inactive. When this is raised, the arena should return empty results or
    reschedule the task rather than failing the entire collection run.

    Args:
        platform: Platform identifier for which no credential is available.
        tier: Requested tier (``"free"``, ``"medium"``, ``"premium"``).
    """

    def __init__(
        self,
        platform: str | None = None,
        tier: str | None = None,
    ) -> None:
        msg = "No credential available"
        if platform:
            msg += f" for platform '{platform}'"
        if tier:
            msg += f" at tier '{tier}'"
        super().__init__(msg)
        self.platform = platform
        self.tier = tier


# ---------------------------------------------------------------------------
# Credit exceptions
# ---------------------------------------------------------------------------


class CreditError(IssueObservatoryError):
    """Base class for credit-system errors."""


class InsufficientCreditError(CreditError):
    """Raised when a user does not have enough credits for a requested action.

    Args:
        required: Number of credits required.
        available: Number of credits the user currently holds.
        user_id: UUID string of the user (for logging).
    """

    def __init__(
        self,
        required: int,
        available: int,
        user_id: str | None = None,
    ) -> None:
        super().__init__(
            f"Insufficient credits: required {required}, available {available}"
        )
        self.required = required
        self.available = available
        self.user_id = user_id


class CreditReservationError(CreditError):
    """Raised when a credit reservation cannot be created or updated.

    This covers race conditions, database failures, and invalid reservation
    states (e.g. attempting to settle a reservation that does not exist).

    Args:
        message: Description of the reservation failure.
        collection_run_id: UUID string of the affected collection run.
    """

    def __init__(
        self,
        message: str,
        collection_run_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.collection_run_id = collection_run_id


# ---------------------------------------------------------------------------
# Data-processing exceptions
# ---------------------------------------------------------------------------


class NormalizationError(IssueObservatoryError):
    """Raised when a raw platform record cannot be normalized.

    Args:
        message: Description of the normalization failure.
        platform: Platform identifier of the raw record.
        raw_item: The raw dict that could not be normalized (for debugging).
    """

    def __init__(
        self,
        message: str,
        platform: str | None = None,
        raw_item: dict | None = None,  # type: ignore[type-arg]
    ) -> None:
        super().__init__(message)
        self.platform = platform
        self.raw_item = raw_item


class EntityResolutionError(IssueObservatoryError):
    """Raised when actor entity resolution fails.

    Args:
        message: Description of the resolution failure.
        platform: Platform on which resolution was attempted.
        platform_user_id: Platform-native user identifier that could not be resolved.
    """

    def __init__(
        self,
        message: str,
        platform: str | None = None,
        platform_user_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.platform = platform
        self.platform_user_id = platform_user_id
