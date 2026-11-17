#!/usr/bin/env python3
"""A stand-in for a PVJ phone, for testing the bridge without one.

Listens on UDP 4855 like PVJ Pro and prints every /pvj/... command it gets.
With --out HOST:PORT it also sends a changing /pvj/out/... state, like PVJ's
OSC feedback, so the bridge's Logos cue path can be tested.

    python tools/fake_pvj.py                      # print commands
    python tools/fake_pvj.py --out 127.0.0.1:9000 # and send state to the bridge
"""
import argparse, os, random, socket, sys, threading, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bridge"))
from pvj import osc_decode, osc_encode, MODES, XFADE_MODES  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=4855)
ap.add_argument("--out", default="", help="HOST:PORT to send /pvj/out state to")
a = ap.parse_args()

def send_state():
    host, port = a.out.split(":")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    bpm, mode = 124.0, "manual"
    while True:
        time.sleep(random.uniform(2, 5))
        if random.random() < 0.5:
            bpm = round(random.choice([120, 124, 126, 128, 132]) + random.random() * 0.04, 3)
        else:
            mode = random.choice(MODES)
        for addr, args in (("/pvj/out/bpm", [float(bpm)]), ("/pvj/out/mode", [mode]),
                           ("/pvj/out/beat", [random.randint(1, 4)]), ("/pvj/out/xfade/mode", [random.choice(XFADE_MODES)])):
            s.sendto(osc_encode(addr, args), (host, int(port)))
        print(f"[fake pvj] state out: bpm {bpm} mode {mode}", flush=True)

if a.out:
    threading.Thread(target=send_state, daemon=True).start()
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", a.port))
print(f"[fake pvj] listening on udp {a.port}", flush=True)
while True:
    data, src = sock.recvfrom(65536)
    for addr, args in osc_decode(data):
        print(f"[fake pvj] {src[0]}  {addr} {' '.join(map(str, args))}", flush=True)
