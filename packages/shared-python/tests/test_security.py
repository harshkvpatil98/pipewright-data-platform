from shared_python.auth.security import create_access_token, decode_access_token, hash_password, verify_password


def test_password_hashing_round_trip() -> None:
    encoded = hash_password("super-secret-password")
    assert verify_password("super-secret-password", encoded) is True
    assert verify_password("wrong-password", encoded) is False


def test_jwt_round_trip() -> None:
    token, expires_in = create_access_token(
        user_id="123",
        username="platform-admin",
        secret_key="test-secret",
        issuer="platform",
        audience="web",
        expires_minutes=10,
    )

    payload = decode_access_token(
        token,
        secret_key="test-secret",
        issuer="platform",
        audience="web",
    )

    assert payload.sub == "123"
    assert payload.username == "platform-admin"
    assert expires_in == 600
