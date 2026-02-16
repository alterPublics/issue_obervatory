"""Common Crawl arena package.

Provides index-based access to the Common Crawl web archive via the
CC Index API. Queries return index metadata (URL, timestamp, WARC location)
rather than full page content. WARC record retrieval is out of scope.

No credentials are required. Rate limit: 1 request/second courtesy throttle.
"""
