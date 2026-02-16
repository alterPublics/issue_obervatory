"""Wayback Machine arena package.

Provides CDX API access to the Internet Archive's Wayback Machine for
historical web page snapshots. Queries return capture metadata (URL,
timestamp, digest) from the CDX index.

No credentials are required. Rate limit: 1 request/second courtesy throttle.
The Internet Archive's infrastructure can be fragile; implement robust error
handling and do not depend on availability for time-sensitive research.
"""
