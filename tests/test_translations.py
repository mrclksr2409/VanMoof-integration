"""Keep all translation files in sync with strings.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "vanmoof"
LANGUAGES = ("de", "en", "nl")


def _keys(data: dict, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    for key, value in data.items():
        path = f"{prefix}.{key}" if prefix else key
        keys |= _keys(value, path) if isinstance(value, dict) else {path}
    return keys


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_matches_strings(language: str) -> None:
    strings = json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))
    translation = json.loads(
        (COMPONENT / "translations" / f"{language}.json").read_text(encoding="utf-8")
    )
    assert _keys(translation) == _keys(strings)


def test_english_is_strings() -> None:
    assert (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8") == (
        COMPONENT / "strings.json"
    ).read_text(encoding="utf-8")
