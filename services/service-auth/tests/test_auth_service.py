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
