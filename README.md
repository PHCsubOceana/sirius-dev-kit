# Sirius Dev Kit

Developer documentation and a browser-based control tool for the **Hengbot
Sirius** robot dog — reconstructed by measurement on a real machine, because the
manufacturer's documentation stops at motion and its spec sheet lists **no
sensors at all**.

Everything here was verified against a physical robot. Where it wasn't, it says so.

> **Independent project by explorations360 — not affiliated with, endorsed by,
> or supported by Hengbot.** Sirius and Hengbot are trademarks of their
> respective owners. This kit was reconstructed by reverse-engineering the
> robot's API; it is neither supplied nor approved by the manufacturer.

🇫🇷 [Version française](README.fr.md) · Full technical reference:
[`docs/sirius-api-fr.md`](docs/sirius-api-fr.md) (French)

---

## Start here: the five traps

If your Sirius acknowledges your commands and does nothing useful, the answer is
almost certainly one of these. All five produce the *same* symptom — a robot that
replies, echoes back the value you sent, and marches in place.

**1. Speed is normalised, not m/s.** `linear_x`, `linear_y`, `angular_z` expect a
value in `[-1, 1]` — a fraction of full travel. Sending `0.15` asks for 15 % of
maximum, not 0.15 m/s: the stride collapses and the robot walks on the spot. The
official docs do state this for the `Control_Move` API — but the same convention
silently applies to `gait_control` on the WebSocket and to the ROS topic
`/gait_generation_trot/cmd_vel`, where nothing warns you. Proof: commanding
`vx = 0.50` comes back as `0.500` on `filtered_velocity`, which exceeds the
robot's own declared maximum, so it cannot be metres per second.

**2. The robot ships in `desktop` mode**, which deliberately restricts gait so it
won't walk off a table. `USER_SET_ROBOT_MODE {"robot_mode":"ground"}` releases it.

**3. Action priority.** An `ACTION_PLAY` sent at priority 1 (the default) is
overridden by the running autonomous behaviour. Use **priority 5**.

**4. Command names are UPPERCASE on the wire.** `BEHAVIOR_SET_PAUSE`, not
`set_behavior_pause` — the lowercase names you find in the binaries are internal
handlers. Five exceptions exist only in lowercase, and they are precisely the ones
that make the robot move: `gait_control`, `gait_step_move`, `attitude_control`,
`self_recover`, `set_motion_mode`.

**5. No ROS nodes visible?** You're missing the DDS environment. Without
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `ros2 node list` returns nothing while
the robot runs perfectly.

---

## What's undocumented, and what we measured

The manufacturer documents an app, a Python API and a keyframe WebSocket API.
It documents **no sensor reading of any kind** — the Specifications section lists
no ToF, no IMU, not even the camera. There is no mention of ROS 2, although an
EDU edition is sold on that argument.

Measured on the machine:

| | |
|---|---|
| **ToF distance sensor** | `/state_sensor/tof/distance_array`, `state_sensor_tof/msg/ToFDistanceArray`. **Millimetres**, range 11–2047 (2047 = no target), ~38 Hz, 16 zones in a 4×4 grid |
| **Grid origin** | **bottom-left** — channel 1 is bottom-left, 16 is top-right. Reading it like an image flips the field vertically and turns the floor into the sky |
| **Sensor location** | **under the neck, high on the chest — body-mounted, not in the head.** Tilting the head 17° moves the readings by 1–2 mm. So ToF geometry depends only on body attitude, and the head is free to look elsewhere |
| **Self-occlusion** | It sees its **own front legs** at the bottom of the field (a hand in front drops the bottom row by only 18 %, versus 80 % for the top rows) and its **own jaw** at the top — a phantom obstacle at 191 mm, σ = 5 mm across ten sessions |
| **Free-fall detection, for free** | The bottom rows see the floor at ~20 and ~30 cm. When the floor disappears — table edge, stair — they saturate to 2047. ⚠️ **Never yet tested on a real edge.** Do not treat it as a working safety feature |
| **Head control** | `/kinematics/ik_subscriber/head_euler_follow` (`geometry_msgs/Point`), **radians**: `x` = pitch, `y` = yaw, `z` no effect. Stay under 0.35 rad. No angle readback exists |
| **IMU** | `/state_sensor/imu_onbody/imu_publisher/imu_data` and `…/imu_angle` — readable, and absent from the spec sheet |
| **Motor load** | `motor-load`, 14 motors, ±1000 ‰ of PWM. Normal peak ~540 ‰ at any speed; a stalled motor sustains 950–985 ‰. **The discriminant is duration, not amplitude** |
| **Camera** | Works over WebRTC, signalling on port **8766** (not 8765) — while the official app documentation says head image transmission is "not available, please wait" |
| **Three contradictory top speeds** | Spec sheet 0.4 m/s · WebSocket API docs 0.28 m/s · `ros2 param dump` on the machine 0.24 m/s. The last one governs actual behaviour |

Full detail, including the 59-command protocol and the complete ROS inventory
(29 distinct nodes, ~130 topics), is in [`docs/`](docs/).

---

## The control tool

`tool/` is **Studio 360 for Sirius** — **Studio 360** for short:
a local Python bridge (FastAPI) that speaks WebSocket to the robot and serves a
React interface to your browser. Video goes
**straight from robot to browser** over WebRTC — a backend can relay the
signalling, never the stream.

Two joysticks for walking and turning, a third for the head, live camera with
detection overlays, the robot's action library with its Chinese names translated,
14-motor telemetry, an API call log, the Ground/Desktop switch, and a **cut-out
that stops the robot beyond 850 ‰ of motor load sustained for 0.8 s**.

The interface is **bilingual English / French** — an EN / FR button sits in the
top bar.

> **A note on the name.** The tool was called *Sirius Studio* up to and
> including v2.6, which was too easily confused with Hengbot's own official
> application. From **v2.7** onwards it is **Studio 360 for
> Sirius** (*Studio 360*). Already-released archives keep their original
> filenames — `SiriusStudio_v1.9` through `SiriusStudio_v2.6` — so no existing
> download link breaks. Script filenames, bridge routes and wire commands are
> unchanged.

### Running it

Windows, Python 3 installed with **"Add Python to PATH"** ticked:

```
1. Power the robot on, same Wi-Fi network as your PC.
   Its IP address is shown on the head screen, Network menu.
2. Double-click tool/demarrer.bat — your browser opens on http://127.0.0.1:8787
3. Type the robot's IP in the interface and click Connect.
```

First run installs `fastapi`, `uvicorn`, `websockets` and `httpx`, once, in about
thirty seconds.

**No robot?** Double-click `tool/demarrer_simulateur.bat` and connect to
`127.0.0.1`. A simulated robot answers, speaking the **real protocol**, with data
modelled on measurements taken from the physical machine. Nothing can be damaged —
it is also the fastest way to see what the protocol looks like.

The launchers are Windows `.bat` files; the Python bridge itself is
platform-independent but has not been tested elsewhere.

### ⚠️ Before you move anything

**On the floor, never on a table.** Nothing in this robot detects a drop, and our
free-fall detection has never been tested on a real edge. Clear two metres in
front. **Turn autonomous mode off** or the on-board behaviour will override your
commands. The robot **cannot see behind it** — every reverse move is blind. Keep a
way to stop it within reach *before* you start.

This kit is provided as is, with no warranty. It drives hardware that can fall
over or jam a joint.

---

## How to read the claims

Every statement in these documents belongs to one of four states, and
[`docs/data.json`](docs/data.json) carries the state for each individual value:

**verified** — measured on the robot · **documented** — written by the
manufacturer · **deduced** — inferred from firmware or behaviour, never confirmed
· **to be confirmed** — a working hypothesis, not a fact.

The firmware this was measured on is **2.5.0 beta**, installed 2026-07-23 —
read off the robot's own System Update Center, which reports *System is up to
date*. The manufacturer runs two channels, RELEASE (3 stable versions) and BETA
(8 test versions).

**Where to find release notes.** Hengbot keeps a detailed, per-version changelog —
but only *inside* the System Update page of its console, reachable once you
connect a robot. Nothing is published on the web and no search engine indexes it,
which is why you won't find it by looking. A French summary of all eleven entries
is in [`docs/firmware-changelog-fr.md`](docs/firmware-changelog-fr.md); it answers
several questions the official documentation leaves open, including what the
head-screen swipe actually does (it unlocks the screen and wakes the robot — it
does **not** change the robot mode).

And a warning: the source package `sirius_full_v2.3.6` shipped with the OTA tools
is **older than the installed firmware**, and its node names no longer match. The
2.5.0 release note says why, in the vendor's own words: behavior and emotion nodes
were removed and merged into a single behavior-tree driver node. Trust what
answers on the machine.

---

## Credits

Independent prior work by [**dspeers**](https://github.com/dspeers) —
[`sirius-control-panel`](https://github.com/dspeers/sirius-control-panel) and
[`sirius-voice-bridge`](https://github.com/dspeers/sirius-voice-bridge). The REST
port `:8088` and the MJPEG stream on `:8080` were found independently on both
sides; **he published them first**.

Official manufacturer documentation:
[hengbot-dynamics.github.io/heng-docs](https://hengbot-dynamics.github.io/heng-docs/docs/intro).

Built by [explorations360](https://explorations360.com) — the long-form write-up
lives at [explorations360.com/sirius](https://explorations360.com/sirius).

Corrections welcome. If you verify one of the points marked uncertain — the
gesture topic, the free-fall detection on a real edge, the head-screen Developer
Mode — please open an issue.

Licensed under the **Apache License 2.0** — see [LICENSE](LICENSE) and
[NOTICE](NOTICE).

The `NOTICE` file states two things that matter here: this project is neither
affiliated with nor endorsed by Hengbot, and the licence grants no rights over
their trademarks (section 6 of the licence); and the protocol documentation was
established by observing a lawfully acquired robot — network traffic, ROS
inventory, readable files present on the machine — with no decompilation or
disassembly, and without reproducing a single line of the manufacturer's code.
