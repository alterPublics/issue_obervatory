"""Tests for YF-13: Cross-design discovered sources view.

Verifies that the LinkMiner can mine links across all of a user's query
designs when query_design_id is None, and that the discovered-links route
correctly handles both single-design and user-scope modes.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from issue_observatory.analysis.link_miner import LinkMiner
from issue_observatory.core.models.collection import CollectionRun
from issue_observatory.core.models.content import UniversalContentRecord
from issue_observatory.core.models.query_design import QueryDesign


@pytest.mark.asyncio
async def test_link_miner_user_scope_mode(db_session, test_user):
    """Test that LinkMiner can mine across all user's query designs."""
    # Create two query designs for the user
    qd1 = QueryDesign(
        id=uuid.uuid4(),
        name="Design 1",
        created_by=test_user.id,
        search_terms=["climate", "energy"],
    )
    qd2 = QueryDesign(
        id=uuid.uuid4(),
        name="Design 2",
        created_by=test_user.id,
        search_terms=["politics", "elections"],
    )
    db_session.add_all([qd1, qd2])
    await db_session.flush()

    # Create collection runs for each design
    run1 = CollectionRun(
        id=uuid.uuid4(),
        query_design_id=qd1.id,
        initiated_by=test_user.id,
        status="complete",
    )
    run2 = CollectionRun(
        id=uuid.uuid4(),
        query_design_id=qd2.id,
        initiated_by=test_user.id,
        status="complete",
    )
    db_session.add_all([run1, run2])
    await db_session.flush()

    # Create content records with links in each run
    record1 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run1.id,
        query_design_id=qd1.id,
        platform="bluesky",
        arena="social_media",
        content_type="post",
        text_content="Check out this Telegram channel: https://t.me/climateaction",
        url="https://bsky.app/profile/user1/post/abc123",
        collected_at=datetime.now(tz=timezone.utc),
    )
    record2 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run2.id,
        query_design_id=qd2.id,
        platform="reddit",
        arena="social_media",
        content_type="post",
        text_content="Join the discussion at https://t.me/climateaction",
        url="https://reddit.com/r/politics/comments/xyz",
        collected_at=datetime.now(tz=timezone.utc),
    )
    record3 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 17, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run2.id,
        query_design_id=qd2.id,
        platform="reddit",
        arena="social_media",
        content_type="post",
        text_content="Follow us on YouTube: https://www.youtube.com/@climatetv",
        url="https://reddit.com/r/politics/comments/abc",
        collected_at=datetime.now(tz=timezone.utc),
    )
    db_session.add_all([record1, record2, record3])
    await db_session.commit()

    # Test user-scope mode (query_design_id=None)
    miner = LinkMiner()
    links = await miner.mine(
        db=db_session,
        query_design_id=None,
        user_id=test_user.id,
        platform_filter=None,
        min_source_count=1,
        limit=50,
    )

    # Should find links from both query designs
    assert len(links) == 2, f"Expected 2 discovered links, got {len(links)}"

    # Verify Telegram channel appears with source_count=2 (from both designs)
    telegram_link = next((lnk for lnk in links if lnk.platform == "telegram"), None)
    assert telegram_link is not None, "Expected to find Telegram link"
    assert telegram_link.target_identifier == "climateaction"
    assert telegram_link.source_count == 2, f"Expected 2 sources, got {telegram_link.source_count}"

    # Verify YouTube channel appears with source_count=1 (only from design 2)
    youtube_link = next((lnk for lnk in links if lnk.platform == "youtube"), None)
    assert youtube_link is not None, "Expected to find YouTube link"
    assert youtube_link.target_identifier == "climatetv"
    assert youtube_link.source_count == 1


@pytest.mark.asyncio
async def test_link_miner_single_design_mode(db_session, test_user):
    """Test that LinkMiner scopes to a single design when query_design_id is provided."""
    # Create two query designs
    qd1 = QueryDesign(
        id=uuid.uuid4(),
        name="Design 1",
        created_by=test_user.id,
        search_terms=["climate"],
    )
    qd2 = QueryDesign(
        id=uuid.uuid4(),
        name="Design 2",
        created_by=test_user.id,
        search_terms=["politics"],
    )
    db_session.add_all([qd1, qd2])
    await db_session.flush()

    run1 = CollectionRun(
        id=uuid.uuid4(),
        query_design_id=qd1.id,
        initiated_by=test_user.id,
        status="complete",
    )
    run2 = CollectionRun(
        id=uuid.uuid4(),
        query_design_id=qd2.id,
        initiated_by=test_user.id,
        status="complete",
    )
    db_session.add_all([run1, run2])
    await db_session.flush()

    # Add content to design 1
    record1 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run1.id,
        query_design_id=qd1.id,
        platform="bluesky",
        arena="social_media",
        content_type="post",
        text_content="https://t.me/channel1",
        url="https://bsky.app/profile/user/post/1",
        collected_at=datetime.now(tz=timezone.utc),
    )
    # Add content to design 2
    record2 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run2.id,
        query_design_id=qd2.id,
        platform="bluesky",
        arena="social_media",
        content_type="post",
        text_content="https://t.me/channel2",
        url="https://bsky.app/profile/user/post/2",
        collected_at=datetime.now(tz=timezone.utc),
    )
    db_session.add_all([record1, record2])
    await db_session.commit()

    # Test single-design mode: should only see channel1
    miner = LinkMiner()
    links_design1 = await miner.mine(
        db=db_session,
        query_design_id=qd1.id,
        user_id=None,  # Should be ignored when query_design_id is set
        platform_filter=None,
        min_source_count=1,
        limit=50,
    )

    assert len(links_design1) == 1, f"Expected 1 link from design 1, got {len(links_design1)}"
    assert links_design1[0].target_identifier == "channel1"

    # Test with design 2: should only see channel2
    links_design2 = await miner.mine(
        db=db_session,
        query_design_id=qd2.id,
        user_id=None,
        platform_filter=None,
        min_source_count=1,
        limit=50,
    )

    assert len(links_design2) == 1, f"Expected 1 link from design 2, got {len(links_design2)}"
    assert links_design2[0].target_identifier == "channel2"


@pytest.mark.asyncio
async def test_link_miner_user_isolation(db_session, test_user, test_user_2):
    """Test that user-scope mode only returns links from the specified user's content."""
    # User 1's query design
    qd1 = QueryDesign(
        id=uuid.uuid4(),
        name="User 1 Design",
        created_by=test_user.id,
        search_terms=["climate"],
    )
    # User 2's query design
    qd2 = QueryDesign(
        id=uuid.uuid4(),
        name="User 2 Design",
        created_by=test_user_2.id,
        search_terms=["energy"],
    )
    db_session.add_all([qd1, qd2])
    await db_session.flush()

    run1 = CollectionRun(
        id=uuid.uuid4(),
        query_design_id=qd1.id,
        initiated_by=test_user.id,
        status="complete",
    )
    run2 = CollectionRun(
        id=uuid.uuid4(),
        query_design_id=qd2.id,
        initiated_by=test_user_2.id,
        status="complete",
    )
    db_session.add_all([run1, run2])
    await db_session.flush()

    # User 1's content
    record1 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run1.id,
        query_design_id=qd1.id,
        platform="bluesky",
        arena="social_media",
        content_type="post",
        text_content="https://t.me/user1channel",
        url="https://bsky.app/profile/user1/post/1",
        collected_at=datetime.now(tz=timezone.utc),
    )
    # User 2's content
    record2 = UniversalContentRecord(
        id=uuid.uuid4(),
        published_at=datetime(2024, 1, 16, 12, 0, tzinfo=timezone.utc),
        collection_run_id=run2.id,
        query_design_id=qd2.id,
        platform="bluesky",
        arena="social_media",
        content_type="post",
        text_content="https://t.me/user2channel",
        url="https://bsky.app/profile/user2/post/2",
        collected_at=datetime.now(tz=timezone.utc),
    )
    db_session.add_all([record1, record2])
    await db_session.commit()

    # User 1's user-scope mining should only see their own links
    miner = LinkMiner()
    links_user1 = await miner.mine(
        db=db_session,
        query_design_id=None,
        user_id=test_user.id,
        platform_filter=None,
        min_source_count=1,
        limit=50,
    )

    assert len(links_user1) == 1, f"Expected 1 link for user 1, got {len(links_user1)}"
    assert links_user1[0].target_identifier == "user1channel"

    # User 2's user-scope mining should only see their own links
    links_user2 = await miner.mine(
        db=db_session,
        query_design_id=None,
        user_id=test_user_2.id,
        platform_filter=None,
        min_source_count=1,
        limit=50,
    )

    assert len(links_user2) == 1, f"Expected 1 link for user 2, got {len(links_user2)}"
    assert links_user2[0].target_identifier == "user2channel"


@pytest.mark.asyncio
async def test_link_miner_requires_scope_parameter(db_session):
    """Test that LinkMiner raises ValueError when neither query_design_id nor user_id is provided."""
    miner = LinkMiner()

    with pytest.raises(ValueError, match="Either query_design_id or user_id must be provided"):
        await miner.mine(
            db=db_session,
            query_design_id=None,
            user_id=None,
            platform_filter=None,
            min_source_count=1,
            limit=50,
        )
