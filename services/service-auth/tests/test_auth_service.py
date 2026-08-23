from types import SimpleNamespace
from unittest.mock import patch

import pytest

from service_auth.service import authenticate_user
from shared_python.errors import UnauthorizedError


@patch("service_auth.service.get_user_by_username")
@patch("service_auth.service.verify_password", return_value=True)
def test_authenticate_user_returns_matching_user(_verify_password, get_user_by_username) -> None:
    get_user_by_username.return_value = SimpleNamespace(
        username="platform-admin",
        password_hash="ignored-in-test",
        is_active=True,
    )
    user = authenticate_user(object(), "platform-admin", "super-secret-password")
    assert user.username == "platform-admin"


@patch("service_auth.service.get_user_by_username", return_value=None)
def test_authenticate_user_rejects_unknown_users(_get_user_by_username) -> None:
    with pytest.raises(UnauthorizedError):
        authenticate_user(object(), "missing-user", "super-secret-password")


def test_listing_users_returns_them_oldest_first() -> None:
    """The invite picker needs names; it does not need anything sensitive."""
    from service_auth.service import list_users

    class FakeScalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeDb:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self, _statement):
            return FakeScalars(self._rows)

    rows = ["first", "second"]
    assert list_users(FakeDb(rows)) == rows
