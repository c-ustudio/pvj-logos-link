# Cue protocol v1

How messages on Logos map to OSC in `pvj-logos-link`. Two kinds of message travel as ordinary Logos Chat messages (end-to-end encrypted, carried by Logos Delivery):

- **Commands**: short text a person types in Logos Chat, such as `bpm 128`.
- **Cues**: JSON that one bridge sends to another, such as `{"v":1,"type":"state","bpm":128}`.

The bridge turns both into OSC for the receiving software, and turns that software's OSC feedback back into cues.

## Commands (typed by people)

Case-insensitive; several in one message separated by `;`.

| Command | Meaning | PVJ OSC sent |
| --- | --- | --- |
| `bpm 128` | Tempo, 40 to 300 | `/pvj/bpm f` |
| `slot 3` / `slot 3 b` | Load sequence slot 1 to 6 (lane a by default), on the next bar | `/pvj/seq/slot i [s]` |
| `auto on` / `auto off b` | Sequencer auto-advance | `/pvj/seq/auto i [s]` |
| `mode random` | `manual`, `sequential`, `random` or `lfo` | `/pvj/mode s` |
| `xfade 0.5` | Crossfader position, 0 to 1 | `/pvj/xfade f` |
| `xfade beat` | Crossfade mode: `manual`, `beat`, `audio` or `lfo` | `/pvj/xfade/mode s` |
| `laneb on` / `laneb off` | Arm lane B | `/pvj/lane_b/arm i` |
| `laneb clip` | Lane B source: `clip`, `net` or `td` | `/pvj/lane_b/source s` |
| `next` / `prev` | Next or previous clip, at once (like PVJ's NEXT/PREV buttons) | `/pvj/deck/next`, `/pvj/deck/prev` |
| `clip 3` / `clip pvj_loop_07` | Jump to a clip, at once: its number as PVJ shows it (`CLIP 3/31`), or its name (file name with or without extension, any case) | `/pvj/deck/clip i` or `s` |
| `help` | Replies with this list (with `--confirm`) | none |

Anything else is rejected whole: a message is applied completely or not at all.

## Cues (sent by bridges)

```json
{"v": 1, "type": "state",
 "bpm": 128.0,
 "mode": "random",
 "xfade_mode": "beat",
 "xfade": 0.5,
 "seq": {"slot": 3, "auto": 1, "lane": "a"},
 "lane_b": {"arm": 1, "source": "clip"},
 "clip": "pvj_loop_07.mp4"}
```

- Every field except `v` and `type` is optional; a cue carries only what changed, plus a full keyframe every 30 s.
- `clip` is the playing clip's file name with its extension, exactly as PVJ sends it in `/pvj/out/clip` (a string). Cues report it; they do not set it. To change clip, send the `clip` command: PVJ's `/pvj/deck/clip` accepts that same file name, so a reported value can be sent straight back.
- Unknown fields are ignored, so v1 receivers accept cues from later senders.

## Rate and timing

Logos Delivery limits how often each publisher can send. The bridge therefore:

- sends only discrete changes (tempo rounded to 0.1 BPM, modes, slots, lane B), at most `--max-rate` cues a second (default 1), latest state wins;
- never sends per-beat or per-frame data (`/pvj/out/beat`, `/pvj/out/bar`, tracking);
- sends crossfader moves only with `--sync-xfade`, coarsened to steps of 0.05.

Timing is left to the receiver: PVJ applies `/pvj/seq/*` on its own next downbeat (`next`, `prev` and `clip` apply at once, like a button), so a cue that arrives a little late still lands on the bar. Tempo follows PVJ's rule of one tempo authority: send `bpm` to the main phone and its link spreads it to the others.

## Security

A bridge's Logos address is effectively a remote control. Use `--allow` with the Logos account addresses of the people who may control it; without it, anyone who has the address can. The bridge logs every ignored sender.

## OSC namespaces

| Direction | Addresses | Notes |
| --- | --- | --- |
| Bridge → PVJ | `/pvj/...` on UDP 4855 | PVJ's `OSC_NAMESPACE_SPEC` v1, inbound |
| PVJ → bridge | `/pvj/out/...` on UDP 9000 (`--pvj-listen`) | Enable on the phone: `[osc] out_enabled=true`, `out_targets="<laptop-ip>:9000"` in `settings.cfg` |
| Bridge → TD / Bitwig | `/logos/message`, `/logos/count`, `/logos/address`, `/logos/state` on UDP 7000 | Every shown message, both modes |
