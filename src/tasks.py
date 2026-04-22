from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib import error, request

from celery import signals
from celery.utils.log import get_task_logger

# API docs - https://openrelik.github.io/openrelik-worker-common/openrelik_worker_common/index.html
from openrelik_common.logging import Logger
from openrelik_worker_common.file_utils import create_output_file
from openrelik_worker_common.task_utils import create_task_result, get_input_files

from .app import celery

TASK_NAME = "openrelik-worker-notify.tasks.send_notification"
TASK_METADATA = {
    "display_name": "Notification worker",
    "description": "Send workflow notifications to Discord.",
    "task_config": [
        {
            "name": "message",
            "label": "Message",
            "description": "Custom message text. Leave empty for an auto-generated message.",
            "type": "textarea",
            "required": False,
        },
        {
            "name": "discord_webhook_url",
            "label": "Discord webhook URL",
            "description": "Optional override. Falls back to DISCORD_WEBHOOK_URL environment variable.",
            "type": "text",
            "required": False,
        },
    ],
}

log_root = Logger()
logger = log_root.get_logger(__name__, get_task_logger(__name__))


@signals.task_prerun.connect
def on_task_prerun(sender, task_id, task, args, kwargs, **_):
    log_root.bind(
        task_id=task_id,
        task_name=task.name,
        worker_name=TASK_METADATA.get("display_name"),
    )


def _cfg_str(task_config: dict[str, Any] | None, key: str, default: str = "") -> str:
    value = (task_config or {}).get(key, default)
    if isinstance(value, list):
        value = value[0] if value else default
    if value is None:
        return default
    return str(value).strip()


def _build_message(
    task_config: dict[str, Any] | None,
    workflow_id: str | None,
    input_files: list[dict[str, Any]],
) -> str:
    configured_message = _cfg_str(task_config, "message")
    if configured_message:
        return configured_message

    workflow = workflow_id or "unknown"
    file_count = len(input_files)
    return f"OpenRelik workflow {workflow} finished. Input files: {file_count}."


def _webhook_host(webhook_url: str) -> str:
    if not webhook_url:
        return "missing"
    parsed = urlparse(webhook_url)
    return parsed.netloc or "unknown"


def _send_discord(message: str, webhook_url: str) -> dict[str, Any]:
    if not webhook_url:
        raise ValueError("Missing Discord webhook URL. Set task_config.discord_webhook_url or DISCORD_WEBHOOK_URL.")

    body = json.dumps({"content": message}).encode("utf-8")
    req = request.Request(
        webhook_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "openrelik-worker-notify/0.1 (+https://github.com/julianghill/openrelik-worker-notify)",
        },
    )

    try:
        with request.urlopen(req, timeout=15):
            pass
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Discord webhook HTTP error {exc.code}: {details}") from exc

    return {
        "channel": "discord",
        "ok": True,
    }


@celery.task(bind=True, name=TASK_NAME, metadata=TASK_METADATA)
def command(
    self,
    pipe_result: str = None,
    input_files: list = None,
    output_path: str = None,
    workflow_id: str = None,
    task_config: dict = None,
) -> str:
    """Send a notification to Discord."""
    log_root.bind(workflow_id=workflow_id)
    logger.info(f"Starting {TASK_NAME} for workflow {workflow_id}")

    input_files = get_input_files(pipe_result, input_files or [])
    message = _build_message(task_config, workflow_id, input_files)
    webhook_url = _cfg_str(task_config, "discord_webhook_url", os.getenv("DISCORD_WEBHOOK_URL", ""))

    try:
        result = _send_discord(message, webhook_url)
    except Exception as exc:
        failure_message = (
            "Discord notification failed. "
            f"workflow_id={workflow_id or 'unknown'}, "
            f"webhook_host={_webhook_host(webhook_url)}, "
            f"error={exc}"
        )
        logger.exception(
            failure_message,
            extra={
                "workflow_id": workflow_id,
                "input_file_count": len(input_files),
                "primary_webhook_host": _webhook_host(webhook_url),
            },
        )
        raise RuntimeError(failure_message) from exc

    output_file = create_output_file(
        output_path,
        display_name=f"notify_discord_{workflow_id or 'unknown'}",
        extension="json",
        data_type="openrelik:notify:result",
    )

    payload = {
        "workflow_id": workflow_id,
        "message": message,
        "input_file_count": len(input_files),
        "result": result,
    }
    Path(output_file.path).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    logger.info(
        "Discord notification delivered",
        extra={
            "workflow_id": workflow_id,
            "input_file_count": len(input_files),
            "primary_webhook_host": _webhook_host(webhook_url),
        },
    )
    logger.info(f"Finished {TASK_NAME} for workflow {workflow_id}")

    return create_task_result(
        output_files=[output_file.to_dict()],
        workflow_id=workflow_id,
        command="notify:discord",
        meta={"channel": "discord", "delivered": True},
    )
