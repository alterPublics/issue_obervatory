"""Central language resolution utilities for arena collectors.

Maps ISO 639-1 language codes to platform-specific parameters (country codes,
locale strings, API filter values).  Each arena calls one helper function
instead of importing hardcoded Danish defaults.

All functions default to Danish (``"da"``) when ``language_filter`` is ``None``
or empty — preserving backward compatibility with existing collection runs.

Key design rule: Danish (``"da"``) always includes country code ``"DK"`` for
platforms that support region/country filtering.  English (``"en"``) never
attaches a region code (it is a global language).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Language → country code mapping
# ---------------------------------------------------------------------------

LANGUAGE_COUNTRY_MAP: dict[str, str | None] = {
    "da": "DK",
    "en": None,
    "kl": "GL",
    "de": "DE",
    "sv": "SE",
    "no": "NO",
    "ru": "RU",
    "fi": "FI",
    "fr": "FR",
    "es": "ES",
    "nl": "NL",
    "pt": "PT",
    "it": "IT",
    "pl": "PL",
    "ar": None,
    "zh": None,
    "ja": "JP",
    "ko": "KR",
}
"""Maps ISO 639-1 codes to ISO 3166-1 alpha-2 country codes (or ``None``)."""

# ISO 639-1 → ISO 639-3 mapping for Event Registry
_ISO1_TO_ISO3: dict[str, str] = {
    "da": "dan",
    "en": "eng",
    "de": "deu",
    "sv": "swe",
    "no": "nor",
    "fi": "fin",
    "fr": "fra",
    "es": "spa",
    "nl": "nld",
    "pt": "por",
    "it": "ita",
    "pl": "pol",
    "ru": "rus",
    "ar": "ara",
    "zh": "zho",
    "ja": "jpn",
    "ko": "kor",
    "kl": "kal",
}

# ISO 639-1 → GDELT language name mapping
_ISO1_TO_GDELT_LANG: dict[str, str] = {
    "da": "danish",
    "en": "english",
    "de": "german",
    "fr": "french",
    "es": "spanish",
    "sv": "swedish",
    "no": "norwegian",
    "fi": "finnish",
    "nl": "dutch",
    "pt": "portuguese",
    "it": "italian",
    "pl": "polish",
    "ru": "russian",
    "ar": "arabic",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
}

# GDELT uses FIPS 10-4 country codes, not ISO 3166.
_COUNTRY_TO_FIPS: dict[str, str] = {
    "DK": "DA",
    "DE": "GM",
    "SE": "SW",
    "NO": "NO",
    "FI": "FI",
    "FR": "FR",
    "ES": "SP",
    "NL": "NL",
    "PT": "PO",
    "IT": "IT",
    "PL": "PL",
    "RU": "RS",
    "JP": "JA",
    "KR": "KS",
    "GL": "GL",
}

_DEFAULT_LANG: str = "da"


def _first_lang(language_filter: list[str] | None) -> str:
    """Return the first language code from the filter, or ``"da"``."""
    if language_filter:
        return language_filter[0]
    return _DEFAULT_LANG


# ---------------------------------------------------------------------------
# Public resolver functions
# ---------------------------------------------------------------------------


def resolve_country(language_filter: list[str] | None) -> str | None:
    """Return the country code for the primary language, or ``None``.

    >>> resolve_country(["da"])
    'DK'
    >>> resolve_country(["en"]) is None
    True
    >>> resolve_country(None)
    'DK'
    """
    lang = _first_lang(language_filter)
    return LANGUAGE_COUNTRY_MAP.get(lang)


def resolve_google_params(language_filter: list[str] | None) -> dict[str, str]:
    """Return ``{"gl": ..., "hl": ...}`` for Google Search / Autocomplete.

    ``hl`` is always the language code.  ``gl`` is the lowercase country code
    when available, otherwise omitted.

    >>> resolve_google_params(["da"])
    {'gl': 'dk', 'hl': 'da'}
    >>> resolve_google_params(["en"])
    {'hl': 'en'}
    """
    lang = _first_lang(language_filter)
    country = LANGUAGE_COUNTRY_MAP.get(lang)
    params: dict[str, str] = {"hl": lang}
    if country is not None:
        params["gl"] = country.lower()
    return params


def resolve_youtube_params(language_filter: list[str] | None) -> dict[str, str]:
    """Return YouTube Data API v3 locale parameters.

    For languages with a country mapping, returns both ``relevanceLanguage``
    and ``regionCode``.  For English and other global languages, returns only
    ``relevanceLanguage``.

    >>> resolve_youtube_params(["da"])
    {'relevanceLanguage': 'da', 'regionCode': 'DK'}
    >>> resolve_youtube_params(["en"])
    {'relevanceLanguage': 'en'}
    """
    lang = _first_lang(language_filter)
    country = LANGUAGE_COUNTRY_MAP.get(lang)
    params: dict[str, str] = {"relevanceLanguage": lang}
    if country is not None:
        params["regionCode"] = country
    return params


def resolve_bluesky_lang(language_filter: list[str] | None) -> str:
    """Return the Bluesky ``lang`` parameter value.

    >>> resolve_bluesky_lang(["en"])
    'en'
    >>> resolve_bluesky_lang(None)
    'da'
    """
    return _first_lang(language_filter)


def resolve_x_lang_operator(language_filter: list[str] | None) -> str:
    """Return the X/Twitter ``lang:`` search operator.

    >>> resolve_x_lang_operator(["da"])
    'lang:da'
    >>> resolve_x_lang_operator(["en"])
    'lang:en'
    """
    return f"lang:{_first_lang(language_filter)}"


def resolve_gdelt_filters(
    language_filter: list[str] | None,
) -> dict[str, str | None]:
    """Return GDELT DOC API filter parameters.

    For Danish: ``{"sourcelang": "danish", "sourcecountry": "DA"}``.
    For English: ``{"sourcelang": "english", "sourcecountry": None}``.

    >>> resolve_gdelt_filters(["da"])
    {'sourcelang': 'danish', 'sourcecountry': 'DA'}
    >>> resolve_gdelt_filters(["en"])
    {'sourcelang': 'english', 'sourcecountry': None}
    """
    lang = _first_lang(language_filter)
    gdelt_lang = _ISO1_TO_GDELT_LANG.get(lang, lang)
    country = LANGUAGE_COUNTRY_MAP.get(lang)
    fips = _COUNTRY_TO_FIPS.get(country) if country else None
    return {"sourcelang": gdelt_lang, "sourcecountry": fips}


def resolve_tiktok_region(language_filter: list[str] | None) -> str | None:
    """Return TikTok ``region_code`` value, or ``None`` for global languages.

    >>> resolve_tiktok_region(["da"])
    'DK'
    >>> resolve_tiktok_region(["en"]) is None
    True
    """
    lang = _first_lang(language_filter)
    return LANGUAGE_COUNTRY_MAP.get(lang)


def resolve_event_registry_lang(language_filter: list[str] | None) -> str:
    """Map the primary language to ISO 639-3 for Event Registry.

    >>> resolve_event_registry_lang(["da"])
    'dan'
    >>> resolve_event_registry_lang(["en"])
    'eng'
    """
    lang = _first_lang(language_filter)
    return _ISO1_TO_ISO3.get(lang, lang)


def resolve_language_label(language_filter: list[str] | None) -> str:
    """Return the primary language code for use in normalized record ``language`` fields.

    >>> resolve_language_label(["en"])
    'en'
    >>> resolve_language_label(None)
    'da'
    """
    return _first_lang(language_filter)
