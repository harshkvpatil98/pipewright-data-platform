from shared_python.status_redaction import redact_details


def test_redact_details_strips_sensitive_keys() -> None:
    out = redact_details(
        {
            "user_count": 3,
            "api_key": "secret",
            "nested": {"client_secret": "x", "ok": 1},
        }
    )
    assert out["user_count"] == 3
    assert out["api_key"] == "[redacted]"
    assert out["nested"]["client_secret"] == "[redacted]"
    assert out["nested"]["ok"] == 1
