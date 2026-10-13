"""The support address a deployment sets reaches the Help menu as a link (A6, W2)."""

from shared_python.status import support_contact


def test_an_email_becomes_a_mail_link() -> None:
    contact = support_contact(" help@example.com ", "1.0")
    assert contact.contact == "help@example.com"
    assert contact.href == "mailto:help@example.com"


def test_a_web_address_is_linked_as_it_is() -> None:
    assert support_contact("https://support.example.com/new", "1.0").href == "https://support.example.com/new"


def test_anything_else_is_ignored_rather_than_shown_broken() -> None:
    for value in (None, "", "call Ann", "javascript:alert(1)", "ftp://example.com"):
        contact = support_contact(value, "1.0")
        assert contact.contact is None and contact.href is None
        assert contact.version == "1.0"
