# pvj-logos-link

Connects [Logos](https://logos.co) to live visuals. A small bridge brings up a Logos Chat node through `logosctl` and turns messages into OSC for [PVJ](https://c-u.studio/tools/pvj), TouchDesigner or Bitwig, and PVJ's state back into Logos messages. By [Collective Unconscious](https://c-u.studio).

```
              Logos network (Delivery, end-to-end encrypted Chat)
                 ▲                                      ▲
   Logos Chat ───┘                                      └─── another pvj-logos-link
   (anyone's Basecamp)                                        (another venue, another phone)
                 │
         logosctl + chat_module
                 │
          bridge/logos_bridge.py ──── OSC /pvj/...  ──▶ PVJ phone(s)  (UDP 4855)
                 │              ◀─── OSC /pvj/out ──── PVJ phone     (UDP 9000)
                 ├──── OSC /logos/... ──▶ TouchDesigner, Bitwig       (UDP 7000)
                 └──── SSE ──▶ browser visual (examples/signals)      (http://127.0.0.1:8765)
```

**Status: alpha, on the Logos testnet.** The bridge, the PVJ mapping and the Signals visual are tested with mocks and a fake PVJ. The live Logos path is next (see Open questions).

## Modes

| Mode | What happens |
| --- | --- |
| `signals` (default) | Every message becomes a frequency: a wave line, the text and a tone in the browser visual, plus `/logos/message` OSC. Built for the Freequencies night in Lisbon. |
| `pvj` | Messages become PVJ commands (`bpm 128`, `slot 3`, `mode random`) over PVJ's OSC namespace. PVJ's `/pvj/out` state goes to another bridge as JSON cues, so two phones in different places stay in step. |

The message format is in [docs/CUE_PROTOCOL.md](docs/CUE_PROTOCOL.md).

## Run it

Needs Python 3.9+ (standard library only). `logosctl` is installed on the first real run from the official Logos script; its session lives in `session/` inside this folder.

**Windows**: double-click

| File | Does |
| --- | --- |
| `run-signals-mock.bat` | Signals with fake messages, no Logos |
| `run-signals.bat` | Signals on the Logos testnet |
| `run-pvj-mock.bat` | Fake PVJ commands to a phone, no Logos |
| `run-pvj.bat` | Logos Chat → PVJ phone; asks for the phone's IP, replies `ok: ...` to senders |
| `stop-logos.bat` | Stops the Logos runtime (the next start gets a new address) |

**macOS / Linux**

```sh
./run.sh --mock                                    # Signals, fake messages
./run.sh                                           # Signals on the testnet
./run.sh --mode pvj --pvj 192.168.1.40 --confirm   # Logos -> PVJ
python3 bridge/logos_bridge.py --help              # every option
```

The first real start installs `delivery_module` and `chat_module` and can take a few minutes before the status turns green. The node's Logos address shows at the bottom of the visual and in `logos-address.txt`.

## PVJ mode in practice

1. **Phone**: PVJ Pro on the same network as the laptop. OSC input is on by default (UDP 4855).
2. **Laptop**: `run-pvj.bat` (or `./run.sh --mode pvj --pvj <phone-ip> --confirm`).
3. **Control**: from Logos Chat, open a direct conversation with the bridge's address and send `bpm 126; slot 2`. Sequence changes land on the phone's next bar; `next`, `prev` and `clip 3` (or `clip <name>`) change clip at once.
4. **Lock it**: add `--allow <your Logos address>`, or anyone who has the address can drive the phone.

**Two phones, two places.** On the phone that leads, open LIB ▸ OSC, turn OSC OUT on and set OUT TARGETS to `<laptop-ip>:9000` (older Pro builds: `[osc] out_enabled=true` and `out_targets="<laptop-ip>:9000"` in PVJ's `settings.cfg`). LIB ▸ OSC also shows the phone's IP for `--pvj`. Run a bridge next to each phone and pass the other bridge's address with `--peer`. Changes on the leading phone (tempo, mode, crossfade mode, lane B) reach the other phone as cues, at most one a second.

**No phone?** `python tools/fake_pvj.py` listens on 4855 like PVJ and prints what it gets; `--out 127.0.0.1:9000` makes it send PVJ-style state back.

## Signals in practice

People install Logos Basecamp, add **Chat** from the Package Manager, open a direct conversation with the address on screen and send a message. On a public screen the bridge caps messages at 120 characters, allows one per sender every 15 s, drops anything matching `blocklist.txt`, and the operator can pause (`P`) or hide (`H`). Press `?` in the visual for all keys.

## Windows notes (Basecamp 0.3.2, checked 2026-11-17)

- `delivery_module` 0.3.3, the newest, ships no Windows build (only darwin-arm64, linux-amd64, linux-arm64); Basecamp downloads it and then refuses it. 0.3.2 has one. In Basecamp, open **Chat** under Applications and pick Delivery Module **v0.3.2** before installing; don't press **Update** afterwards. The bridge pins `delivery_module@0.3.2` on Windows for the same reason.
- Untick the optional **RLN Module** and **libp2p Networking** in that dialog: `libp2p_module` and `liblogos_lez_rln_module` have no Windows builds either.
- **A Windows node can receive but not send on `logos.test`.** `delivery_module` attaches an RLN proof to every message; with no RLN module it parks each send and retries forever (`Failed to attach RLN proof … parking task for a later round` in the daemon log), while the status still says Online. Chat messages from Basecamp on Windows never reach the bridge, and the bridge's `ok:` replies and `--peer` cues never leave. Checked 2026-11-17.
- On some machines Basecamp's dialog buttons react to a double-click, not a single click.
- Windows Firewall may ask about `logos_host`. Outgoing connections are enough for Chat; incoming ones matter only for serving Storage files and for PVJ's `/pvj/out` reaching the bridge (set the network to Private).

## Open questions (for the Logos team)

- Will `delivery_module` 0.3.3+ get a Windows build again (and `libp2p_module`, `liblogos_lez_rln_module`)?

- ~~Do senders need an RLN membership to publish on `logos.test`?~~ Yes. Every sending node needs `liblogos_rln_module` (macOS/Linux only) and a membership registered on LEZ, paid from the node's payer account: about 250,000,000 native LEZ units, and the testnet has no faucet (Logos docs, `docs/lez/rln/register-rln-membership-on-lez-with-delivery-node.md`). On Linux the bridge installs the modules (`--packages delivery_module,chat_module,liblogos_rln_module`), syncs the LEZ wallet (~5 min), then logs `waiting for <payer> to hold 182800000 native`.
- How should a public demo get testnet LEZ for every sender? (A faucet, or memberships for Basecamp users?) And when will the RLN modules have Windows builds?
- A chat installation gets a new address on every `init`. Is there a way to keep a stable address across restarts for a public demo?
- The bridge reads `logosctl watch chat_module --json` loosely (named or positional `data`); raw events are logged to `logs/events-*.ndjson`. A confirmed example of `message_received` would let us tighten it.
- Is Chat the right carrier for machine cues, or should bridges publish on a Delivery content topic directly (with its own rate limit)?

## Files

```
bridge/logos_bridge.py     the bridge: logosctl session, Chat node, HTTP + SSE, OSC out, modes
bridge/pvj.py              PVJ adapter: commands and cues <-> PVJ's OSC namespace
examples/signals/visual/   the Signals visual (WebGL, Server-Sent Events, Web Audio)
docs/CUE_PROTOCOL.md       commands, JSON cues, rates, OSC addresses
tools/fake_pvj.py          a stand-in PVJ phone for testing
blocklist.txt              words that keep a message off the Signals screen
run.ps1, run.sh, *.bat     launchers
```

## License

To be decided before the repo is shared (Logos itself is dual MIT / Apache-2.0).
