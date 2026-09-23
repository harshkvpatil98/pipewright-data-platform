"""The content digest that time-travel versions are fingerprinted with."""

from __future__ import annotations

import hashlib

import pytest

from shared_python.storage import content_digest
from shared_python.storage.digest import DIGEST_ALGORITHM


def test_digest_is_self_describing():
    # The algorithm travels with the value so an old digest is never bare hex.
    digest = content_digest(b"region,amount\nnorth,100\n")
    assert digest.startswith("sha256:")
    assert DIGEST_ALGORITHM == "sha256"


def test_digest_matches_the_named_algorithm():
    payload = b"the same bytes"
    expected = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    assert content_digest(payload) == expected


def test_identical_bytes_hash_identically():
    # This is the whole point: two materialisations of the same data dedupe.
    assert content_digest(b"abc") == content_digest(b"abc")


def test_a_single_changed_byte_changes_the_digest():
    assert content_digest(b"abc") != content_digest(b"abd")


def test_empty_bytes_have_a_stable_digest():
    assert content_digest(b"") == f"sha256:{hashlib.sha256(b'').hexdigest()}"


def test_bytearray_and_memoryview_are_accepted():
    assert content_digest(bytearray(b"xyz")) == content_digest(b"xyz")
    assert content_digest(memoryview(b"xyz")) == content_digest(b"xyz")


def test_a_string_is_refused_rather_than_hashed_wrongly():
    # Hashing str would hash its repr or raise deep in hashlib; refuse up front
    # so an accidental str never becomes a plausible-looking digest.
    with pytest.raises(TypeError):
        content_digest("not bytes")  # type: ignore[arg-type]
