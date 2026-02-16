"""Factory Boy factories for QueryDesign and SearchTerm models.

Usage::

    from tests.factories.query_designs import QueryDesignFactory, SearchTermFactory

    design = QueryDesignFactory.build(name="Danish Climate Coverage")
    term = SearchTermFactory.build(query_design_id=design["id"], term="klimaforandringer")
"""

from __future__ import annotations

import uuid

import factory


class QueryDesignFactory(factory.Factory):
    """Factory for QueryDesign model dicts.

    Produces Danish-context query designs by default, reflecting the project's
    primary research context.  Override fields as needed for edge-case tests.

    Fields match :class:`issue_observatory.core.models.query_design.QueryDesign`.
    """

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    owner_id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"Test Query Design {n}")
    description = factory.Faker("sentence")
    visibility = "private"
    is_active = True
    default_tier = "free"
    # Danish defaults
    language = "da"
    locale_country = "dk"


class DanishQueryDesignFactory(QueryDesignFactory):
    """QueryDesign pre-loaded with Danish search terms (not persisted).

    Use :class:`SearchTermFactory` to create associated terms.
    """

    name = factory.Sequence(lambda n: f"Dansk Søgedesign {n}")
    description = "Søgedesign til dansk mediemonitoring med æ, ø og å"


class SearchTermFactory(factory.Factory):
    """Factory for SearchTerm model dicts.

    Fields match :class:`issue_observatory.core.models.query_design.SearchTerm`.
    """

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    query_design_id = factory.LazyFunction(uuid.uuid4)
    term = factory.Sequence(lambda n: f"søgeord{n}")
    term_type = "keyword"
    is_active = True


class DanishSearchTermFactory(SearchTermFactory):
    """SearchTerm factory with Danish keyword defaults.

    Covers the full range of Danish special characters: æ, ø, å.
    """

    term = factory.Iterator(
        [
            "klimaforandringer",       # Climate change (no special chars)
            "grøn omstilling",         # Green transition (ø)
            "sundhedspleje",           # Healthcare
            "velfærdsstat",            # Welfare state (æ)
            "dansk økonomi",           # Danish economy (ø)
            "Aalborg",                 # Å in city name
            "Søren Kierkegaard",       # Person name with ø
            "færøerne",                # Faroe Islands (æ, ø)
        ]
    )
    term_type = "keyword"
