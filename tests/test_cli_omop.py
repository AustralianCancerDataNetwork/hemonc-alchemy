from __future__ import annotations

from typer.testing import CliRunner

from hemonc_alchemy import cli


def test_regen_condition_targets_stops_before_writing_when_vocabulary_is_unavailable(
    monkeypatch, tmp_path
):
    patches_path = cli.condition_target_generation_module.PATCHES_PATH
    before = patches_path.read_bytes() if patches_path.exists() else None
    review_path = tmp_path / "review.csv"
    regenerate_called = False

    def unexpected_regenerate(*args, **kwargs):
        nonlocal regenerate_called
        regenerate_called = True
        raise AssertionError("regeneration ran without an available vocabulary")

    monkeypatch.setattr(
        cli.condition_target_generation_module, "regenerate", unexpected_regenerate
    )
    result = CliRunner().invoke(
        cli.app,
        [
            "regen-condition-targets",
            "--data-dir", str(tmp_path),
            "--db-url", "sqlite://",
            "--review-out", str(review_path),
        ],
    )

    assert result.exit_code == 1
    assert "schema tag 'vocab' is unmapped" in result.output
    assert not regenerate_called
    assert not review_path.exists()
    assert (patches_path.read_bytes() if patches_path.exists() else None) == before
