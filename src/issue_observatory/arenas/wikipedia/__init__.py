"""Wikipedia arena for The Issue Observatory.

Collects editorial attention signals from Wikipedia via the MediaWiki Action
API and the Wikimedia Analytics (Pageviews) API.  Wikipedia's value for issue
tracking lies not in its encyclopedic content, but in the *signals* it
produces: which articles are being edited, by whom, how frequently, and how
many people are reading articles on contested topics.

Two record types are produced:

- ``wiki_revision``: A single edit to a Wikipedia article.  The
  ``text_content`` field contains the editor's edit summary (comment), not the
  full article text.  Most analysis focuses on edit frequency and editor
  identity rather than summary text.

- ``wiki_pageview``: An aggregated daily pageview count for a specific article
  on a specific date.  The primary data point is ``views_count``.

Both record types belong to the ``"reference"`` arena group, which groups
encyclopedic and reference sources distinct from social media or news.

**Danish focus**: The collector queries ``da.wikipedia.org`` by default
(Danish Wikipedia, ~290 000 articles).  English Wikipedia is also queried
when the ``language_filter`` includes ``"en"`` or is ``None``.

**No credentials required**: All MediaWiki read endpoints are unauthenticated.
Only a descriptive ``User-Agent`` header is required by Wikimedia policy.

**Rate limiting**: 5 requests per second via ``asyncio.Semaphore``.

See :mod:`issue_observatory.arenas.wikipedia.collector` for the full
implementation and :mod:`issue_observatory.arenas.wikipedia.config` for
all tunable constants.
"""
