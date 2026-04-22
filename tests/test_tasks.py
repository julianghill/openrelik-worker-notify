"""Tests for notification worker tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import tasks


class _OutputFile:
    def __init__(self, path: Path):
        self.path = str(path)

    def to_dict(self):
        return {"path": self.path, "display_name": "notify", "data_type": "openrelik:notify:result"}


def test_command_sends_discord(monkeypatch, tmp_path):
    """Discord path should call sender and return task result."""

    monkeypatch.setattr(tasks, "get_input_files", lambda pipe_result, input_files: input_files)
    monkeypatch.setattr(
        tasks,
        "create_output_file",
        lambda output_path, **kwargs: _OutputFile(Path(output_path) / "notify.json"),
    )

    captured = {}

    def _fake_send_discord(message, webhook_url):
        captured["discord"] = {"message": message, "webhook_url": webhook_url}
        return {"channel": "discord", "ok": True}

    monkeypatch.setattr(tasks, "_send_discord", _fake_send_discord)
    monkeypatch.setattr(tasks, "create_task_result", lambda **kwargs: kwargs)

    result = tasks.command.run(
        pipe_result=None,
        input_files=[{"path": "/tmp/input.txt", "display_name": "input.txt"}],
        output_path=str(tmp_path),
        workflow_id="wf-2",
        task_config={
            "message": "Hello from test",
            "discord_webhook_url": "https://discord.example/webhook",
        },
    )

    assert result["command"] == "notify:discord"
    assert captured["discord"]["webhook_url"] == "https://discord.example/webhook"

    payload = json.loads((tmp_path / "notify.json").read_text(encoding="utf-8"))
    assert payload["workflow_id"] == "wf-2"
    assert payload["result"]["channel"] == "discord"


def test_command_builds_default_message(monkeypatch, tmp_path):
    """Default message should be generated when message is not configured."""

    monkeypatch.setattr(tasks, "get_input_files", lambda pipe_result, input_files: input_files)
    monkeypatch.setattr(
        tasks,
        "create_output_file",
        lambda output_path, **kwargs: _OutputFile(Path(output_path) / "notify.json"),
    )
    monkeypatch.setattr(tasks, "_send_discord", lambda message, webhook_url: {"channel": "discord", "ok": True, "message": message})
    monkeypatch.setattr(tasks, "create_task_result", lambda **kwargs: kwargs)

    tasks.command.run(
        pipe_result=None,
        input_files=[{"path": "/tmp/a"}, {"path": "/tmp/b"}],
        output_path=str(tmp_path),
        workflow_id="wf-default",
        task_config={"discord_webhook_url": "https://discord.example/webhook"},
    )

    payload = json.loads((tmp_path / "notify.json").read_text(encoding="utf-8"))
    assert payload["message"] == "OpenRelik workflow wf-default finished. Input files: 2."


def test_send_discord_requires_webhook_url():
    """Discord send should fail if webhook URL is missing."""

    with pytest.raises(ValueError, match="Discord webhook URL"):
        tasks._send_discord("hi", "")


def test_command_failure_raises_ui_visible_error(monkeypatch, tmp_path):
    """When delivery fails, the raised error should contain context for OpenRelik UI."""

    monkeypatch.setattr(tasks, "get_input_files", lambda pipe_result, input_files: input_files)
    monkeypatch.setattr(
        tasks,
        "create_output_file",
        lambda output_path, **kwargs: _OutputFile(Path(output_path) / "notify.json"),
    )

    def _fake_send_discord(message, webhook_url):
        raise RuntimeError("primary delivery failed")

    monkeypatch.setattr(tasks, "_send_discord", _fake_send_discord)

    with pytest.raises(RuntimeError, match="Discord notification failed"):
        tasks.command.run(
            pipe_result=None,
            input_files=[{"path": "/tmp/input.txt"}],
            output_path=str(tmp_path),
            workflow_id="wf-fail",
            task_config={
                "message": "will fail",
                "discord_webhook_url": "https://discord.example/primary",
            },
        )
