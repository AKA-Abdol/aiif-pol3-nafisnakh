"""The CLI surface (Q2: modular service + CLI, JSON output, no UI)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from nafisnakh.cli import app

runner = CliRunner()


def test_help_lists_every_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("build", "signals", "brief", "eval", "label", "fixture", "calibrate"):
        assert command in result.stdout


def test_fixture_command_reports_full_detector_coverage():
    result = runner.invoke(app, ["fixture"])
    assert result.exit_code == 0, result.stdout
    assert "22 از 22" in result.stdout
    assert "فعال نشد" not in result.stdout


def test_label_command_shows_unreviewed_rows():
    result = runner.invoke(app, ["label", "--show", "2"])
    assert result.exit_code == 0
    assert "بازبینی‌نشده" in result.stdout
    assert "برچسب پیشنهادی" in result.stdout


def test_brief_writes_json_and_text(settings):
    result = runner.invoke(app, ["brief", "--top", "3"])
    assert result.exit_code == 0, result.stdout
    json_path = Path(settings.out_dir) / f"actions_{settings.as_of.isoformat()}.json"
    text_path = Path(settings.out_dir) / f"brief_{settings.as_of.isoformat()}.txt"
    assert json_path.exists() and text_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["as_of"] == settings.as_of.isoformat()
    assert payload["actions"]
    for action in payload["actions"]:
        assert action["evidence_ids"]
        assert action["bucket"] in {"grow", "protect", "fix", "reduce"}


def test_calibrate_exits_zero_when_every_detector_is_in_range():
    result = runner.invoke(app, ["calibrate"])
    assert result.exit_code == 0, result.stdout
    assert "fire_rate" in result.stdout
