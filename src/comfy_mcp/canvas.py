"""HTTP client for the Canvas Bridge node pack (TEMPORARY test exception).

AGENTS.md's "Temporary test exception — canvas_* tools" allows the ``canvas_*``
tools, and only them, to call the bridge's ``/canvas_bridge/*`` route on the
targeted ComfyUI over HTTP from THIS module, with stdlib ``urllib`` only, until
comfy-cli ships ``comfy canvas`` commands. Then these become ``_run_comfy``
passthroughs and this module goes away.

Target resolution reuses :mod:`comfy_mcp.target`: an explicit ``COMFYUI_URL`` /
``COMFYUI_HOST`` wins, then Comfy Desktop's single live port lock, then ComfyUI's
default ``127.0.0.1:8188``. (``COMFY_LOCAL_URL`` is comfy-cli's variable and is not
read here.)

Leaf module: imports only ``errors`` and ``target``; nothing here imports ``server``.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from typing import Any

from . import target
from .errors import ComfyCliError

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = target.DEFAULT_COMFYUI_PORT
OPS = ("snapshot", "layout", "capture", "focus")
# Seconds the HTTP call may wait. The bridge's own relay timeout (sent as
# `timeout` in the body) is a few seconds shorter, so the bridge answers first
# with a clear "window did not answer" error.
_HTTP_SLACK_S = 10.0
_DEFAULT_RELAY_TIMEOUT_S = {"capture": 60.0}
# Who the bridge credits each op to: its cursor, name pill and activity log use it.
# One id per MCP server process, so two agents on one canvas show as two cursors.
ACTOR = os.environ.get("COMFY_MCP_ACTOR") or f"agent:claude:{os.getpid()}"


def resolve_base_url() -> tuple[str, str]:
    """``(base_url, source)`` for the ComfyUI whose canvas the tools address."""
    explicit = target._comfy_target()
    if explicit is not None:
        host, port, source = explicit
    else:
        desktop = target._discover_comfy_desktop_port()
        if desktop is not None:
            host, port, source = DEFAULT_HOST, desktop, "comfy-desktop-port-lock"
        else:
            host, port, source = DEFAULT_HOST, DEFAULT_PORT, "default"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"http://{host}:{port}", source


def _error_from_body(op: str, status: int, body: bytes, base: str) -> ComfyCliError:
    try:
        payload = json.loads(body.decode("utf-8"))
        err = payload.get("error") or {}
        code = err.get("code", f"http_{status}")
        message = err.get("message", "")
    except (ValueError, AttributeError):
        code, message = f"http_{status}", body[:300].decode("utf-8", "replace")
    if status == 404 and not message:
        return ComfyCliError(
            f"canvas_{op}: {base} has no /canvas_bridge route. Install the Canvas Bridge "
            "node pack into this ComfyUI's custom_nodes and restart it."
        )
    return ComfyCliError(f"canvas_{op} failed ({code}): {message}")


def call(op: str, args: dict[str, Any]) -> dict[str, Any]:
    """POST ``args`` to ``/canvas_bridge/<op>`` and return the bridge's ``data``."""
    if op not in OPS:
        raise ComfyCliError(f"unknown canvas op {op!r}")
    base, source = resolve_base_url()
    body = {k: v for k, v in args.items() if v is not None}
    body.setdefault("actor", ACTOR)
    relay_timeout = float(body.get("timeout") or _DEFAULT_RELAY_TIMEOUT_S.get(op, 20.0))
    body["timeout"] = relay_timeout
    req = urllib.request.Request(
        f"{base}/canvas_bridge/{op}",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=relay_timeout + _HTTP_SLACK_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise _error_from_body(op, exc.code, exc.read(), base) from exc
    except (urllib.error.URLError, socket.timeout, ConnectionError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ComfyCliError(
            f"canvas_{op}: could not reach ComfyUI at {base} (from {source}): {reason}. "
            "Start ComfyUI (from Comfy Desktop, so its port lock is found), or point "
            "COMFYUI_URL at the running one."
        ) from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        err = (payload or {}).get("error") or {}
        raise ComfyCliError(
            f"canvas_{op} failed ({err.get('code', 'error')}): {err.get('message', payload)}"
        )
    data = payload.get("data")
    if not isinstance(data, dict):
        data = {"result": data}
    data.setdefault("comfyui", base)
    return data
