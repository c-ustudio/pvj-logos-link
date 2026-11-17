# Controlling PVJ from Logos Basecamp

You type a short command into a Basecamp **Chat** conversation; the bridge on the laptop turns it into
OSC and sends it to the phone running **PVJ Pro**. One message can carry several commands joined with `;`.

```
Basecamp Chat ──Logos──▶ pvj-logos-link bridge (laptop) ──UDP 4855──▶ PVJ Pro (phone)
```

> **Status, 2026-11-17: sending from Basecamp doesn't work yet.** Every node that *sends* on
> `logos.test` needs an RLN membership: the RLN module exists only for macOS and Linux, and the
> membership costs about 250,000,000 testnet LEZ (no faucet). Basecamp on Windows logs "sent" but parks
> every message. The bridge → phone half works today (checked on a Pixel 8: tempo, mode, `next`, `prev`,
> `clip`, `text`; the rest reached the phone through the bridge's mock).
> See [Before you start](#before-you-start).

## Before you start

1. **The phone** runs PVJ **Pro** with OSC on (LIB ▸ OSC shows `UDP 4855 · <phone IP>`). The phone and
   the laptop are on the same Wi-Fi.
2. **The bridge** runs on the laptop: `run-pvj.bat` (Windows; it asks for the phone IP) or
   `python3 bridge/logos_bridge.py --mode pvj --pvj <phone IP> --confirm`. When its status turns
   **online** it shows its **Logos address** (also in `logos-address.txt`).
3. **The sender** needs an RLN membership (macOS or Linux, funded with testnet LEZ). Without one,
   messages never leave the sender.
4. **In Basecamp**: Chat ▸ **New chat** ▸ paste the bridge's Logos address ▸ send commands in that
   conversation. With `--confirm` the bridge answers each message with `ok: …` or the error (this also
   needs an RLN membership on the bridge's side).

## Commands

| Type this | What PVJ does | When |
|---|---|---|
| `bpm 128` | Tempo, 40–300 | at once |
| `slot 2` · `slot 4 b` | Load sequence slot 1–6 (lane `a` by default, or `b`) | next bar |
| `auto on` · `auto off b` | Sequencer auto-advance on/off (lane `a` or `b`) | next bar |
| `mode random` | Clip switching: `manual`, `sequential`, `random`, `lfo` | at once |
| `xfade 0.5` | Crossfader position, 0–1 | at once |
| `xfade beat` | Crossfader automation: `manual`, `beat`, `audio`, `lfo` | at once |
| `laneb on` · `laneb off` | Arm lane B | at once |
| `laneb clip` | Lane B source: `clip`, `net` (the other phone), `td` (TouchDesigner) | at once |
| `next` · `prev` | Next / previous clip, like the buttons (skips clips that can't play) | at once |
| `clip 3` | Jump to clip 3, the number PVJ shows (`CLIP 3/31`) | at once |
| `clip pvj_loop_07` | Jump to a clip by name (file name, with or without extension, any case) | at once |
| `text HELLO LOGOS` | **A message on screen.** Takes over the look: ASCII effect on, Custom mode, the picture drawn in the message's letters | at once |
| `ascii binary` | ASCII glyph style: `brightness`, `binary`, `random`, `custom` (doesn't turn the effect on) | at once |
| `help` | The bridge replies with the command list | — |

`on`/`off` also accept `1`/`0`, `yes`/`no`, `true`/`false`. Case doesn't matter.

### Examples

```
bpm 126; slot 2
mode random; xfade beat
next
clip 3
text HAPPY BIRTHDAY SAM
text WELCOME; ascii custom
laneb on; laneb clip; slot 3 b
```

### About `text`

- Up to 64 characters show. Letters A–Z and digits 0–9 appear; anything else (punctuation, emoji)
  becomes a gap. Lower case is shown as upper case.
- The message repeats across the picture, with a space between the copies. It's drawn only where the
  video is bright, so a dark clip shows fewer letters.
- It takes over on purpose (for audience messages). The performer gets their look back with one tap in
  the FX panel; the next message takes over again.

## Write the words, not the brackets

`<…>` in the bridge's help text marks a placeholder. Send `text HELLO`, not `text <hello>`, and
`ascii binary`, not `ascii <mode>`. A message that starts with anything other than a command, such as
`send bpm 128`, is refused as a whole: nothing in it is applied.

## What can't be controlled from chat

Masks and warp, effects other than ASCII, recording, the clip library, lane B's clip transport (`next`,
`prev` and `clip` drive the main deck only), and anything in PVJ's settings. The performer on the phone
always has the last word: every command goes through the same functions as the phone's buttons, so a tap
on the phone simply changes it back.

## Safety on a public screen

- **Lock it:** start the bridge with `--allow <your Logos address>` (comma-separated for several).
  Without it, anyone who has the bridge's address can drive the phone.
- Every message passes the bridge's filter first: `blocklist.txt` (one word or phrase per line),
  a 120-character cap (`--max-len`) and a short per-sender cooldown.

## Nothing happens?

| Symptom | Likely cause |
|---|---|
| Basecamp says sent, the phone doesn't change, no `ok:` reply | The sender has no RLN membership (always the case on Windows today). The bridge's log shows no incoming message |
| `ok:` arrives but the phone doesn't change | Wrong phone IP in `--pvj`, the phone on another network, or a non-Pro PVJ build |
| An error reply | A typo or a placeholder: see [Write the words, not the brackets](#write-the-words-not-the-brackets) |
| The slot changes a moment later | Expected: `slot` and `auto` wait for the next bar |
| Basecamp shows **Delivery error** | Basecamp's delivery module lost the network; check **Show logs**, then retry |
