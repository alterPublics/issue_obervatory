"""Shared slowapi rate-limiter singleton.

Keeping the ``Limiter`` instance in its own module breaks the circular
import that would arise if route modules imported directly from ``main.py``
(which itself imports every route module).

Usage in route modules::

    from issue_observatory.api.limiter import limiter

    @router.get("/export")
    @limiter.limit("10/minute")
    async def export_content(request: Request, ...):
        ...

The ``request`` parameter **must** be present in the route function
signature for slowapi to resolve the rate-limit key.

The ``Limiter`` is configured in ``main.create_app()`` where it is
attached to ``app.state`` and the ``SlowAPIMiddleware`` is registered.
This module only constructs the instance; ``main.py`` wires it into the
application.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter: Limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["100/minute"],
)
"""Global rate-limiter instance.

Default limit: 100 requests/minute per IP address (enforced globally via
``SlowAPIMiddleware`` registered in ``main.create_app()``).

Individual routes apply stricter limits with ``@limiter.limit("N/minute")``.
"""
