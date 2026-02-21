"""Platform-specific normalizers for Zeeschuimer data.

Each normalizer implements a ``normalize()`` method that takes:
- raw_data: The nested ``data`` field from the Zeeschuimer item
- envelope: The Zeeschuimer envelope fields (timestamp_collected, source_platform, etc.)

And returns a flat dict that can be passed to the universal ``Normalizer.normalize()``
method.

Normalizers:
- LinkedInNormalizer: LinkedIn Voyager V2 API format (most complex)
- TwitterNormalizer: Adapter to existing x_twitter collector normalization logic
- InstagramNormalizer: Adapter to existing instagram collector normalization logic
- TikTokNormalizer: Adapter to existing tiktok collector normalization logic
- ThreadsNormalizer: Adapter to existing threads collector normalization logic
"""

from __future__ import annotations

__all__ = [
    "LinkedInNormalizer",
    "TwitterNormalizer",
    "InstagramNormalizer",
    "TikTokNormalizer",
    "ThreadsNormalizer",
]

from issue_observatory.imports.normalizers.linkedin import LinkedInNormalizer
from issue_observatory.imports.normalizers.twitter import TwitterNormalizer
from issue_observatory.imports.normalizers.instagram import InstagramNormalizer
from issue_observatory.imports.normalizers.tiktok import TikTokNormalizer
from issue_observatory.imports.normalizers.threads import ThreadsNormalizer
