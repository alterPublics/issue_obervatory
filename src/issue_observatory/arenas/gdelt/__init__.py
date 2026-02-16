"""GDELT DOC 2.0 API arena — free global news monitoring with Danish filtering.

Queries the GDELT DOC 2.0 API for articles matching search terms, filtering by
Danish source country (FIPS code ``DA``) and/or language (``danish``).  GDELT
machine-translates non-English content, so both Danish and English query terms
may be needed for full coverage.

Collectors:
    :class:`~issue_observatory.arenas.gdelt.collector.GDELTCollector`

Tasks:
    :mod:`issue_observatory.arenas.gdelt.tasks`

Router:
    :mod:`issue_observatory.arenas.gdelt.router`

Configuration:
    :mod:`issue_observatory.arenas.gdelt.config`

Notes:
    - GDELT DOC API provides a rolling 3-month window only.
    - ``collect_by_actors()`` is not supported (raises ``NotImplementedError``).
    - Rate limit: max 1 request/second (empirical; no formal published limit).
    - No credentials required for the DOC API.
"""
