# Studio 360 for Sirius — user guide

**Studio 360** — development kit *for Hengbot Sirius, an independent project*.

> **Independent project by explorations360 — not affiliated with, endorsed by,
> or supported by Hengbot.** Sirius and Hengbot are trademarks of their
> respective owners. This kit was reconstructed by reverse-engineering the
> robot's API; it is neither supplied nor approved by the manufacturer.

> ## ⚠️ Who this kit is for — read before you begin
>
> **This tool is for people who can code and know what they are doing.** It
> drives a real robot: motors that move, a machine that walks, stands up and
> can fall over. It has no parental safety rails, no authentication, and it
> exposes commands obtained by reverse-engineering that the manufacturer does
> not document.
>
> **Provided as is, with no support and no warranty of any kind.** Nobody
> undertakes to answer questions, fix defects, or keep compatibility with future
> firmware. Some commands are marked "to be confirmed": they may do nothing, or
> do something other than what you expect.
>
> **You alone are responsible for your robot, its surroundings and any damage.**
> Use it on flat, clear ground, staying within arm's reach, and do not run a
> command whose effect you do not understand. If these terms do not suit you, do
> not use it.


*The tool was called "Sirius Studio" up to v2.6; renamed at v2.7 so it would no
longer be confused with the manufacturer's official application. Already-released
archives keep their original filenames.*

**The interface installs on your phone (made functional in v2.8.1).** By default
the helper only listens on this PC; run **`demarrer_telephone.bat`** to make it
reachable over Wi-Fi. The window then shows the address to type into the phone's
browser (the "to open on the phone" line — same network as the PC). Open it, then
"Add to Home Screen": the app opens full-screen, with no address bar, and its own
icon. The five screens are usable at 390 px wide, and zoom stays active if you
need it.

⚠️ Phone mode makes robot control accessible to **anyone on the Wi-Fi, without a
password**: use it only on a trusted network. The cut-out stays active, and PC
mode (`demarrer.bat`) exposes nothing.

On iPhone, adding to the Home Screen is enough. On Android, Chrome reserves the
install prompt for secure addresses: the page remains perfectly usable, but
without one-click install — that is a browser constraint, not a kit one.

**The theme now follows the computer.** The button in the top bar cycles through
dark, light, then "system". In that last mode, the interface switches with the
machine's day/night setting, even while in use. The chosen theme is now applied
before the first render: no more light flash on load.

The version is shown in three places: in the black window at startup, on the
connection screen, and in the interface's top bar. It comes from the
`VERSION.txt` file — a single place to change, everything follows.

---

## Getting started

### With your robot

1. Power the robot on, check that it is on **the same Wi-Fi network** as your PC.
2. **Double-click `demarrer.bat`** — the browser opens by itself.
3. **Enter the robot's IP address in the interface**, then click "Connect".
   It is remembered: next time, a single click on the recent address is enough.

The robot's IP is shown on its screen, in the Network menu.

### Without a robot (discovery, demonstration)

**Double-click `demarrer_simulateur.bat`**, then connect to `127.0.0.1` in the
interface. A simulated robot answers, with data modelled on measurements from the
real one. Nothing can be damaged — ideal for showing off the tool.

### Wandering — the robot roams on its own

The **Wandering** tab shows what the robot perceives in front of it (its distance
sensor, sixteen zones in a 4×4 grid), what it infers from it, and lets you launch
it. But the avoidance itself runs **on board the robot**: the distance sensor
only exists on the embedded ROS, never on the network channel this kit speaks.
So you have to drop a file onto it, once:

```
scp deambulation.py root@<IP_DU_ROBOT>:/root/
ssh root@<IP_DU_ROBOT>
python3 /root/deambulation.py --service
```

The Wandering tab then comes alive. As long as this program is not running, it
shows "service unreachable" — that is normal, that is the only thing missing.

> ⚠️ **FLAT GROUND ONLY.** Never on a table, a worktop or a bed, never near a
> staircase, a step or an edge. The robot can see an obstacle in front of it, and
> *in principle* can see a drop — but **this drop detection has never been tested
> at the edge of a real height difference**: do not rely on it. It sees nothing
> behind it. Stay within arm's reach.
>
> On launch, **nothing moves**: the program observes and writes down what it
> would do. The robot only walks if you click **Start**. **Stop**, or the **Esc**
> and **Space** keys, halt it and reset the commands to zero.

### On the phone

**Double-click `demarrer_telephone.bat`** (instead of `demarrer.bat`). The window
shows an address of the form `http://192.168.x.x:8787`: type it into your phone's
browser, on the **same Wi-Fi** as the PC, then "Add to Home Screen" to install
it.

⚠️ This mode opens robot control to the whole Wi-Fi network, **without a
password** — trusted network only.

> The first use installs the Python dependencies (~30 s). After that, startup is
> immediate. Python must be installed — https://www.python.org/downloads/
> with **"Add Python to PATH"** ticked.

To stop everything: close the black window.

---

## ⚠️ The setting to know about: Ground or Desktop

The robot has two **environments**, and this is trap number one:

- **Desktop** — it restricts its gait and wide movements so it won't fall off a
  table. Result: **it moves its legs without going anywhere**.
- **Ground** — full gait, real travel.

Out of the box it is in **Desktop** mode. If your robot marches in place, it is
almost always this — not the battery, not the network. The setting is in
**Dashboard → Modes & behaviour → Environment**.

Another useful thing: the robot **falls asleep after a while of inactivity** and
crouches down. In that state, a walk command does nothing. Wake it up by playing
an action (for example "Standard standing posture") before driving it.

On the robot, this setting is also changed by a **vertical swipe on the head
screen**. The **Ground / Desktop** button in the interface does the same thing
remotely; the **Stand up** button plays the role of the wake-up.

---

## The interface

**Dashboard** — battery, motor temperatures, posture, emotion, ROS nodes, camera
view, quick control, favourite actions.

**Control** — two joysticks like on the Xbox controller: the left one for
translation, the right one for orientation. Mouse and touch. On the keyboard:
`W`/`S` forward-backward, `A`/`D` sideways, `Q`/`E` rotation, **`Space` = stop**.
Below: live telemetry and the API call log.

The **Posture** selector lies the robot down and stands it up. "Stand" replays
exactly the Reset button's action — the safe route, captured from the official
interface. "Down" looks for the matching action in your robot's library and shows
you the chosen name: check by eye that it is the right one the first time.

**Head** — a third joystick, separate, on the Control page. It is *sticky*: the
head keeps the direction you give it when you let go of the knob, which is the
useful behaviour for looking around with the camera. The **Recentre** button
brings it back to neutral. The range is limited to ±26° in yaw and ±20° in pitch,
below the robot's declared domain. This command is the only one in the kit not
yet confirmed on the hardware: if the head does not move, flip the selector to
**Body** and watch the robot's response in the API log — it will tell us which of
the two field names is the right one.

**Camera view** (on the Dashboard) — the video stream arrives live from the
robot, peer-to-peer. Over the image, the **detection boxes** and the **skeleton
points** are drawn in real time. Just below, the **Real-time tracking** panel
lists what the vision can recognise with, next to each name, the number of
objects currently tracked: `Corps (1)`, `Main (0)`… An unknown class that appears
adds itself to the list — this is how we will discover what the on-board model
can really detect.

**Actions** — the robot's library, filterable, with a French translation of the
names (the robot stores them in Chinese).

**System** *(new in v2.7)* — the diagnostics page, and the one that most frankly
says what the robot **does not measure**.

- *Vision* — the detection and face-tracking switches, and the real-time
  perception counters: `face`, `body`, `head`, the frame rate and the age of the
  last one.
- *Thermal* — the **battery temperature** is the only one the robot actually
  publishes, and it is shown. The **four leg probes are mute** on this firmware:
  they return 0, which is written on the screen rather than faked. The **CPU
  temperature is not available**, and the interface says why: it exists neither on
  the robot's WebSocket nor on its REST API; its only known source is an internal
  ROS topic (`/fan_breathing/cpu_temp`) that nothing relays to the web bridge. An
  honest dash is better than an invented number.
- *Motors* — the load of the 14 motors and the state of the cut-out.
- *Metrics* — CPU, disk, active ROS nodes, network, link freshness.

⏳ **Two switches on this page are not tested**, and the interface flags it: motor
**thermal protection** (`MOTOR_SET_THERMAL_PROTECTION`) and **face tracking**
(`VISION_SET_FACE_TRACKING`). Their wire name is certain, their effect is not —
and for the second, the `face_tracker` node **is not running** on this firmware:
the command will probably be accepted without anything moving. If you observe the
opposite on your machine, tell us: that is exactly what we are trying to find
out.

📌 This is face **detection** — knowing that a face is there and where it is. **No
identity-based facial recognition**: the robot does not know *who* is in front of
it, and nothing in its API allows it.

**Modes & behaviour** (on the Dashboard) — the Ground/Desktop environment,
autonomous mode, random actions, AI interaction and voice triggering. The
**autonomous mode** deserves attention: when it is active, the robot decides on
its own and can cancel your commands.

A **Stop** button stays accessible at all times in the top bar, next to the
**autonomous / manual** switch. Since v2.7, this switch really acts on the robot —
previously it sent its toggle to the display only.

---

## Safety

Three protections stack.

**The robot** itself clips joint angles and its workspace
(`joint_clamp_enabled`, `ws_clamp_enabled`) and detects angle jumps.

**The helper** refuses out-of-domain commands *before* sending them. Limits read
off the robot: forward 0.24 m/s, backward 0.16 m/s, sideways ±0.20 m/s, rotation
±1.2 rad/s, pitch and roll ±30°.

**The cut-out** watches the load of the 14 motors. Beyond **850 ‰ sustained for
0.8 s**, it stops the robot and locks the commands until rearmed from the
interface. Threshold calibrated on real measurements: normal operation tops out
at ~540 ‰ whatever the pace, a motor at a hard stop exceeds 950 ‰ in a
*sustained* way.

The stop is **verified**: the helper repeats the command until telemetry
confirms zero speed, and alerts if it does not.

### Best practices

Robot **on the ground**, clear space, kept an eye on during the first tries.
Disable **autonomous mode** during your tests (robot's official interface →
Inner World): otherwise it takes over and cancels your commands. Avoid very long
continuous sessions, the motors heat up.

---

## Folder contents

```
VERSION.txt                  the kit's version number
demarrer.bat                 launch with the robot
demarrer_simulateur.bat      launch without a robot
demarrer_telephone.bat       launch in network mode (phone access)
sirius_helper.py             the robot ↔ browser bridge (+ safety)
deambulation.html            the Wandering page, served on /deambulation
deambulation.py              the obstacle avoidance — to DROP ONTO THE ROBOT
                             (see "Wandering" above · flat ground)
mock_robot.py                the simulated robot
ui/                          the web interface
lire_limites_servos.sh       servo limit readout (advanced, SSH)
ecran_tete.sh                head-screen diagnostics (advanced, SSH)
```

---

## What's new in v2.8.5

- **LEDs — per-LED control.** Both ears are shown as clock dials (6 points each,
  1 = twelve o'clock, clockwise) and driven LED by LED, like the 6 back LEDs; an
  **Identify** mode lights one diode at a time. The 4 tail/junction lights are not
  colour-addressable — they are the battery gauge (from the official manual). The
  helper now drives 12 head channels instead of 2.
- **Mood plane fixed.** Valence / arousal / satiety are read on the robot's 0–100
  scale, so the marker reflects the real state (lying down = calm, at the bottom)
  instead of sticking to the top-right corner.
- **Robot life reorganised**: Audio volume and Head screen moved up; Recent
  interactions and AI dialogue grouped above the motor load.
- **Main interface**: a **Reset** button in the top bar, and **Recovery** fixed —
  it now triggers the robot's real get-up-after-a-fall routine (`/api/recovery`),
  distinct from simply standing back up.
- **Wandering**: a banner at the top of the page reminds that nothing works
  without the on-board service (launched over SSH / by `deambulation_robot.bat`),
  linking to the wiki; and **stronger drop anticipation** (node v16) — it stops
  advancing the instant a drop is suspected, and a single fully-lost floor zone now
  triggers, to catch diagonal approaches. ⚠ This reduces the risk, it does not make
  a table safe: stay within arm's reach.

## What's new in v2.8.4

**The new tools are tabs of the main interface** — nothing else to open. Menu
order: Dashboard · System · Robot life · Actions · Sequences · Control ·
Wandering.

- **Robot life** — dashboard: the robot's mood (pleasure, arousal, satiety,
  fatigue), **audio volume**, **LEDs** (2 on the head, 6 on the body), **head
  screen** (text message and animations from its library), battery, network, load
  of the 14 motors, touch interactions, logs, reset of the AI dialogue memory.
- **Sequences** — "Play Blocks" editor: animations, random-draw groups, pauses
  and wandering blocks placed end to end, looping or not; save to the PC,
  JSON export/import.
- **Wandering** — redesigned in three columns (see / measure / act), with
  **step-by-step walking** (movements bounded in strides), a **Wake / Stand up**
  button and camera on demand.
- **`deambulation_robot.bat`** — drops the node onto the robot and launches its
  service with the right ROS environment, in one double-click.
- Fixes: end of the left bias in avoidance, reversing on drop detection now
  bounded, the head's "Recentre" button that really commands the robot, and
  removal of a polling loop that was saturating the bridge.

⚠️ **The interface (`ui/`) is a hand-patched build** to add these tabs and two
fixes. A future rebuild of the frontend from source would overwrite these
changes: they would have to be reapplied.


This version adds several modules, all linked by a **common navigation** at the
top of each page. Entry point: **`/accueil`** (opens from any page via the "Home"
menu).

- **Home** (`/accueil`) — a hub with one tile per module.
- **Sequences** (`/enchainements`) — "Play Blocks" editor: you place animations,
  groups (random draw), pauses and "auto-wander" blocks one after another, then
  launch the cycle (looping or stopping at the end of the cycle). Sequences are
  saved to the PC (via the helper) with a browser fallback and JSON export/import.
- **Eyes** (`/yeux`) — gaze controller (direction, dilation, rotation, blink) and
  preset expressions, with on-screen preview. UDP channel 8770. ⚠ effect on the
  robot's screen not yet tested.
- **Life & System** (`/tableau`) — dashboard: mood (valence/arousal/satiety/
  fatigue), **audio volume**, battery, network, load per motor (14), touch
  interactions, logs, reset of the dialogue memory.
- **Wandering** — two additions: a **Wake / Stand up** button (wakes and freezes
  the robot standing: ground mode + autonomous paused + hold upright — useful at
  first startup), and **step-by-step walking** (movements bounded in strides).
- **Audio volume** — adjustable from 0 to 100 (`audio_volume` parameter of the
  `wmix_audio_player_node` node, command verified on the official interface).
- Wandering node fixes (v15): end of the left bias in avoidance, reversing
  triggered by a drop now bounded, and optional animation played when approaching
  an obstacle before reversing.

## Troubleshooting

**"Cannot reach the robot"** — check the IP, and that the robot and PC are on the
same network.

**The browser does not open** — go to http://127.0.0.1:8787

**"Python not found"** — install Python with "Add Python to PATH" ticked.

**It moves its legs but does not advance** — two possible causes: it is in
**Desktop** mode (switch to **Ground** in Modes & behaviour), or the requested
speed is too low. Raise the speed slider: at 0.24 m/s the robot walks at full
amplitude.

**It does not react at all** — either it is asleep (play an action to wake it
up), or **autonomous mode** is active and cancelling your commands (turn it off
in Modes & behaviour).

**Seeing what's happening** — the helper's API is documented and testable at
http://127.0.0.1:8787/docs
