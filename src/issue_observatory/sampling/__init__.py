"""Actor sampling and network expansion utilities.

Public symbols:

- ``NetworkExpander``: discover actors via platform follower graphs and
  co-mention analysis.
- ``SimilarityFinder``: discover similar actors via platform recommendations
  and content-based TF-IDF similarity.
- ``SnowballSampler``: coordinate iterative multi-wave snowball sampling.
- ``SnowballResult``: result container returned by ``SnowballSampler.run()``.
- Factory functions: ``get_network_expander()``, ``get_similarity_finder()``,
  ``get_snowball_sampler()`` — suitable for FastAPI dependency injection.
"""

from __future__ import annotations

from issue_observatory.sampling.network_expander import (
    NetworkExpander,
    get_network_expander,
)
from issue_observatory.sampling.similarity_finder import (
    SimilarityFinder,
    get_similarity_finder,
)
from issue_observatory.sampling.snowball import (
    SnowballResult,
    SnowballSampler,
    get_snowball_sampler,
)

__all__ = [
    "NetworkExpander",
    "SimilarityFinder",
    "SnowballResult",
    "SnowballSampler",
    "get_network_expander",
    "get_similarity_finder",
    "get_snowball_sampler",
]
