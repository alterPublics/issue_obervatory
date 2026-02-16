"""Factory Boy factories for User-related models.

Usage in tests::

    from tests.factories.users import UserFactory, CreditAllocationFactory

    # Build a dict (no DB write)
    user_data = UserFactory.build()

    # Build with overrides
    admin_data = UserFactory.build(role="admin", email="admin@example.com")
"""

from __future__ import annotations

import datetime
import uuid

import factory

from tests.conftest import TEST_PASSWORD_HASH


class UserFactory(factory.Factory):
    """Factory for User model dicts.

    Returns plain dicts rather than ORM objects so that tests can control
    when and how objects are persisted (avoiding implicit DB writes).

    Fields match the :class:`issue_observatory.core.models.users.User` ORM
    model column names.
    """

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    display_name = factory.Faker("name")
    role = "researcher"
    is_active = True
    hashed_password = TEST_PASSWORD_HASH
    api_key = None
    metadata_ = factory.LazyFunction(dict)


class AdminUserFactory(UserFactory):
    """Factory for admin users."""

    role = "admin"
    email = factory.Sequence(lambda n: f"admin{n}@example.com")
    display_name = factory.Sequence(lambda n: f"Admin User {n}")


class InactiveUserFactory(UserFactory):
    """Factory for inactive (pending approval) users."""

    is_active = False
    email = factory.Sequence(lambda n: f"pending{n}@example.com")


class CreditAllocationFactory(factory.Factory):
    """Factory for CreditAllocation model dicts.

    Fields match :class:`issue_observatory.core.models.users.CreditAllocation`.
    """

    class Meta:
        model = dict

    id = factory.LazyFunction(uuid.uuid4)
    user_id = factory.LazyFunction(uuid.uuid4)
    credits_amount = 500
    allocated_by = None
    valid_from = factory.LazyFunction(datetime.date.today)
    valid_until = None
    memo = factory.Sequence(lambda n: f"Test allocation {n}")
