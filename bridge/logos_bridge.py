#!/usr/bin/env python3
"""pvj-logos-link: Logos Chat <-> OSC, for live visuals and music software.

Brings up a Logos Chat node through `logosctl` and connects it to the AV world:

  --mode signals   every message becomes a frequency in the browser visual
                   (examples/signals) and an OSC message for TD / Bitwig
  --mode pvj       messages become PVJ commands over PVJ's OSC namespace, and
                   PVJ's /pvj/out state goes back over Logos as JSON cues

Standard library only (Python 3.9+). Runs on Windows, macOS and Linux.

    python bridge/logos_bridge.py --mock                         # fake messages, no Logos
    python bridge/logos_bridge.py                                # Signals on the Logos testnet
    python bridge/logos_bridge.py --mode pvj --pvj 192.168.1.40  # Logos -> a PVJ phone

OSC out (default 127.0.0.1:7000):
    /logos/message  s:sender  s:text  f:freq_hz  f:hue_0_1
    /logos/count    i:messages_shown
    /logos/address  s:logos_address
    /logos/state    s:state  s:detail
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import random
import re
import shutil
import socket
import struct
import subprocess
import sys
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VISUAL = ROOT / "examples" / "signals" / "visual"
LOG_DIR = ROOT / "logs"

# --------------------------------------------------------------------------- logging

_log_lock = threading.Lock()
_log_file = None


def log(msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    with _log_lock:
        try:
            print(line, flush=True)
        except UnicodeEncodeError:
            print(line.encode("ascii", "replace").decode(), flush=True)
        if _log_file:
            _log_file.write(line + "\n")
            _log_file.flush()


def open_log() -> None:
    global _log_file
    LOG_DIR.mkdir(exist_ok=True)
    _log_file = open(LOG_DIR / f"bridge-{time.strftime('%Y%m%d-%H%M%S')}.log", "a", encoding="utf-8")


# --------------------------------------------------------------------------- OSC


def _pad(b: bytes) -> bytes:
    return b + b"\0" * (4 - len(b) % 4)


def osc_packet(address: str, *args) -> bytes:
    tags, payload = ",", b""
    for a in args:
        if isinstance(a, bool):
            a = int(a)
        if isinstance(a, int):
            tags += "i"
            payload += struct.pack(">i", max(-(2**31), min(2**31 - 1, a)))
        elif isinstance(a, float):
            tags += "f"
            payload += struct.pack(">f", a)
        else:
            tags += "s"
            payload += _pad(str(a).encode("utf-8"))
    return _pad(address.encode()) + _pad(tags.encode()) + payload


class Osc:
    def __init__(self, host: str, port: int, enabled: bool = True):
        self.target = (host, port)
        self.enabled = enabled
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) if enabled else None

    def send(self, address: str, *args) -> None:
        if not self.enabled:
            return
        try:
            self.sock.sendto(osc_packet(address, *args), self.target)
        except OSError as e:
            log(f"osc send failed: {e}")


# --------------------------------------------------------------------------- event hub (SSE)


class Hub:
    """Fans events out to every connected browser."""

    def __init__(self):
        self.lock = threading.Lock()
        self.clients: set[queue.Queue] = set()
        self.history: deque = deque(maxlen=12)
        self.count = 0
        self.state = {"state": "starting", "detail": "", "address": "", "mode": "logos"}

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=256)
        with self.lock:
            self.clients.add(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self.lock:
            self.clients.discard(q)

    def snapshot(self) -> dict:
        with self.lock:
            return {"type": "hello", **self.state, "count": self.count, "recent": list(self.history)}

    def set_state(self, **kw) -> None:
        with self.lock:
            self.state.update(kw)
            data = {"type": "state", **self.state, "count": self.count}
        self._broadcast(data)

    def message(self, data: dict) -> int:
        with self.lock:
            self.count += 1
            data = {"type": "message", "id": self.count, **data}
            self.history.append(data)
            n = self.count
        self._broadcast(data)
        return n

    def _broadcast(self, data: dict) -> None:
        payload = json.dumps(data, ensure_ascii=False)
        with self.lock:
            clients = list(self.clients)
        for q in clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass


# --------------------------------------------------------------------------- moderation


class Moderator:
    """A public screen needs a floor: length cap, blocklist, per-sender cooldown, pause."""

    def __init__(self, max_len: int, cooldown_s: float, blocklist: Path):
        self.max_len = max_len
        self.cooldown_s = cooldown_s
        self.blocked = []
        if blocklist.exists():
            for line in blocklist.read_text(encoding="utf-8").splitlines():
                w = line.strip().lower()
                if w and not w.startswith("#"):
                    self.blocked.append(w)
        self.last_seen: dict[str, float] = {}
        self.paused = False

    def check(self, sender: str, text: str):
        if self.paused:
            return False, "paused"
        text = re.sub(r"[\x00-\x1f\x7f]", " ", str(text))
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            return False, "empty"
        low = text.lower()
        for w in self.blocked:
            if w in low:
                return False, "blocklist"
        now = time.time()
        if now - self.last_seen.get(sender, 0) < self.cooldown_s:
            return False, "cooldown"
        self.last_seen[sender] = now
        if len(text) > self.max_len:
            text = text[: self.max_len - 1].rstrip() + "…"
        return True, text


# --------------------------------------------------------------------------- message -> frequency

PENTATONIC = [0, 2, 4, 7, 9]


def tone_for(text: str):
    """Same text, same note and colour, everywhere (browser, TD, Bitwig)."""
    h = int(hashlib.sha1(text.encode("utf-8")).hexdigest(), 16)
    semis = (h % 2) * 12 + PENTATONIC[(h // 2) % 5]
    freq = 220.0 * 2 ** (semis / 12)  # two octaves: 220 Hz .. ~740 Hz
    hue = ((h // 15) % 360) / 360.0
    return round(freq, 2), round(hue, 4)


def short_id(addr: str) -> str:
    addr = str(addr or "anon")
    return addr if len(addr) <= 12 else f"{addr[:6]}…{addr[-4:]}"


class Deliver:
    def __init__(self, hub: Hub, osc: Osc, mod: Moderator):
        self.hub, self.osc, self.mod = hub, osc, mod

    def __call__(self, sender: str, text: str, source: str = "logos") -> bool:
        ok, res = self.mod.check(sender, text)
        if not ok:
            log(f"skipped message from {short_id(sender)} ({res})")
            return False
        freq, hue = tone_for(res)
        who = short_id(sender)
        n = self.hub.message({"sender": who, "text": res, "freq": freq, "hue": hue, "ts": time.time(), "source": source})
        self.osc.send("/logos/message", who, res, float(freq), float(hue))
        self.osc.send("/logos/count", n)
        log(f"#{n} {who}: {res}")
        return True


# --------------------------------------------------------------------------- logosctl

SIGNATURES = {
    "message_received": ["convo_id", "content", "timestamp_ms", "sender"],
    "message_sent": ["convo_id", "content", "timestamp_ms"],
    "conversation_created": ["convo_id", "is_outgoing", "peer_label", "kind", "name", "desc"],
    "delivery_state_changed": ["delivery_state", "detail", "delivery_adopted"],
}


def normalise_event(obj: dict):
    """logosctl prints {"timestamp","module","event","data"}; data may be a dict or positional list."""
    name = obj.get("event") or obj.get("name") or ""
    data = obj.get("data", obj.get("args", obj.get("params")))
    fields = SIGNATURES.get(name, [])
    if isinstance(data, list):
        return name, {(fields[i] if i < len(fields) else f"arg{i}"): v for i, v in enumerate(data)}
    if isinstance(data, dict):
        if fields and not any(f in data for f in fields):
            vals = list(data.values())
            return name, {(fields[i] if i < len(fields) else f"arg{i}"): v for i, v in enumerate(vals)}
        return name, dict(data)
    return name, {"value": data}


def find_logosctl(explicit: str | None) -> str | None:
    if explicit:
        return explicit
    found = shutil.which("logosctl")
    if found:
        return found
    candidates = []
    if os.name == "nt":
        candidates.append(Path(os.environ.get("LOCALAPPDATA", "")) / "logosctl" / "bin" / "logosctl.exe")
    candidates.append(Path.home() / ".local" / "logosctl" / "bin" / "logosctl")
    candidates.append(Path("/usr/local/bin/logosctl"))
    for c in candidates:
        if c.exists():
            return str(c)
    return None


class Logosctl:
    def __init__(self, exe: str, session: Path, module: str):
        self.exe, self.session, self.module = exe, session, module
        self.flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW

    def base(self) -> list[str]:
        return [self.exe, "--config-dir", str(self.session), "--json"]

    def run(self, *args: str, timeout: float = 120):
        cmd = self.base() + list(args)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout, creationflags=self.flags)
        except subprocess.TimeoutExpired:
            log(f"logosctl {' '.join(args)}: timed out after {timeout}s")
            return None
        out = (p.stdout or "").strip()
        parsed = None
        for line in reversed(out.splitlines()):
            line = line.strip()
            if line.startswith("{") or line.startswith("["):
                try:
                    parsed = json.loads(line)
                    break
                except json.JSONDecodeError:
                    continue
        if p.returncode != 0:
            err = (p.stderr or "").strip().splitlines()
            log(f"logosctl {' '.join(args)} -> exit {p.returncode}: {(err[-1] if err else out[-300:])}")
        return parsed if parsed is not None else ({"status": "ok", "raw": out} if p.returncode == 0 else None)

    def daemon_running(self) -> bool:
        r = self.run("daemon", "status", timeout=30)
        return bool(r) and isinstance(r.get("daemon"), dict) and r["daemon"].get("status") == "running"

    def call(self, method: str, *args: str, timeout: float = 60):
        r = self.run("call", self.module, method, *args, timeout=timeout)
        if not r or r.get("status") != "ok":
            return None
        res = r.get("result")
        if isinstance(res, dict) and "success" in res and "value" in res:
            return res.get("value") if res.get("success") else None
        return res

    def watch(self) -> subprocess.Popen:
        return subprocess.Popen(self.base() + ["watch", self.module], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                                bufsize=1, creationflags=self.flags)


class LogosLink(threading.Thread):
    """Brings chat_module up on the testnet and feeds inbound messages to Deliver."""

    def __init__(self, args, hub: Hub, deliver: Deliver, on_message=None):
        super().__init__(daemon=True)
        self.args, self.hub, self.deliver = args, hub, deliver
        # on_message(sender, content, convo_id) -> optional reply text
        self.on_message = on_message or (lambda sender, content, convo: (deliver(sender, content), None)[1])
        self.peer_convo: str | None = None
        self.online = threading.Event()
        self.ctl: Logosctl | None = None
        self.watcher: subprocess.Popen | None = None
        self.raw = open(LOG_DIR / f"events-{time.strftime('%Y%m%d-%H%M%S')}.ndjson", "a", encoding="utf-8")

    def state(self, state: str, detail: str = "") -> None:
        log(f"state: {state} {detail}".rstrip())
        self.hub.set_state(state=state, detail=detail)
        self.deliver.osc.send("/logos/state", state, detail)

    def run(self) -> None:
        while True:
            try:
                self.session_once()
            except Exception as e:  # keep the demo alive whatever happens
                self.state("error", f"{type(e).__name__}: {e}")
            if self.watcher and self.watcher.poll() is None:
                self.watcher.terminate()
            time.sleep(10)
            self.state("connecting", "retrying")

    def session_once(self) -> None:
        a = self.args
        exe = find_logosctl(a.logosctl)
        if not exe:
            self.state("error", "logosctl not found: run run-demo.ps1 (Windows) or run-demo.sh first")
            time.sleep(50)
            return
        ctl = self.ctl = Logosctl(exe, Path(a.session), a.module)
        Path(a.session).mkdir(parents=True, exist_ok=True)

        self.state("connecting", "starting the Logos runtime")
        if not ctl.daemon_running():
            ctl.run("daemon", "start", "--detach", timeout=180)
            if not ctl.daemon_running():
                raise RuntimeError("logosctl daemon did not start (see session/logs)")

        listing = json.dumps(ctl.run("module", "ls", timeout=60) or {})
        missing = [p for p in a.packages.split(",") if p and p not in listing]
        if missing:
            self.state("connecting", f"installing {', '.join(missing)}")
            ctl.run("package", "install", *missing, "-y", timeout=900)

        self.state("connecting", f"loading {a.module}")
        ctl.run("module", "load", a.module, timeout=180)

        # Subscribe before init, or the first events are missed.
        self.watcher = ctl.watch()
        threading.Thread(target=self.read_events, daemon=True).start()
        time.sleep(1.0)

        self.state("connecting", f"joining {a.preset}")
        ctl.call("init", "json:" + json.dumps({"delivery_preset": a.preset}), timeout=120)

        deadline = time.time() + 240
        while time.time() < deadline and not self.online.is_set():
            st = ctl.call("status", timeout=30)
            if isinstance(st, dict) and st.get("delivery_state") == "online":
                self.online.set()
                break
            if isinstance(st, dict) and st.get("delivery_state") == "error":
                raise RuntimeError(f"delivery error: {st.get('detail', '')}")
            self.online.wait(3)
        if not self.online.is_set():
            raise RuntimeError("delivery did not come online within 4 minutes")

        addr = ctl.call("get_address", timeout=30)
        addr = addr if isinstance(addr, str) else json.dumps(addr)
        self.hub.set_state(address=addr)
        self.deliver.osc.send("/logos/address", addr)
        (ROOT / "logos-address.txt").write_text(addr + "\n", encoding="utf-8")
        log(f"Logos address: {addr}")
        if self.args.peer:
            convo = ctl.call("create_conversation", "str:" + self.args.peer, timeout=60)
            if isinstance(convo, str) and convo:
                self.peer_convo = convo
                log(f"conversation with peer {short_id(self.args.peer)}: {convo}")
            else:
                log("could not open a conversation with --peer (check the address)")
        self.state("online", "send a message to the address on screen")

        while self.watcher.poll() is None:
            time.sleep(2)
        self.online.clear()
        raise RuntimeError("event stream ended (daemon stopped?)")

    def read_events(self) -> None:
        w = self.watcher
        for line in w.stdout:
            line = line.strip()
            if not line:
                continue
            self.raw.write(line + "\n")
            self.raw.flush()
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("status") == "error":
                log(f"watch: {obj.get('message', line)}")
                continue
            name, d = normalise_event(obj)
            if name == "message_received":
                convo = str(d.get("convo_id", ""))
                answer = self.on_message(str(d.get("sender", "anon")), str(d.get("content", "")), convo)
                text = answer or self.args.reply
                if text and convo:
                    threading.Thread(target=self.send, args=(convo, text), daemon=True).start()
            elif name == "delivery_state_changed":
                s = str(d.get("delivery_state", ""))
                if s == "online":
                    self.online.set()
                self.hub.set_state(network=s)
            elif name == "conversation_created" and not d.get("is_outgoing", False):
                log(f"new conversation from {short_id(d.get('peer_label', ''))}")

    def send(self, convo_id: str, text: str) -> None:
        if self.ctl and self.online.is_set():
            self.ctl.call("send_message", "str:" + convo_id, "str:" + text, timeout=60)

    def send_to_peer(self, cue: dict) -> None:
        if self.peer_convo:
            self.send(self.peer_convo, json.dumps(cue, separators=(",", ":")))


# --------------------------------------------------------------------------- mock source

MOCK_TEXTS = [
    "hello from the other side of the room", "privacy is a frequency", "can you hear this?",
    "olá lisboa", "signal > noise", "sent from a laptop, no server in between",
    "who else is on the testnet tonight", "bona nit des de Begur", "every message is a note",
    "turn it up", "parallel societies need parallel channels", "bass please", "testing 1 2 3",
]


def mock_source(deliver: Deliver, hub: Hub, every: float) -> None:
    hub.set_state(state="online", detail="mock mode: fake messages", mode="mock",
                  address="mock-0x" + "".join(random.choice("0123456789abcdef") for _ in range(40)))
    senders = ["0x" + "".join(random.choice("0123456789abcdef") for _ in range(40)) for _ in range(6)]
    while True:
        time.sleep(random.uniform(every * 0.6, every * 1.4))
        deliver(random.choice(senders), random.choice(MOCK_TEXTS), source="mock")


# --------------------------------------------------------------------------- HTTP


def make_handler(hub: Hub, deliver: Deliver, mod: Moderator, visual_dir: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "LogosBridge/1"

        def log_message(self, fmt, *args):  # quiet
            pass

        def _local(self) -> bool:
            return self.client_address[0] in ("127.0.0.1", "::1")

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0]
            if path == "/events":
                return self.events()
            if path == "/state":
                return self._json(hub.snapshot())
            if path == "/":
                path = "/index.html"
            f = (visual_dir / path.lstrip("/")).resolve()
            if visual_dir.resolve() not in f.parents or not f.is_file():
                self.send_error(404)
                return
            ctype = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
                     ".png": "image/png", ".svg": "image/svg+xml"}.get(f.suffix, "application/octet-stream")
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            # Operator controls, from this machine only: /control?action=pause|resume|test
            if not self._local():
                return self._json({"ok": False, "error": "local only"}, 403)
            q = self.path.split("?", 1)[1] if "?" in self.path else ""
            action = dict(p.split("=", 1) for p in q.split("&") if "=" in p).get("action", "")
            if action == "pause":
                mod.paused = True
            elif action == "resume":
                mod.paused = False
            elif action == "test":
                deliver("operator", random.choice(MOCK_TEXTS), source="test")
            hub.set_state(paused=mod.paused)
            return self._json({"ok": True, "paused": mod.paused})

        def events(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()
            q = hub.subscribe()
            try:
                self.wfile.write(f"data: {json.dumps(hub.snapshot(), ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        payload = q.get(timeout=15)
                        self.wfile.write(f"data: {payload}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                hub.unsubscribe(q)

    return Handler


# --------------------------------------------------------------------------- main


def mock_pvj_source(adapter, deliver: Deliver, hub: Hub, every: float) -> None:
    hub.set_state(state="online", detail="mock mode: fake PVJ commands", mode="mock",
                  address="mock-0x" + "".join(random.choice("0123456789abcdef") for _ in range(40)))
    cmds = ["bpm 124", "slot 2", "mode random", "xfade beat", "slot 4 b", "laneb on", "bpm 128.5",
            "mode sequential", "auto on", "xfade 0.5", "laneb clip", "slot 1"]
    sender = "0x" + "".join(random.choice("0123456789abcdef") for _ in range(40))
    while True:
        time.sleep(random.uniform(every * 0.6, every * 1.4))
        cmd = random.choice(cmds)
        ok, info = adapter.handle_text(cmd)
        log(f"mock -> pvj: {info}")
        if ok:
            deliver(sender, cmd, source="mock")


def main() -> None:
    ap = argparse.ArgumentParser(description="Logos Chat <-> OSC (Signals visual, PVJ, TD, Bitwig)")
    ap.add_argument("--mode", choices=("signals", "pvj"), default="signals")
    ap.add_argument("--mock", action="store_true", help="fake messages, no Logos needed")
    ap.add_argument("--mock-every", type=float, default=6.0, help="seconds between mock messages")
    ap.add_argument("--host", default="127.0.0.1", help="HTTP bind address (0.0.0.0 to view from another machine)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--visual", default=str(DEFAULT_VISUAL), help="folder served at / (the Signals visual)")
    ap.add_argument("--osc-host", default="127.0.0.1", help="OSC target for /logos/... (TD, Bitwig)")
    ap.add_argument("--osc-port", type=int, default=7000)
    ap.add_argument("--no-osc", action="store_true")
    ap.add_argument("--logosctl", help="path to logosctl if not on PATH")
    ap.add_argument("--session", default=str(ROOT / "session"), help="logosctl session dir (kept inside this folder)")
    ap.add_argument("--module", default="chat_module")
    ap.add_argument("--packages", default="delivery_module,chat_module")
    ap.add_argument("--preset", default="logos.test")
    ap.add_argument("--reply", default="", help="optional fixed auto-reply to each sender")
    ap.add_argument("--peer", default="", help="Logos address of another bridge to send cues to")
    ap.add_argument("--max-len", type=int, default=120)
    ap.add_argument("--cooldown", type=float, default=15.0, help="seconds between shown messages per sender")
    ap.add_argument("--blocklist", default=str(ROOT / "blocklist.txt"))
    ap.add_argument("--open", action="store_true", help="open the visual in the default browser")
    pv = ap.add_argument_group("pvj mode")
    pv.add_argument("--pvj", default="", help="PVJ phone(s): ip[:port],ip[:port]  (port 4855 by default)")
    pv.add_argument("--pvj-listen", type=int, default=9000, help="UDP port for the phone's /pvj/out (0 = off)")
    pv.add_argument("--allow", default="", help="Logos sender addresses allowed to control PVJ (comma list); empty = anyone")
    pv.add_argument("--confirm", action="store_true", help="reply 'ok: ...' or the error to each sender")
    pv.add_argument("--max-rate", type=float, default=1.0, help="cues per second sent over Logos")
    pv.add_argument("--sync-xfade", action="store_true", help="also send crossfader moves (coarse)")
    a = ap.parse_args()

    open_log()
    hub = Hub()
    osc = Osc(a.osc_host, a.osc_port, enabled=not a.no_osc)
    mod = Moderator(a.max_len, a.cooldown if a.mode == "signals" else min(a.cooldown, 0.5), Path(a.blocklist))
    deliver = Deliver(hub, osc, mod)

    server = ThreadingHTTPServer((a.host, a.port), make_handler(hub, deliver, mod, Path(a.visual)))
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}/"
    log(f"mode: {a.mode}   visual: {url}   osc: {'off' if a.no_osc else f'{a.osc_host}:{a.osc_port}'}")

    on_message = None
    adapter = None
    if a.mode == "pvj":
        import pvj
        targets = pvj.parse_targets(a.pvj)
        if not targets:
            log("pvj mode: no --pvj target given, commands will only show on screen")
        adapter = pvj.PvjAdapter(targets, a.pvj_listen, log, max_rate=a.max_rate, sync_xfade=a.sync_xfade)
        allowed = {x.strip() for x in a.allow.split(",") if x.strip()}
        if not allowed:
            log("pvj mode: OPEN - anyone with this node's Logos address can control the phone (use --allow)")

        def on_message(sender: str, content: str, convo: str):
            if allowed and sender not in allowed:
                log(f"pvj: ignored {short_id(sender)} (not in --allow)")
                return None
            ok, info = adapter.handle_text(content)
            log(f"pvj <- {short_id(sender)}: {content!r} -> {info}")
            if ok:
                deliver(sender, content, source="logos")
            return info if a.confirm else None

        adapter.start_listener()

    if a.mock:
        if adapter:
            threading.Thread(target=mock_pvj_source, args=(adapter, deliver, hub, a.mock_every), daemon=True).start()
        else:
            threading.Thread(target=mock_source, args=(deliver, hub, a.mock_every), daemon=True).start()
    else:
        link = LogosLink(a, hub, deliver, on_message=on_message)
        if adapter:
            adapter.send_cue = link.send_to_peer
        link.start()

    if a.open:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log("stopping (the logosctl daemon keeps running, so the address stays the same next time)")
        server.shutdown()


if __name__ == "__main__":
    main()
