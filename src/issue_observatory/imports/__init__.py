"""Data import module for Zeeschuimer and other manual capture sources.

This module handles data imports from the Zeeschuimer browser extension and other
manual capture workflows. It provides:

- NDJSON streaming parser with envelope restructuring (``ZeeschuimerProcessor``)
- Platform-specific normalizers for LinkedIn, Twitter, Instagram, TikTok, Threads
- FastAPI routes are in ``api/routes/imports.py`` (4CAT-compatible protocol)

The import pathway is separate from the arena collector framework because
Zeeschuimer data is push-based (browser → server) rather than pull-based
(server → API). Imports create collection runs with method="zeeschuimer_import"
for provenance tracking.
"""

from __future__ import annotations

__all__ = [
    "InstagramNormalizer",
    "LinkedInNormalizer",
    "ThreadsNormalizer",
    "TikTokNormalizer",
    "TwitterNormalizer",
    "ZeeschuimerProcessor",
]

from issue_observatory.imports.normalizers import (
    InstagramNormalizer,
    LinkedInNormalizer,
    ThreadsNormalizer,
    TikTokNormalizer,
    TwitterNormalizer,
)
from issue_observatory.imports.zeeschuimer import ZeeschuimerProcessor
