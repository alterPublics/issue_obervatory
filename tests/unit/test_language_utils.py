"""Tests for the central language resolution utility module."""

from __future__ import annotations

from issue_observatory.core.language_utils import (
    LANGUAGE_COUNTRY_MAP,
    resolve_bluesky_lang,
    resolve_country,
    resolve_event_registry_lang,
    resolve_gdelt_filters,
    resolve_google_params,
    resolve_language_label,
    resolve_tiktok_region,
    resolve_x_lang_operator,
    resolve_youtube_params,
)

# ---------------------------------------------------------------------------
# resolve_country
# ---------------------------------------------------------------------------


class TestResolveCountry:
    def test_danish_returns_dk(self) -> None:
        assert resolve_country(["da"]) == "DK"

    def test_english_returns_none(self) -> None:
        assert resolve_country(["en"]) is None

    def test_none_defaults_to_danish(self) -> None:
        assert resolve_country(None) == "DK"

    def test_empty_list_defaults_to_danish(self) -> None:
        assert resolve_country([]) == "DK"

    def test_multi_language_uses_first(self) -> None:
        assert resolve_country(["en", "da"]) is None
        assert resolve_country(["da", "en"]) == "DK"

    def test_unknown_code_returns_none(self) -> None:
        assert resolve_country(["xx"]) is None


# ---------------------------------------------------------------------------
# resolve_google_params
# ---------------------------------------------------------------------------


class TestResolveGoogleParams:
    def test_danish(self) -> None:
        params = resolve_google_params(["da"])
        assert params == {"gl": "dk", "hl": "da"}

    def test_english_no_gl(self) -> None:
        params = resolve_google_params(["en"])
        assert params == {"hl": "en"}
        assert "gl" not in params

    def test_none_defaults_to_danish(self) -> None:
        params = resolve_google_params(None)
        assert params == {"gl": "dk", "hl": "da"}

    def test_german(self) -> None:
        params = resolve_google_params(["de"])
        assert params == {"gl": "de", "hl": "de"}

    def test_swedish(self) -> None:
        params = resolve_google_params(["sv"])
        assert params == {"gl": "se", "hl": "sv"}


# ---------------------------------------------------------------------------
# resolve_youtube_params
# ---------------------------------------------------------------------------


class TestResolveYoutubeParams:
    def test_danish(self) -> None:
        params = resolve_youtube_params(["da"])
        assert params == {"relevanceLanguage": "da", "regionCode": "DK"}

    def test_english_no_region_code(self) -> None:
        params = resolve_youtube_params(["en"])
        assert params == {"relevanceLanguage": "en"}
        assert "regionCode" not in params

    def test_none_defaults_to_danish(self) -> None:
        params = resolve_youtube_params(None)
        assert params == {"relevanceLanguage": "da", "regionCode": "DK"}


# ---------------------------------------------------------------------------
# resolve_bluesky_lang
# ---------------------------------------------------------------------------


class TestResolveBlueSkyLang:
    def test_danish(self) -> None:
        assert resolve_bluesky_lang(["da"]) == "da"

    def test_english(self) -> None:
        assert resolve_bluesky_lang(["en"]) == "en"

    def test_none_defaults_to_danish(self) -> None:
        assert resolve_bluesky_lang(None) == "da"


# ---------------------------------------------------------------------------
# resolve_x_lang_operator
# ---------------------------------------------------------------------------


class TestResolveXLangOperator:
    def test_danish(self) -> None:
        assert resolve_x_lang_operator(["da"]) == "lang:da"

    def test_english(self) -> None:
        assert resolve_x_lang_operator(["en"]) == "lang:en"

    def test_none_defaults_to_danish(self) -> None:
        assert resolve_x_lang_operator(None) == "lang:da"


# ---------------------------------------------------------------------------
# resolve_gdelt_filters
# ---------------------------------------------------------------------------


class TestResolveGdeltFilters:
    def test_danish(self) -> None:
        result = resolve_gdelt_filters(["da"])
        assert result == {"sourcelang": "danish", "sourcecountry": "DA"}

    def test_english_no_country(self) -> None:
        result = resolve_gdelt_filters(["en"])
        assert result == {"sourcelang": "english", "sourcecountry": None}

    def test_none_defaults_to_danish(self) -> None:
        result = resolve_gdelt_filters(None)
        assert result == {"sourcelang": "danish", "sourcecountry": "DA"}

    def test_german(self) -> None:
        result = resolve_gdelt_filters(["de"])
        assert result == {"sourcelang": "german", "sourcecountry": "GM"}


# ---------------------------------------------------------------------------
# resolve_tiktok_region
# ---------------------------------------------------------------------------


class TestResolveTiktokRegion:
    def test_danish(self) -> None:
        assert resolve_tiktok_region(["da"]) == "DK"

    def test_english_returns_none(self) -> None:
        assert resolve_tiktok_region(["en"]) is None

    def test_none_defaults_to_danish(self) -> None:
        assert resolve_tiktok_region(None) == "DK"


# ---------------------------------------------------------------------------
# resolve_event_registry_lang
# ---------------------------------------------------------------------------


class TestResolveEventRegistryLang:
    def test_danish(self) -> None:
        assert resolve_event_registry_lang(["da"]) == "dan"

    def test_english(self) -> None:
        assert resolve_event_registry_lang(["en"]) == "eng"

    def test_none_defaults_to_danish(self) -> None:
        assert resolve_event_registry_lang(None) == "dan"


# ---------------------------------------------------------------------------
# resolve_language_label
# ---------------------------------------------------------------------------


class TestResolveLanguageLabel:
    def test_danish(self) -> None:
        assert resolve_language_label(["da"]) == "da"

    def test_english(self) -> None:
        assert resolve_language_label(["en"]) == "en"

    def test_none_defaults_to_danish(self) -> None:
        assert resolve_language_label(None) == "da"

    def test_empty_list_defaults_to_danish(self) -> None:
        assert resolve_language_label([]) == "da"


# ---------------------------------------------------------------------------
# LANGUAGE_COUNTRY_MAP sanity checks
# ---------------------------------------------------------------------------


class TestLanguageCountryMap:
    def test_danish_always_dk(self) -> None:
        assert LANGUAGE_COUNTRY_MAP["da"] == "DK"

    def test_english_always_none(self) -> None:
        assert LANGUAGE_COUNTRY_MAP["en"] is None

    def test_arabic_always_none(self) -> None:
        assert LANGUAGE_COUNTRY_MAP["ar"] is None

    def test_chinese_always_none(self) -> None:
        assert LANGUAGE_COUNTRY_MAP["zh"] is None
