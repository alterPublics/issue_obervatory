"""YouTube arena package.

Provides the YouTube Data API v3 collector for the Issue Observatory.
Register the arena by importing this package or the collector module directly.

The collector is registered in the arena registry via the ``@register``
decorator in :mod:`.collector`.  The standalone router is exposed via
:attr:`.router.router` and mounted in the main FastAPI application.

RSS-first strategy: channel feeds are polled at zero quota cost before
falling back to the ``search.list`` API endpoint (100 units per call).

Credential environment variable convention (env-var fallback)::

    YOUTUBE_FREE_API_KEY         # first GCP project key
    YOUTUBE_FREE_API_KEY_2       # second GCP project key
    YOUTUBE_FREE_API_KEY_3       # third GCP project key
    ...                          # add more keys to multiply daily quota
"""

from issue_observatory.arenas.youtube.collector import YouTubeCollector

__all__ = ["YouTubeCollector"]
