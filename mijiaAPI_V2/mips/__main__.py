"""MIPS 推送服务入口

运行::

    python -m mijiaAPI_V2.mips                # 默认 0.0.0.0:8130，允许局域网访问
    python -m mijiaAPI_V2.mips --port 8131 --webhook http://127.0.0.1:9000/hook

浏览器打开服务地址（本机或局域网 IP）即可登录小米账号、查看实时推送。
"""

from __future__ import annotations

import argparse
import json
import logging
import queue
import socket
import threading
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from mijiaAPI_V2.core.logging import get_logger
from mijiaAPI_V2.mips.auth import MipsAuthError
from mijiaAPI_V2.mips.service import MipsService

logger = get_logger(__name__)

INDEX_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>MIPS 推送服务</title>
<style>
  body { font-family: -apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif;
         max-width: 860px; margin: 24px auto; padding: 0 16px; color: #222; }
  h1 { font-size: 20px; }
  section { border: 1px solid #ddd; border-radius: 8px; padding: 16px; margin: 12px 0; }
  input[type=text] { width: 100%; padding: 8px; box-sizing: border-box; }
  button { padding: 8px 16px; margin-right: 8px; cursor: pointer; }
  #status { color: #555; }
  #log { background: #fafafa; border: 1px solid #eee; border-radius: 6px;
         padding: 8px; height: 320px; overflow-y: auto; font: 12px/1.6 monospace;
         white-space: pre-wrap; }
  .ok { color: #2e7d32; } .err { color: #c62828; }
  a { color: #1565c0; }
</style>
</head>
<body>
<h1>MIoT Pub/Sub 推送服务</h1>
<section>
  <h3>登录状态</h3>
  <div id="status">加载中…</div>
  <p><a id="authlink" href="#" target="_blank">点击这里登录小米账号</a></p>
  <p>登录后浏览器会跳转到 <code>homeassistant.local:8123</code>（打不开是正常的），
     把地址栏里完整的网址粘贴到这里：</p>
  <input type="text" id="redirect" placeholder="http://homeassistant.local:8123/?code=...">
  <button onclick="doLogin()">完成登录</button>
  <button onclick="doLogout()">退出登录</button>
  <div id="loginmsg"></div>
</section>
<section>
  <h3>实时推送</h3>
  <div id="log"></div>
</section>
<script>
const log = document.getElementById('log');
function append(line) {
  const div = document.createElement('div');
  div.textContent = line;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  while (log.childNodes.length > 400) log.removeChild(log.firstChild);
}
async function refresh() {
  const r = await fetch('/status');
  const s = await r.json();
  const el = document.getElementById('status');
  el.innerHTML = s.logged_in
    ? `<span class="ok">已登录</span> · MQTT ${s.connected ? '已连接' : '未连接'} · 已收 ${s.received} 条`
    : '<span class="err">未登录</span>';
  document.getElementById('authlink').href = s.auth_url;
}
async function doLogin() {
  const v = document.getElementById('redirect').value.trim();
  const r = await fetch('/login', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({redirect: v})});
  const s = await r.json();
  document.getElementById('loginmsg').textContent = s.ok ? '登录成功' : ('失败: ' + s.detail);
  refresh();
}
async function doLogout() {
  await fetch('/logout', {method: 'POST'});
  document.getElementById('loginmsg').textContent = '已退出';
  refresh();
}
const es = new EventSource('/events');
es.onmessage = e => append(e.data);
refresh();
setInterval(refresh, 5000);
</script>
</body>
</html>
"""


class LoginRequest(BaseModel):
    redirect: Optional[str] = None
    code: Optional[str] = None


class AppState:
    def __init__(self, service: MipsService) -> None:
        self.service = service
        self.received = 0
        self.subscribers: List[queue.Queue] = []
        self.lock = threading.Lock()

    def broadcast(self, payload: Dict[str, Any]) -> None:
        self.received += 1
        line = json.dumps(payload, ensure_ascii=False)
        print(f"[MIPS] {line}", flush=True)
        with self.lock:
            for q in list(self.subscribers):
                try:
                    q.put_nowait(line)
                except queue.Full:
                    pass


def _event_stream(state: AppState):
    q: queue.Queue = queue.Queue(maxsize=500)
    with state.lock:
        state.subscribers.append(q)
    try:
        yield ": connected\n\n"
        while True:
            try:
                line = q.get(timeout=30)
                yield f"data: {line}\n\n"
            except queue.Empty:
                yield ": keepalive\n\n"
    finally:
        with state.lock:
            if q in state.subscribers:
                state.subscribers.remove(q)


def _do_login(state: AppState, value: str) -> Dict[str, Any]:
    try:
        state.service.complete_login(value)
        state.service.start()
    except MipsAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"ok": True}


def create_app(state: AppState) -> FastAPI:
    app = FastAPI(title="MIPS 推送服务", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return INDEX_HTML

    @app.get("/healthz")
    def healthz() -> Dict[str, Any]:
        return {"status": "ok", "connected": state.service.is_connected}

    @app.get("/status")
    def status() -> Dict[str, Any]:
        service = state.service
        return {
            "logged_in": service.is_logged_in,
            "connected": service.is_connected,
            "received": state.received,
            "auth_url": service.auth_url(),
        }

    @app.post("/login")
    def login(req: LoginRequest) -> Dict[str, Any]:
        value = req.redirect or req.code
        if not value:
            raise HTTPException(status_code=400, detail="缺少 redirect 或 code")
        return _do_login(state, value)

    @app.post("/logout")
    def logout() -> Dict[str, Any]:
        state.service.logout()
        return {"ok": True}

    @app.get("/events")
    def events() -> StreamingResponse:
        return StreamingResponse(_event_stream(state), media_type="text/event-stream")

    return app


def _lan_ip() -> str:
    """探测本机在局域网中的地址（仅用于启动提示，不建立真实连接）"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
        finally:
            sock.close()
    except OSError:
        return "127.0.0.1"


def main(argv: Optional[List[str]] = None) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser(description="MIoT Pub/Sub 推送服务")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="监听地址，默认 0.0.0.0 允许局域网访问；改回 127.0.0.1 仅限本机",
    )
    parser.add_argument("--port", type=int, default=8130, help="监听端口")
    parser.add_argument("--cloud", default="cn", help="云区域：cn/de/i2/ru/sg/us")
    parser.add_argument("--devices", default="", help="只订阅这些设备 did（逗号分隔），默认全部")
    parser.add_argument("--webhook", default="", help="事件转发的 webhook 地址")
    args = parser.parse_args(argv)

    devices = [d.strip() for d in args.devices.split(",") if d.strip()] or None
    service = MipsService(
        cloud_server=args.cloud,
        devices=devices,
        webhook_url=args.webhook or None,
    )
    if service.load_tokens():
        logger.info("已加载保存的令牌，尝试连接")
        try:
            service.start()
        except Exception as exc:
            logger.warning(
                "自动连接失败，请在页面重新登录",
                extra={"error_type": type(exc).__name__},
            )
    else:
        logger.info("未找到令牌，请在页面登录")

    state = AppState(service)

    @service.on_property_change()
    def _on_prop(event) -> None:
        state.broadcast(
            {
                "type": "property_change",
                "did": event.did,
                "prop": f"{event.siid}.{event.piid}",
                "value": event.value,
            }
        )

    @service.on_device_event()
    def _on_event(event) -> None:
        state.broadcast(
            {
                "type": "device_event",
                "did": event.did,
                "event": f"{event.siid}.{event.eiid}",
                "arguments": event.arguments,
            }
        )

    @service.on_device_state()
    def _on_state(event) -> None:
        state.broadcast({"type": "device_state", "did": event.did, "state": event.state})

    app = create_app(state)
    print(f"MIPS 推送服务: http://{args.host}:{args.port}/", flush=True)
    if args.host not in ("127.0.0.1", "localhost", "::1"):
        print(f"局域网访问: http://{_lan_ip()}:{args.port}/", flush=True)
        print("提示：服务已对局域网开放，事件流对同网设备可见。", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
