"""canvas_* tools: thin HTTP calls to the Canvas Bridge route (AGENTS.md test exception).

No real HTTP: ``urllib.request.urlopen`` is replaced with a recorder, the same way
the comfy-cli spawn is faked elsewhere, and every tool is driven through its
public function.
"""

from __future__ import annotations

import asyncio
import io
import json
import urllib.error

import pytest

from comfy_mcp import canvas, server
from comfy_mcp.errors import ComfyCliError


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def bridge(monkeypatch):
    """Record requests and answer with a canned bridge reply."""
    calls: list[dict] = []
    state = {"reply": {"ok": True, "data": {"text": "tab: x"}}, "raise": None}

    def fake_urlopen(req, timeout=None):
        calls.append(
            {
                "url": req.full_url,
                "body": json.loads(req.data),
                "timeout": timeout,
                "method": req.get_method(),
            }
        )
        if state["raise"] is not None:
            raise state["raise"]
        return _Resp(json.dumps(state["reply"]).encode())

    monkeypatch.setattr(canvas.urllib.request, "urlopen", fake_urlopen)
    for var in ("COMFYUI_URL", "COMFYUI_HOST", "COMFYUI_PORT", "COMFY_LOCAL_URL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(canvas.target, "_discover_comfy_desktop_port", lambda: None)
    return calls, state


def test_snapshot_posts_scope_and_detail_to_the_bridge(bridge):
    calls, _ = bridge
    out = asyncio.run(server.canvas_snapshot(scope=["n1", "g2"], detail="full"))
    assert out["text"] == "tab: x"
    assert out["comfyui"] == "http://127.0.0.1:8188"
    assert calls[0]["url"] == "http://127.0.0.1:8188/canvas_bridge/snapshot"
    assert calls[0]["method"] == "POST"
    assert calls[0]["body"]["scope"] == ["n1", "g2"]
    assert calls[0]["body"]["detail"] == "full"
    # The installed comfy-mcp names itself, so a stale cached install is obvious.
    assert out["comfy_mcp"].startswith("comfy-mcp ")
    assert calls[0]["body"]["client"] == out["comfy_mcp"]


def test_layout_drops_unset_options_and_forwards_the_rest(bridge):
    calls, _ = bridge
    asyncio.run(server.canvas_layout(groups="auto", spacing={"colGap": 100}))
    body = calls[0]["body"]
    assert body["groups"] == "auto"
    assert body["spacing"] == {"colGap": 100}
    assert body["animate"] is True
    assert "timeout" in body
    assert body["force"] is False
    assert body["actor"].startswith("agent:claude")


def test_layout_forwards_force(bridge):
    calls, _ = bridge
    asyncio.run(server.canvas_layout(force=True))
    assert calls[0]["body"]["force"] is True


def test_layout_omits_groups_when_not_given(bridge):
    calls, _ = bridge
    asyncio.run(server.canvas_layout())
    assert "groups" not in calls[0]["body"]


def test_capture_gets_a_longer_relay_timeout_and_its_http_wait_exceeds_it(bridge):
    calls, state = bridge
    state["reply"] = {
        "ok": True,
        "data": {"path": "D:/x/a.png", "sidecar": "D:/x/a.json"},
    }
    out = asyncio.run(server.canvas_capture(name="a", out_dir="D:/x", scale=2))
    assert out["path"].endswith("a.png")
    assert calls[0]["body"]["timeout"] == 60.0
    assert calls[0]["timeout"] > calls[0]["body"]["timeout"]
    assert calls[0]["body"]["scale"] == 2


def test_focus_routes_to_the_focus_op(bridge):
    calls, _ = bridge
    asyncio.run(server.canvas_focus(scope="group:g3", zoom=0.6))
    assert calls[0]["url"].endswith("/canvas_bridge/focus")
    assert calls[0]["body"]["scope"] == "group:g3"


@pytest.mark.parametrize(
    ("env", "expected"),
    [
        ({"COMFYUI_URL": "http://10.0.0.5:8190"}, "http://10.0.0.5:8190"),
        ({"COMFYUI_HOST": "box", "COMFYUI_PORT": "9000"}, "http://box:9000"),
    ],
)
def test_target_follows_the_same_env_resolution(bridge, monkeypatch, env, expected):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert canvas.resolve_base_url()[0] == expected


def test_desktop_port_lock_is_used_when_nothing_is_configured(bridge, monkeypatch):
    monkeypatch.setattr(canvas.target, "_discover_comfy_desktop_port", lambda: 8000)
    assert canvas.resolve_base_url() == (
        "http://127.0.0.1:8000",
        "comfy-desktop-port-lock",
    )


def test_no_window_error_is_surfaced_with_the_bridge_message(bridge):
    _, state = bridge
    body = json.dumps(
        {
            "ok": False,
            "error": {
                "code": "no_window",
                "message": "No ComfyUI window is connected.",
            },
        }
    ).encode()
    state["raise"] = urllib.error.HTTPError("u", 503, "x", {}, io.BytesIO(body))
    with pytest.raises(ComfyCliError, match="no_window.*No ComfyUI window"):
        asyncio.run(server.canvas_snapshot())


def test_missing_route_says_to_install_the_node_pack(bridge):
    _, state = bridge
    state["raise"] = urllib.error.HTTPError("u", 404, "x", {}, io.BytesIO(b""))
    with pytest.raises(ComfyCliError, match="Install the Canvas Bridge"):
        asyncio.run(server.canvas_layout())


def test_unreachable_server_names_the_target_and_the_fix(bridge):
    _, state = bridge
    state["raise"] = urllib.error.URLError("refused")
    with pytest.raises(
        ComfyCliError,
        match=r"could not reach ComfyUI at http://127.0.0.1:8188.*COMFYUI_URL",
    ):
        asyncio.run(server.canvas_focus())


def test_http_lives_only_in_the_canvas_module():
    """AGENTS.md scopes the exception to canvas.py; no other module may import urllib.request."""
    import pathlib

    src = pathlib.Path(canvas.__file__).parent
    offenders = [
        p.name
        for p in src.glob("*.py")
        if p.name != "canvas.py" and "urllib.request" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_act_sends_the_ops_and_a_timeout_that_scales(bridge):
    calls, _ = bridge
    ops = [{"op": "move", "ref": "n3", "right_of": "n2", "align": "pins"}] * 3
    asyncio.run(server.canvas_act(ops=ops, capture_each=True, name="loop"))
    c = calls[0]
    assert c["url"].endswith("/canvas_bridge/act")
    assert c["body"]["ops"] == ops
    assert c["body"]["capture_each"] is True
    assert c["body"]["name"] == "loop"
    assert c["body"]["timeout"] == 30.0 + 3 * 8.0
    assert "out_dir" not in c["body"]


def test_move_is_a_single_move_op(bridge):
    calls, _ = bridge
    asyncio.run(server.canvas_move("n4", right_of="n1", gap=60, capture=True))
    body = calls[0]["body"]
    assert calls[0]["url"].endswith("/canvas_bridge/act")
    assert body["ops"] == [{"op": "move", "ref": "n4", "right_of": "n1", "gap": 60}]
    assert body["capture_each"] is True
