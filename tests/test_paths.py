"""Tests for clawteam.paths — identifier validation and path containment."""

from __future__ import annotations

import pytest

from clawteam.paths import ensure_within_root, validate_identifier


class TestValidateIdentifier:
    """validate_identifier accepts safe names and rejects dangerous ones."""

    @pytest.mark.parametrize(
        "value",
        [
            "alice",
            "my-team",
            "agent_01",
            "v2.0",
            "A",
            "0",
            "a.b-c_d",
            "UPPER.lower-123_456",
        ],
    )
    def test_valid_identifiers(self, value):
        assert validate_identifier(value) == value

    @pytest.mark.parametrize(
        "value",
        [
            "",
            " ",
            ".",
            "..",
            "../etc",
            "foo/bar",
            "foo\\bar",
            "name with space",
            "tab\there",
            "new\nline",
            "\x00null",
            "café",
            "日本語",
        ],
    )
    def test_invalid_identifiers(self, value):
        with pytest.raises(ValueError, match="Invalid"):
            validate_identifier(value)

    def test_allow_empty_true(self):
        assert validate_identifier("", allow_empty=True) == ""

    def test_allow_empty_false_rejects_empty(self):
        with pytest.raises(ValueError, match="must not be empty"):
            validate_identifier("", allow_empty=False)

    def test_custom_kind_in_error(self):
        with pytest.raises(ValueError, match="Invalid team name"):
            validate_identifier("bad/name", kind="team name")


class TestEnsureWithinRoot:
    """ensure_within_root prevents path traversal escapes."""

    def test_simple_join(self, tmp_path):
        result = ensure_within_root(tmp_path, "teams", "alpha")
        assert result == tmp_path / "teams" / "alpha"

    def test_single_part(self, tmp_path):
        result = ensure_within_root(tmp_path, "config.json")
        assert result == tmp_path / "config.json"

    def test_dotdot_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="escapes"):
            ensure_within_root(tmp_path, "..", "etc", "passwd")

    def test_absolute_segment_rejected(self, tmp_path):
        with pytest.raises(ValueError, match="escapes"):
            ensure_within_root(tmp_path, "/etc/passwd")

    def test_dotdot_in_middle_rejected(self, tmp_path):
        child = tmp_path / "sub"
        child.mkdir()
        with pytest.raises(ValueError, match="escapes"):
            ensure_within_root(child, "..", "..", "outside")

    def test_symlink_escape_rejected(self, tmp_path):
        legit = tmp_path / "data"
        legit.mkdir()
        outside = tmp_path / "secret"
        outside.mkdir()
        link = legit / "escape"
        link.symlink_to(outside)
        with pytest.raises(ValueError, match="escapes"):
            ensure_within_root(legit, "escape")

    def test_returns_unresolved_path_on_success(self, tmp_path):
        result = ensure_within_root(tmp_path, "a", "b")
        assert result == tmp_path / "a" / "b"
        assert not result.is_absolute() or str(result).startswith(str(tmp_path))
