from pathlib import Path

import pytest

from material_matcher.profile import load_profile


def test_load_profile_and_hash(tmp_path: Path) -> None:
    profile = tmp_path / "customer.yaml"
    profile.write_text(
        """
profile:
  name: demo
  version: 1
source:
  adapter: excel
  path: source.xlsx
target:
  adapter: excel
  path: target.xlsx
logical_fields:
  source_id:
    source:
      aliases: [MATNR]
match_rules:
  - id: id
    source_fields: [source_id]
    target_fields: [source_id]
    method: exact
    weight: 1.0
""".strip(),
        encoding="utf-8",
    )

    loaded = load_profile(profile)
    assert loaded.document.profile.name == "demo"
    assert len(loaded.sha256) == 64


def test_profile_requires_source_or_datasets(tmp_path: Path) -> None:
    profile = tmp_path / "invalid.yaml"
    profile.write_text(
        """
profile:
  name: invalid
target:
  adapter: excel
logical_fields:
  source_id: {}
match_rules:
  - id: id
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="source or datasets"):
        load_profile(profile)
