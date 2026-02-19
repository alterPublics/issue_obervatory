"""Test wayback content fetcher imports for circular import issues.

This test verifies that the _content_fetcher module can be imported without
circular import errors, as flagged in QA report W-01.

The module imports from issue_observatory.scraper, which could potentially
create a circular dependency if scraper imports anything from arenas.
"""


def test_wayback_content_fetcher_importable() -> None:
    """Verify _content_fetcher can be imported without circular import error."""
    from issue_observatory.arenas.web.wayback._content_fetcher import (
        fetch_content_for_records,
        fetch_single_record_content,
    )

    assert callable(fetch_content_for_records)
    assert callable(fetch_single_record_content)
