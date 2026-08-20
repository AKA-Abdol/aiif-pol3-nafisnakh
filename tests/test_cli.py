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
    assert "27 از 27" in result.stdout
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


def test_customer_command_writes_a_360_page(tmp_path):
    out = tmp_path / "c.html"
    result = runner.invoke(app, ["customer", "C_126481", "--output", str(out)])
    assert result.exit_code == 0, result.stdout
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "پرونده ۳۶۰ مشتری — C_126481" in text
    assert '<details class="evd"' in text


def test_customer_command_rejects_an_unknown_id():
    result = runner.invoke(app, ["customer", "C_NOPE"])
    assert result.exit_code != 0


def test_tools_command_prints_claims_and_ids_only():
    result = runner.invoke(app, ["tools", "C_126481", "--tool", "get_payment_state"])
    assert result.exit_code == 0, result.stdout
    assert "ابزار: get_payment_state" in result.stdout
    assert "EV-C_126481-exposure-001" in result.stdout


def test_tools_command_rejects_an_unknown_tool():
    result = runner.invoke(app, ["tools", "C_126481", "--tool", "get_nothing"])
    assert result.exit_code != 0
