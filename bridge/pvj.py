"""PVJ adapter: Logos messages <-> PVJ's OSC namespace.

PVJ Pro listens for OSC on UDP 4855 (OSC_NAMESPACE_SPEC v1, inbound) and can send
its state to a list of targets as /pvj/out/... (opt-in). This module turns

  * human commands typed in Logos Chat   ("bpm 128", "slot 3", "mode random")
  * JSON cues from another bridge        ({"v": 1, "type": "state", "bpm": 128, ...})

into PVJ OSC, and PVJ's /pvj/out/... feedback into JSON cues to send over Logos.
Nothing here needs PVJ's source: it speaks the documented namespace only.
See docs/CUE_PROTOCOL.md.
"""
from __future__ import annotations

import json
import re
import socket
import struct
import threading
import time

PVJ_PORT = 4855
MODES = ("manual", "sequential", "random", "lfo")
XFADE_MODES = ("manual", "beat", "audio", "lfo")
LANE_B_SOURCES = ("clip", "net", "td")
LANES = ("a", "b")

HELP = ("PVJ commands: bpm <40-300> · slot <1-6> [a|b] · auto on|off [a|b] · "
        "mode manual|sequential|random|lfo · xfade <0-1> · xfade manual|beat|audio|lfo · "
        "laneb on|off · laneb clip|net|td   (join several with ;)")


class CommandError(ValueError):
    pass


# --------------------------------------------------------------------------- OSC encode / decode

def _pad(b: bytes) -> bytes:
    return b + b"\0" * (4 - len(b) % 4)


def osc_encode(address: str, args) -> bytes:
    tags, payload = ",", b""
    for a in args:
        if isinstance(a, bool):
            a = int(a)
        if isinstance(a, int):
            tags += "i"
            payload += struct.pack(">i", a)
        elif isinstance(a, float):
            tags += "f"
            payload += struct.pack(">f", a)
        else:
            tags += "s"
            payload += _pad(str(a).encode("utf-8"))
    return _pad(address.encode()) + _pad(tags.encode()) + payload


def _read_str(data: bytes, i: int):
    end = data.index(b"\0", i)
    s = data[i:end].decode("utf-8", "replace")
    return s, (end // 4 + 1) * 4


def osc_decode(data: bytes) -> list:
    """Returns [(address, [args])]; bundles flattened. Strict: unknown tags drop the packet."""
    out = []
    if data.startswith(b"#bundle\0"):
        i = 16
        while i + 4 <= len(data):
            (size,) = struct.unpack(">i", data[i:i + 4])
            out += osc_decode(data[i + 4:i + 4 + size])
            i += 4 + size
        return out
    addr, i = _read_str(data, 0)
    tags, i = _read_str(data, i)
    if not tags.startswith(","):
        return []
    args = []
    for t in tags[1:]:
        if t == "i":
            args.append(struct.unpack(">i", data[i:i + 4])[0]); i += 4
        elif t == "f":
            args.append(struct.unpack(">f", data[i:i + 4])[0]); i += 4
        elif t == "s":
            s, i = _read_str(data, i); args.append(s)
        elif t in "TF":
            args.append(t == "T")
        else:
            return []
    return [(addr, args)]


# --------------------------------------------------------------------------- commands -> OSC

def _onoff(word: str) -> int:
    if word in ("on", "1", "yes", "true"):
        return 1
    if word in ("off", "0", "no", "false"):
        return 0
    raise CommandError(f"expected on/off, got '{word}'")


def _lane(rest: list) -> list:
    if not rest:
        return []
    if rest[0] not in LANES:
        raise CommandError(f"lane must be a or b, got '{rest[0]}'")
    return [rest[0]]


def parse_command(text: str) -> list:
    """Logos message text -> [(osc_address, [args])]. Raises CommandError on anything unclear."""
    t = (text or "").strip()
    if t.startswith("{"):
        try:
            return from_cue(json.loads(t))
        except json.JSONDecodeError as e:
            raise CommandError(f"bad JSON cue: {e}")
    msgs = []
    for part in re.split(r"[;\n]", t):
        w = part.strip().lower().split()
        if not w:
            continue
        cmd, rest = w[0].lstrip("/"), w[1:]
        if cmd == "help":
            raise CommandError(HELP)
        if not rest:
            raise CommandError(f"'{cmd}' needs a value. {HELP}")
        v = rest[0]
        if cmd == "bpm":
            try:
                bpm = float(v)
            except ValueError:
                raise CommandError(f"bpm must be a number, got '{v}'")
            if not 40 <= bpm <= 300:
                raise CommandError("bpm must be between 40 and 300")
            msgs.append(("/pvj/bpm", [round(bpm, 2)]))
        elif cmd == "slot":
            if not v.isdigit() or not 1 <= int(v) <= 6:
                raise CommandError("slot must be 1 to 6")
            msgs.append(("/pvj/seq/slot", [int(v)] + _lane(rest[1:])))
        elif cmd == "auto":
            msgs.append(("/pvj/seq/auto", [_onoff(v)] + _lane(rest[1:])))
        elif cmd == "mode":
            if v not in MODES:
                raise CommandError(f"mode is one of {', '.join(MODES)}")
            msgs.append(("/pvj/mode", [v]))
        elif cmd == "xfade":
            if v in XFADE_MODES:
                msgs.append(("/pvj/xfade/mode", [v]))
            else:
                try:
                    x = float(v)
                except ValueError:
                    raise CommandError(f"xfade is 0-1 or one of {', '.join(XFADE_MODES)}")
                msgs.append(("/pvj/xfade", [max(0.0, min(1.0, x))]))
        elif cmd in ("laneb", "lane_b", "lane-b"):
            if v in LANE_B_SOURCES:
                msgs.append(("/pvj/lane_b/source", [v]))
            else:
                msgs.append(("/pvj/lane_b/arm", [_onoff(v)]))
        else:
            raise CommandError(f"unknown command '{cmd}'. {HELP}")
    if not msgs:
        raise CommandError(HELP)
    return msgs


def from_cue(cue: dict) -> list:
    """JSON cue (docs/CUE_PROTOCOL.md) -> [(osc_address, [args])]."""
    if not isinstance(cue, dict) or cue.get("v") != 1:
        raise CommandError("cue must be a JSON object with \"v\": 1")
    msgs = []
    if "bpm" in cue:
        msgs.append(("/pvj/bpm", [float(cue["bpm"])]))
    if cue.get("mode") in MODES:
        msgs.append(("/pvj/mode", [cue["mode"]]))
    if cue.get("xfade_mode") in XFADE_MODES:
        msgs.append(("/pvj/xfade/mode", [cue["xfade_mode"]]))
    if isinstance(cue.get("xfade"), (int, float)):
        msgs.append(("/pvj/xfade", [max(0.0, min(1.0, float(cue["xfade"])))]))
    seq = cue.get("seq")
    if isinstance(seq, dict):
        lane = [seq["lane"]] if seq.get("lane") in LANES else []
        if isinstance(seq.get("slot"), int) and 1 <= seq["slot"] <= 6:
            msgs.append(("/pvj/seq/slot", [seq["slot"]] + lane))
        if seq.get("auto") in (0, 1, True, False):
            msgs.append(("/pvj/seq/auto", [int(seq["auto"])] + lane))
    lb = cue.get("lane_b")
    if isinstance(lb, dict):
        if lb.get("arm") in (0, 1, True, False):
            msgs.append(("/pvj/lane_b/arm", [int(lb["arm"])]))
        if lb.get("source") in LANE_B_SOURCES:
            msgs.append(("/pvj/lane_b/source", [lb["source"]]))
    if not msgs:
        raise CommandError("cue carries nothing PVJ understands")
    return msgs


def describe(msgs: list) -> str:
    return "; ".join(f"{a} {' '.join(str(x) for x in args)}".strip() for a, args in msgs)


# --------------------------------------------------------------------------- PVJ out -> cue state

class StateMirror:
    """Collects /pvj/out/... from a phone and decides what is worth a Logos message.

    Logos Delivery is rate-limited, so only discrete changes go out (tempo rounded to
    0.1 BPM, mode, crossfade mode, sequencer auto, lane B), coalesced: the latest
    state wins, at most `max_rate` messages a second, with a full keyframe now and then.
    """

    def __init__(self, max_rate: float = 1.0, keyframe_s: float = 30.0, sync_xfade: bool = False):
        self.interval = 1.0 / max(0.05, max_rate)
        self.keyframe_s = keyframe_s
        self.sync_xfade = sync_xfade
        self.state: dict = {}
        self.sent: dict = {}
        self.last_send = 0.0
        self.last_keyframe = 0.0
        self.lock = threading.Lock()

    def feed(self, address: str, args: list) -> None:
        if not args:
            return
        v = args[0]
        key = {
            "/pvj/out/bpm": "bpm", "/pvj/out/mode": "mode", "/pvj/out/xfade/mode": "xfade_mode",
            "/pvj/out/seq/auto": "auto", "/pvj/out/lane_b/arm": "lane_b_arm",
            "/pvj/out/lane_b/source": "lane_b_source", "/pvj/out/clip": "clip",
            "/pvj/out/xfade": "xfade",
        }.get(address)
        if not key:
            return  # beat / bar / tracking: too fast for Logos
        if key == "bpm":
            v = round(float(v), 1)
        elif key == "xfade":
            if not self.sync_xfade:
                return
            v = round(float(v) * 20) / 20
        with self.lock:
            self.state[key] = v

    def due(self, now: float):
        """Returns a cue dict to send now, or None."""
        with self.lock:
            if now - self.last_send < self.interval:
                return None
            keyframe = now - self.last_keyframe >= self.keyframe_s and bool(self.state)
            changed = {k: v for k, v in self.state.items() if self.sent.get(k) != v}
            if not changed and not keyframe:
                return None
            body = dict(self.state) if keyframe else changed
            self.sent.update(self.state if keyframe else changed)
            self.last_send = now
            if keyframe:
                self.last_keyframe = now
        cue = {"v": 1, "type": "state"}
        for k, v in body.items():
            if k == "auto":
                cue.setdefault("seq", {})["auto"] = int(v)
            elif k == "lane_b_arm":
                cue.setdefault("lane_b", {})["arm"] = int(v)
            elif k == "lane_b_source":
                cue.setdefault("lane_b", {})["source"] = v
            else:
                cue[k] = v
        return cue


# --------------------------------------------------------------------------- the adapter

class PvjAdapter:
    def __init__(self, targets: list, listen_port: int, log, max_rate: float = 1.0, sync_xfade: bool = False):
        self.targets = targets              # [(ip, port)]
        self.listen_port = listen_port      # where the phone's /pvj/out goes (0 = off)
        self.log = log
        self.mirror = StateMirror(max_rate=max_rate, sync_xfade=sync_xfade)
        self.out = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.send_cue = None                # set by the Logos link: callable(dict) -> None

    def to_phones(self, msgs: list) -> None:
        for addr, args in msgs:
            pkt = osc_encode(addr, args)
            for t in self.targets:
                try:
                    self.out.sendto(pkt, t)
                except OSError as e:
                    self.log(f"pvj: send to {t[0]}:{t[1]} failed: {e}")

    def handle_text(self, text: str):
        """Logos message -> phones. Returns (ok, reply_text)."""
        try:
            msgs = parse_command(text)
        except CommandError as e:
            return False, str(e)
        self.to_phones(msgs)
        return True, "ok: " + describe(msgs)

    def start_listener(self) -> None:
        if not self.listen_port:
            return
        threading.Thread(target=self._listen, daemon=True).start()
        threading.Thread(target=self._pump, daemon=True).start()

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind(("0.0.0.0", self.listen_port))
        self.log(f"pvj: listening for /pvj/out on udp {self.listen_port}")
        while True:
            data, _ = sock.recvfrom(65536)
            try:
                for addr, args in osc_decode(data):
                    self.mirror.feed(addr, args)
            except (ValueError, struct.error, IndexError):
                continue

    def _pump(self) -> None:
        while True:
            time.sleep(0.1)
            cue = self.mirror.due(time.time())
            if cue and self.send_cue:
                self.send_cue(cue)


def parse_targets(spec: str) -> list:
    out = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        host, _, port = part.partition(":")
        out.append((host, int(port or PVJ_PORT)))
    return out
