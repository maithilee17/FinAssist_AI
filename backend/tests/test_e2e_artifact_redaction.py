"""Regression checks for safe Phase 7.2 evaluation artifact serialization."""

from app.evaluation.end_to_end.runner import sanitize_for_artifact


def test_sensitive_fields_are_redacted_recursively() -> None:
    payload = {
        "body": {
            "access_token": "secret-token",
            "user": {"email": "safe-fixture@example.com"},
        },
        "password": "do-not-record",
    }

    sanitized = sanitize_for_artifact(payload)

    assert sanitized["body"]["access_token"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["body"]["user"]["email"] == "safe-fixture@example.com"


def test_cookie_and_jwt_values_are_redacted_inside_strings() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"
    header = (
        f"finassist_access_token={jwt}; HttpOnly; Secure, "
        "finassist_csrf_token=csrf-secret; Secure"
    )

    sanitized = sanitize_for_artifact([header, f"Bearer {jwt}"])

    assert jwt not in sanitized[0]
    assert "csrf-secret" not in sanitized[0]
    assert jwt not in sanitized[1]
    assert sanitized[0].count("[REDACTED]") == 2
