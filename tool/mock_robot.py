#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mock_robot.py — Simulateur fidèle du Hengbot Sirius
====================================================
Livré avec Studio 360 pour Sirius (« Studio 360 »).

⚠️ PROJET INDÉPENDANT, SANS LIEN AVEC HENGBOT : ce simulateur est issu d'un
travail de reverse engineering d'explorations360. L'application officielle du
robot est celle de Hengbot, ce kit n'en fait pas partie.

Reproduit le protocole RÉEL du robot, tel que relevé en direct sur
192.168.1.42 (firmware v2.3.6) : « Sirius Core API » v4.0.0.
(Ce nom-là est celui du ROBOT, pas le nôtre : on le laisse intact, sinon le
simulateur cesserait d'être fidèle.)

Pourquoi c'est utile : tout code écrit contre ce simulateur (helper local,
front-end Studio 360) fonctionne **tel quel** sur le vrai robot. Il suffit
de changer l'URL. On peut donc développer sans robot, et sans risque.

    pip install websockets
    python3 mock_robot.py
    →  ws://127.0.0.1:8765     (au lieu de ws://<IP_ROBOT>:8765)

Protocole reproduit
-------------------
• Événements poussés (robot → client) :
    {"type":"event","event_type":"…","timestamp":"ISO","data":{…}}
  types : connection_info, gait-trajectory (10 Hz), battery-status,
          motor-load, motor-temperature, emotion-update, behavior-status,
          system_metrics, lifecycle_update, network-status, hotspot-status

• Requêtes (client → robot) :
    {"type":"request","request_type":"…","request_id":"…","data":{…}}
  réponse :
    {"type":"response","request_id":"…","success":bool,"code":"ok|not_found|
      invalid_request","data":{…},"error":"…","message":"…","timestamp":"ISO"}

  request_type vérifiés sur le vrai robot :
    get_status · get_actions · get_lifecycle_states · get_system_time · get_chrony_status

⚠️ Les commandes de mouvement (play_motion / gait_control / force_reset) sont
   ici **simulées mais pas encore vérifiées sur le robot** — leurs noms sont
   déduits du firmware. Elles sont marquées UNVERIFIED dans les réponses pour
   qu'on ne les prenne pas pour argent comptant.

SÉCURITÉ — le simulateur reproduit aussi le comportement de charge moteur, et
inclut un scénario de blocage (`--stall`) pour tester le coupe-circuit du helper
sans jamais risquer le vrai matériel.

SONDES DE TEMPÉRATURE MOTEUR — `--motor-temps`
----------------------------------------------
Sur le firmware réel, les quatre sondes de patte renvoient **0** : elles sont
muettes, et 0 ne signifie pas « 0 °C » mais « pas de mesure ». C'est le
comportement PAR DÉFAUT du simulateur, parce que reproduire la réalité est plus
utile que reproduire ce qu'on aimerait avoir.

    python3 mock_robot.py                        # sondes muettes (0) — cas réel
    python3 mock_robot.py --motor-temps parlantes  # 28-45 °C plausibles

Le second mode n'existe que pour démontrer l'affichage nominal de l'interface
(et vérifier qu'elle sait afficher autre chose que « sonde muette »). Ne pas
s'en servir pour conclure quoi que ce soit sur le vrai robot.

VISION — `vision-detection`
---------------------------
Quand `VISION_SET_DETECTION` est actif, le simulateur pousse des trames de
détection plausibles (classes body / head / face, rectangles cohérents dans le
repère 640 × 360 du modèle), afin que les compteurs vision et l'onglet Système
soient démontrables sans robot.
"""

import argparse, asyncio, json, math, random, time
from datetime import datetime, timezone
from pathlib import Path

import websockets

PORT = 8765

# ─────────────────────── constantes relevées sur le robot ───────────────────────
N_MOTORS = 14                      # SetMotorTorque : indices 0-13
LOAD_RANGE = {"min": -1000, "max": 1000}   # unit: pwm_permille
IDLE_LOADS = [32, 37, -15, -22, -27, -12, -57, 5, 2, 47, 3, 7, -15, -87]  # relevé réel au repos

# Seuils de sécurité proposés pour le helper (voir §Sécurité du doc API)
SAFETY_LOAD_THRESHOLD = 700        # pour-mille
SAFETY_SUSTAIN_S = 0.5             # durée au-delà de laquelle on coupe

ACTIONS = [
    {"id": "stand_default_idle", "name": "stand_default_idle", "display_name": "标准站姿",
     "description": "", "file": "stand_default_idle.avi", "filename": "stand_default_idle.avi",
     "full_path": "/root/material/actions/stand_default_idle.avi",
     "category": "IDLE", "is_official": True, "size_kb": 198.1, "torque": 400},
    {"id": "stand_default_returnPosition_brief", "name": "stand_default_returnPosition_brief",
     "display_name": "回位", "description": "Retour en posture debout (action du bouton Reset)",
     "file": "stand_default_returnPosition_brief.avi",
     "filename": "stand_default_returnPosition_brief.avi",
     "full_path": "/root/material/actions/stand_default_returnPosition_brief.avi",
     "category": "IDLE", "is_official": True, "size_kb": 176.5, "torque": 2047},
    {"id": "stand_default_peer_brief", "name": "stand_default_peer_brief", "display_name": "好奇眯眼",
     "description": "身体微微前伸，眼睛眯眼", "file": "stand_default_peer_brief.avi",
     "filename": "stand_default_peer_brief.avi",
     "full_path": "/root/material/actions/stand_default_peer_brief.avi",
     "category": "NORMAL", "is_official": True, "size_kb": 210.4, "torque": 2047},
    {"id": "stand_default_ponder_brief", "name": "stand_default_ponder_brief", "display_name": "好奇思考",
     "description": "身体微微倾斜，停留1s后恢复", "file": "stand_default_ponder_brief.avi",
     "filename": "stand_default_ponder_brief.avi",
     "full_path": "/root/material/actions/stand_default_ponder_brief.avi",
     "category": "NORMAL", "is_official": True, "size_kb": 233.8, "torque": 2047},
    {"id": "stand_default_lie_down", "name": "stand_default_lie_down", "display_name": "趴下",
     "description": "Se coucher au sol", "file": "stand_default_lie_down.avi",
     "filename": "stand_default_lie_down.avi",
     "full_path": "/root/material/actions/stand_default_lie_down.avi",
     "category": "IDLE", "is_official": True, "size_kb": 189.7, "torque": 2047},
    {"id": "stand_excited_happy-tail_brief", "name": "stand_excited_happy-tail_brief",
     "display_name": "开心摇尾", "description": "", "file": "stand_excited_happy-tail_brief.avi",
     "filename": "stand_excited_happy-tail_brief.avi",
     "full_path": "/root/material/actions/stand_excited_happy-tail_brief.avi",
     "category": "EXCITED", "is_official": True, "size_kb": 301.2, "torque": 2047},
]

ROS_NODES = ["ai_interaction_node", "behavior_engine_node", "camera_publisher_node",
             "character_state_node", "emotion_manager", "gait_generation_trot_node",
             "ik_subscriber", "lvgl_gui_node", "modbus_driver", "web_bridge_node",
             "action_player_node", "robot_led_controller_node", "fall_detector",
             "face_tracking", "yolov5_face_detector"]


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class Sim:
    """État simulé du robot, fidèle aux grandeurs et unités réelles."""

    def __init__(self, stall=False, motor_temps="muettes"):
        self.t0 = time.time()
        self.clients = {}
        self.next_id = 1
        # batterie : le robot renvoie un RATIO 0-1, pas un pourcentage
        self.percentage = 0.94
        self.voltage = 8.081
        self.current = -1.54
        self.batt_temp = 30.1
        self.vx = self.vy = self.wz = 0.0
        self.is_playing = False
        self.playing_file = ""
        self.emotion = "sleepy"
        self.valence, self.arousal, self.satiety = 50.0, 13.8, 98.0
        self.motor_temps = [28.0, 28.0, 28.0, 28.0]
        self.loads = list(IDLE_LOADS)
        self.phase_pas = 0.0        # phase de la cadence de marche
        self.robot_mode = 'desktop'  # comme le robot réel à la sortie d'usine
        self.attitude = {"head_yaw": 0.0, "head_pitch": 0.0}
        # VISION_SET_DETECTION ouvre d'un seul geste la vidéo ET la sortie du
        # modèle de perception : un seul drapeau, comme sur le vrai robot.
        self.camera = False
        self.face_tracking = False       # ⏳ commande non vérifiée (cf. handle_request)
        self.thermal_protection = True   # ⏳ idem ; supposée armée d'usine
        self.pending_welcome = False
        # "muettes" (défaut, cas réel : les 4 sondes renvoient 0) | "parlantes"
        self.motor_temps_mode = motor_temps
        self.phase_vis = 0.0             # phase du déplacement de la personne simulée
        self.paused = True
        self.stall = stall          # scénario de blocage pour tester le coupe-circuit
        self.stall_since = None
        # comportement autonome : le vrai robot joue des actions tout seul.
        # On le simule pour vérifier que le pont suit la posture SANS clic.
        self.auto_posture = 0.0     # période en s (0 = désactivé), fixée par --auto-posture
        self.prochaine_auto = 0.0
        self.derniere_auto = "stand_default_returnPosition_brief"

    # ---------------- comportement autonome ----------------
    ACTIONS_POSTURE = ("stand_default_lie_down", "stand_default_returnPosition_brief")

    def comportement_autonome(self, now):
        """Joue seul, de temps en temps, une action qui CHANGE la posture.

        C'est ce que fait le robot réel quand le mode autonome est actif : il se
        couche ou se relève sans que personne n'ait cliqué. Le pont doit s'en
        apercevoir via `behavior-status` puis `get_status`.
        """
        if self.auto_posture <= 0 or self.is_playing or now < self.prochaine_auto:
            return None
        a, b = self.ACTIONS_POSTURE
        self.derniere_auto = b if self.derniere_auto == a else a
        self.is_playing = True
        self.playing_file = f"/root/material/actions/{self.derniere_auto}.avi"
        self.prochaine_auto = now + self.auto_posture

        def _fin():
            self.is_playing = False
            self.playing_file = ""
        asyncio.get_event_loop().call_later(3.0, _fin)
        return self.derniere_auto

    # ---------------- physique très simplifiée ----------------
    def step(self, dt):
        load_factor = abs(self.vx) + abs(self.vy) + abs(self.wz)

        # décharge : ~0.4 %/min au repos, davantage en mouvement
        self.percentage = max(0.0, self.percentage - dt * (0.00007 + load_factor * 0.0004))
        self.voltage = 6.6 + 1.9 * self.percentage + random.uniform(-0.01, 0.01)
        self.current = -1.5 - load_factor * 3.0 + random.uniform(-0.05, 0.05)

        # charge moteur : bruit au repos, pics proportionnels au mouvement
        base = IDLE_LOADS
        if self.stall:
            # blocage franc : plateau élevé et SOUTENU (signature d'une butée)
            self.loads = [int(min(1000, abs(b) + 880 + random.uniform(-25, 25))) * (1 if b >= 0 else -1)
                          for b in base]
            if self.stall_since is None:
                self.stall_since = time.time()
        else:
            self.stall_since = None
            # Modèle recalé sur les mesures du robot réel (25/07) :
            #   repos ............ pic 120 – 162 ‰
            #   en mouvement ..... pic ~490 – 540 ‰, moyenne ~265 – 344 ‰
            # Point clé : le pic NE dépend PAS de la vitesse — il est imposé par
            # la cadence du pas (impulsions de levée/pose). On module donc par une
            # phase de marche, pas par load_factor.
            if load_factor > 0.001:
                self.phase_pas = (self.phase_pas + dt * 5.0) % (2 * math.pi)
                cadence = abs(math.sin(self.phase_pas))          # 0 → 1 sur un pas
                pic_vise = 300.0 + 240.0 * cadence               # 300 → 540 ‰
            else:
                pic_vise = 140.0 + random.uniform(-20, 25)       # repos
            echelle = pic_vise / max(1, max(abs(b) for b in base))
            self.loads = [int(max(-1000, min(1000, b * echelle + random.uniform(-12, 12)))) for b in base]

        # Température moteurs : monte avec la charge, se dissipe au repos.
        # Plage visée 28 → 45 °C, ce qu'on mesurerait sur des sondes qui
        # fonctionnent. Ce modèle ne sert QU'AU mode `--motor-temps parlantes` :
        # par défaut l'événement publie 0, comme le vrai firmware.
        peak = max(abs(v) for v in self.loads) / 1000.0
        for i in range(4):
            target = 28.0 + peak * 17.0
            self.motor_temps[i] += (target - self.motor_temps[i]) * dt * 0.08 + random.uniform(-.02, .02)

        # émotion : dérive lente
        self.arousal = max(0.0, min(100.0, self.arousal + random.uniform(-.3, .3) + load_factor * 2))
        self.satiety = max(0.0, self.satiety - dt * 0.0008)

    # ---------------- construction des événements ----------------
    def ev(self, event_type, data):
        return json.dumps({"type": "event", "event_type": event_type,
                           "timestamp": now_iso(), "data": data})

    def vision_event(self):
        """Détections simulées : une personne qui traverse lentement le champ.

        Fidélité au vrai robot (§9 bis de la doc API) :
        • coordonnées dans le repère **640 × 360 du modèle**, pas celui de la
          vidéo affichée — c'est au front de remettre à l'échelle ;
        • classes observées à ce jour : body, head, face ;
        • `track_id` constant d'une trame à l'autre : c'est du SUIVI, pas de la
          détection image par image.

        Le visage n'est publié QUE lorsque la personne est à peu près face à la
        caméra (proche du centre) : le vrai détecteur perd le visage de profil.
        Effet utile ici : les compteurs par classe VARIENT, on voit donc tout de
        suite si l'interface les met à jour ou si elle affiche une valeur figée.
        """
        self.phase_vis = (self.phase_vis + 0.02) % (2 * math.pi)
        cx = 320 + 150 * math.sin(self.phase_vis)
        dets = [
            {"class_id": 0, "class_name": "body", "type": "body", "confidence": 0.98,
             "rect": {"x": int(cx - 63), "y": 20, "width": 126, "height": 192}},
            {"class_id": 1, "class_name": "head", "type": "head", "confidence": 0.95,
             "rect": {"x": int(cx - 19), "y": 12, "width": 38, "height": 44}},
        ]
        if abs(cx - 320) < 95:                       # de face → le visage est vu
            dets.append({"class_id": 2, "class_name": "face", "type": "face",
                         "confidence": 0.91,
                         "rect": {"x": int(cx - 14), "y": 18, "width": 28, "height": 34}})
        pts = [{"x": int(cx + random.uniform(-40, 40)),
                "y": int(60 + i * 12), "score": round(random.uniform(0.5, 0.95), 3)}
               for i in range(14)]
        return self.ev("vision-detection", {
            "detections": dets, "skeletons": [{"track_id": 1, "type": "body", "points": pts}],
            "image_width": 640, "image_height": 360})

    def gait_event(self):
        return self.ev("gait-trajectory", {"filtered_velocity": {
            "linear_x": round(self.vx, 4), "linear_y": round(self.vy, 4),
            "angular_z": round(self.wz, 4)}})

    def battery_event(self):
        return self.ev("battery-status", {
            "capacity": 2.25, "charge": round(2.25 * self.percentage, 4),
            "current": round(self.current, 4), "location": "onbody",
            "percentage": round(self.percentage, 6),        # ← RATIO 0-1
            "power_supply_health": 1, "power_supply_status": 2,
            "temperature": round(self.batt_temp, 2),
            "timestamp": int((time.time() - self.t0) * 1000),
            "voltage": round(self.voltage, 4)})

    def motor_load_event(self):
        return self.ev("motor-load", {"loads": self.loads, "range": LOAD_RANGE,
                                      "timestamp": int(time.time() * 1000),
                                      "unit": "pwm_permille"})

    def motor_temp_event(self):
        """Températures des 4 pattes.

        PAR DÉFAUT : quatre zéros. C'est ce que renvoie le vrai firmware — les
        sondes sont muettes. On le reproduit tel quel plutôt que d'inventer des
        valeurs, sinon l'interface serait développée contre une donnée qui
        n'existe pas, et le problème n'apparaîtrait que devant le robot.
        Le mode « parlantes » (--motor-temps) publie le modèle thermique simulé,
        uniquement pour démontrer l'affichage nominal.
        """
        if self.motor_temps_mode == "parlantes":
            t = [round(v, 1) for v in self.motor_temps]
        else:
            t = [0, 0, 0, 0]
        return self.ev("motor-temperature", {
            "front_left": t[0], "front_right": t[1],
            "back_left": t[2], "back_right": t[3],
            "timestamp": int(time.time() * 1000), "unit": "celsius"})

    def emotion_event(self):
        return self.ev("emotion-update", {
            "arousal_value": round(self.arousal, 4), "emotion_state": self.emotion,
            "fatigue_status": 0, "satiety_value": round(self.satiety, 4),
            "timestamp": int(time.time() * 1000), "toilet_desire": 0,
            "valence_value": round(self.valence, 4)})

    def behavior_event(self):
        return self.ev("behavior-status", {"engine": {
            "active_tree": "", "admission": {"blocked": False, "sources": ""},
            "idle": "stand_default_idle", "intent": "", "last_result": {},
            "recent_events": [{"age_s": int(time.time() - self.t0), "source": "sim", "type": "touch_tap"}],
            "running": self.is_playing}})

    def system_event(self):
        return self.ev("system_metrics", {
            "core_count": 4, "cpu_percent": round(40 + random.uniform(0, 25), 4),
            "load_avg": [round(random.uniform(2, 7), 2) for _ in range(3)],
            "disk": {"total": 28.64, "used": 8.82, "free": 19.82, "percent": 30.8}})

    def network_event(self):
        return self.ev("network-status", {
            "error_message": "", "ip_address": "127.0.0.1", "is_connected": True,
            "mac_address": "c0:4b:24:73:4a:07", "security_type": "WPA2",
            "signal_strength": 55, "ssid": "SIMULATEUR", "status": 2})

    def lifecycle_event(self):
        return self.ev("lifecycle_update", {"nodes": [
            {"available": True, "name": n, "state": "active"} for n in ROS_NODES]})


# ─────────────────────── requêtes ───────────────────────
def make_response(rid, success, code, data=None, error=""):
    return json.dumps({"type": "response", "request_id": rid or "", "success": success,
                       "code": code, "data": data or {}, "error": error,
                       "message": error, "timestamp": now_iso()})


def handle_request(sim: Sim, msg: dict) -> str:
    rid = msg.get("request_id", "")

    # mêmes contrôles que le vrai robot, dans le même ordre
    if msg.get("type") != "request":
        return make_response(rid, False, "invalid_request", error="Missing or invalid 'type' field")
    rt = msg.get("request_type")
    if not rt:
        return make_response(rid, False, "invalid_request", error="Missing 'request_type' field")

    # ── lectures VÉRIFIÉES sur le vrai robot ──
    if rt == "get_status":
        return make_response(rid, True, "ok", {
            "status": "playing" if sim.is_playing else "idle",
            "is_playing": sim.is_playing, "file_path": sim.playing_file})

    if rt == "get_actions":
        return make_response(rid, True, "ok",
                             {"action_base_path": "/root/material/actions", "actions": ACTIONS})

    if rt == "get_lifecycle_states":
        return make_response(rid, True, "ok", {"nodes": [
            {"available": True, "name": n, "state": "active"} for n in ROS_NODES]})

    if rt == "get_system_time":
        return make_response(rid, True, "ok",
                             {"system_time_ms": int(time.time() * 1000), "timezone": "Asia/Shanghai"})

    if rt == "get_chrony_status":
        return make_response(rid, True, "ok", {
            "last_offset_ms": 0.163744, "leap_status": "Normal",
            "reference_id": "time.cloudflare.com", "rms_offset_ms": 1.343196, "stratum": 3})

    # ── commandes NON ENCORE VÉRIFIÉES sur le robot (noms déduits du firmware) ──
    if rt == "play_motion":
        d = msg.get("data") or {}
        name = d.get("action_name") or d.get("name") or ""
        if not name and d.get("file_path"):
            name = d["file_path"].rsplit("/", 1)[-1].replace(".avi", "")
        if not any(a["name"] == name for a in ACTIONS):
            return make_response(rid, False, "not_found", error=f"Unknown action: {name}")
        sim.is_playing = True
        sim.playing_file = f"/root/material/actions/{name}.avi"
        asyncio.get_event_loop().call_later(3.0, lambda: (setattr(sim, "is_playing", False),
                                                          setattr(sim, "playing_file", "")))
        return make_response(rid, True, "ok", {
            "file_path": sim.playing_file, "loop": bool(d.get("loop", False)),
            "priority": d.get("priority", 1), "status": "sending",
            "torque": d.get("torque", 2047)})

    if rt == "cancel_motion":
        sim.is_playing, sim.playing_file = False, ""
        return make_response(rid, True, "ok", {"status": "canceled"})

    if rt == "gait_control":
        d = msg.get("data") or {}
        sim.vx = float(d.get("linear_x", d.get("vx", 0.0)))
        sim.vy = float(d.get("linear_y", d.get("vy", 0.0)))
        sim.wz = float(d.get("angular_z", d.get("wz", 0.0)))
        return make_response(rid, True, "ok",
                             {"linear_x": sim.vx, "linear_y": sim.vy, "angular_z": sim.wz})

    if rt in ("stop_all_motions",):
        sim.vx = sim.vy = sim.wz = 0.0
        sim.is_playing, sim.playing_file = False, ""
        return make_response(rid, True, "ok", {"status": "canceled"})

    # ── modes (protocole en MAJUSCULES, comme le vrai robot) ──
    if rt == "USER_GET_ROBOT_MODE":
        return make_response(rid, True, "ok", {"robot_mode": sim.robot_mode})
    if rt == "USER_SET_ROBOT_MODE":
        m = (msg.get("data") or {}).get("robot_mode")
        if m not in ("ground", "desktop"):
            return make_response(rid, False, "invalid_argument", error=f"Unknown mode: {m}")
        sim.robot_mode = m
        return make_response(rid, True, "ok", {"robot_mode": m})
    if rt == "VISION_SET_DETECTION":
        en = bool((msg.get("data") or {}).get("enabled", False))
        sim.camera = en
        # Le vrai robot enchaîne sur un message « welcome » qui attribue
        # l'identifiant WebRTC. On le reproduit pour que le parcours du front
        # soit testable — le simulateur ne diffuse évidemment aucune vidéo.
        if en:
            sim.pending_welcome = True
        return make_response(rid, True, "ok", {"enabled": en},
                             error="") if False else json.dumps({
            "type": "response", "request_id": rid, "success": True, "code": "ok",
            "data": {"enabled": en}, "error": "", "message": "Web streaming enabled",
            "timestamp": now_iso()})

    # ── ⏳ commandes présentes dans la table §2.3 mais JAMAIS ÉPROUVÉES ──
    # Le nom réseau est sûr (extrait du bundle officiel) ; la charge utile est
    # déduite. Le simulateur répond « ok » comme le ferait vraisemblablement le
    # pont web du robot — attention : côté vrai robot, un « ok » du pont ne
    # prouve PAS que quelque chose s'est produit derrière.
    if rt == "MOTOR_SET_THERMAL_PROTECTION":
        # charge utile déduite du topic ROS /system/enable_thermal_protection
        en = bool((msg.get("data") or {}).get("enabled", False))
        sim.thermal_protection = en
        return make_response(rid, True, "ok", {"enabled": en})

    if rt == "VISION_SET_FACE_TRACKING":
        # ⚠ Sur le firmware réel, le nœud `face_tracker` n'est PAS actif
        # (exécutable présent, topics présents, nœud absent de la liste des
        # nœuds vivants). On mémorise donc le drapeau — c'est tout ce que fait
        # probablement le robot lui aussi — et la tête ne bougera pas d'un
        # degré. Le simulateur ne simule volontairement aucun suivi : promettre
        # ici un comportement qui n'existe pas sur le matériel serait le
        # meilleur moyen de s'en apercevoir trop tard.
        en = bool((msg.get("data") or {}).get("enabled", False))
        sim.face_tracking = en
        return make_response(rid, True, "ok", {"enabled": en})

    if rt == "BEHAVIOR_SET_PAUSE":
        sim.paused = bool((msg.get("data") or {}).get("paused", True))
        return make_response(rid, True, "ok", {"paused": sim.paused})
    if rt in ("BEHAVIOR_SET_RANDOM_ACTION", "ENABLE_AI_INTERACTION", "SET_VOICE_TRIGGER"):
        en = bool((msg.get("data") or {}).get("enabled", False))
        return make_response(rid, True, "ok", {"enabled": en})

    if rt == "self_recover":
        sim.vx = sim.vy = sim.wz = 0.0
        return make_response(rid, True, "ok", {"status": "recovered"})

    if rt == "attitude_control":
        # Le vrai robot n'a pas encore confirmé le nom des champs. Le simulateur
        # accepte head_* et body_*, et REFUSE le reste — de sorte qu'un mauvais
        # nom se voie ici plutôt que sur le robot.
        d = msg.get("data") or {}
        connus = {"head_yaw", "head_pitch", "head_roll",
                  "body_yaw", "body_pitch", "body_roll"}
        inconnus = [k for k in d if k not in connus]
        if inconnus:
            return make_response(rid, False, "invalid_argument",
                                 error=f"Unknown attitude field(s): {', '.join(inconnus)}")
        for k, v in d.items():
            if abs(float(v)) > 0.524:
                return make_response(rid, False, "invalid_argument",
                                     error=f"{k} out of range (±0.524 rad)")
        sim.attitude.update({k: float(v) for k, v in d.items()})
        return make_response(rid, True, "ok", dict(sim.attitude))

    # ── outils du simulateur (n'existent pas sur le vrai robot) ──
    if rt == "sim_stall":
        sim.stall = bool((msg.get("data") or {}).get("enabled", True))
        return make_response(rid, True, "ok",
                             {"SIMULATOR_ONLY": True, "stall": sim.stall,
                              "note": "Simule un moteur en butée pour tester le coupe-circuit."})

    return make_response(rid, False, "not_found", error=f"Unknown request_type: {rt}")


# ─────────────────────── serveur ───────────────────────
async def handler(ws, sim: Sim):
    cid = sim.next_id
    sim.next_id += 1
    sim.clients[cid] = ws
    await ws.send(json.dumps({
        "type": "event", "event_type": "connection_info", "timestamp": now_iso(),
        "data": {"client_id": cid, "status": "connected", "server_info": {
            "name": "Sirius Core API", "version": "4.0.0", "architecture": "Service-based",
            "capabilities": ["play_motion", "status_monitoring", "factory_test", "ota_update"]}}}))
    print(f"  client #{cid} connecté")
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                await ws.send(make_response("", False, "invalid_request", error="Invalid JSON"))
                continue
            await ws.send(handle_request(sim, msg))
    except websockets.ConnectionClosed:
        pass
    finally:
        sim.clients.pop(cid, None)
        print(f"  client #{cid} déconnecté")


async def broadcaster(sim: Sim):
    last = time.time()
    n = 0
    warned = False
    while True:
        await asyncio.sleep(0.1)                     # 10 Hz, comme le vrai robot
        now = time.time(); dt = now - last; last = now
        sim.step(dt)
        n += 1

        auto = sim.comportement_autonome(now)
        if auto:
            print(f"  [autonome] le robot joue « {auto} » de lui-même")

        out = [sim.gait_event()]                     # 10 Hz
        if sim.camera:
            # Lié à VISION_SET_DETECTION, comme sur le robot. Cadence : ~10 Hz
            # ici (celle de cette boucle) alors que le VRAI robot pousse
            # ~30 Hz. C'est assez pour démontrer les compteurs et l'onglet
            # Système ; ce n'est PAS assez pour juger des performances
            # d'affichage du front — le triple de trames, ça se sent. Le test de
            # charge se fait devant le robot, pas ici.
            out.append(sim.vision_event())
        if sim.pending_welcome:
            sim.pending_welcome = False
            out.append(json.dumps({"type": "welcome", "client_id": "ws_sim"}))
        if n % 10 == 0:                              # ~1 Hz
            out += [sim.battery_event(), sim.motor_load_event(), sim.motor_temp_event(),
                    sim.emotion_event(), sim.behavior_event(), sim.system_event()]
        if n % 100 == 0:                             # ~0,1 Hz
            out += [sim.network_event(), sim.lifecycle_event()]

        for ws in list(sim.clients.values()):
            for m in out:
                try:
                    await ws.send(m)
                except Exception:
                    pass

        # démonstration du coupe-circuit côté serveur (le helper fera pareil)
        peak = max(abs(v) for v in sim.loads)
        if peak >= SAFETY_LOAD_THRESHOLD and sim.stall_since:
            held = now - sim.stall_since
            if held >= SAFETY_SUSTAIN_S and not warned:
                warned = True
                print(f"  ⚠ SÉCURITÉ : charge {peak}‰ soutenue {held:.1f}s "
                      f"(seuil {SAFETY_LOAD_THRESHOLD}‰/{SAFETY_SUSTAIN_S}s) → un helper doit couper ICI")
        elif peak < SAFETY_LOAD_THRESHOLD:
            warned = False


async def main():
    ap = argparse.ArgumentParser(description="Simulateur du robot Sirius (protocole réel)")
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--stall", action="store_true",
                    help="démarre avec un moteur simulé en butée (test du coupe-circuit)")
    ap.add_argument("--auto-posture", type=float, default=0.0, metavar="S",
                    help="joue seul une action de posture toutes les S secondes "
                         "(comportement autonome simulé ; 0 = désactivé)")
    ap.add_argument("--motor-temps", choices=("muettes", "parlantes"), default="muettes",
                    help="sondes de température moteur : « muettes » = 0 sur les 4 pattes, "
                         "comme le firmware réel (défaut) ; « parlantes » = 28-45 °C "
                         "plausibles, pour démontrer l'affichage nominal")
    args = ap.parse_args()

    sim = Sim(stall=args.stall, motor_temps=args.motor_temps)
    sim.auto_posture = args.auto_posture
    sim.prochaine_auto = time.time() + args.auto_posture
    try:
        _v = (Path(__file__).resolve().parent / "VERSION.txt").read_text(encoding="utf-8").strip()
    except OSError:
        _v = "1.9"
    print(f"Simulateur Studio 360 pour Sirius (Studio 360) v{_v} "
          f"— ws://127.0.0.1:{args.port}")
    print("  projet indépendant, sans lien avec Hengbot")
    print("  protocole : Sirius Core API v4.0.0 (identique au robot réel)")
    if args.motor_temps == "muettes":
        print("  sondes moteur : MUETTES (0 sur les 4 pattes) — comme le firmware réel")
    else:
        print("  sondes moteur : parlantes (28-45 °C simulés) — démonstration uniquement")
    if args.stall:
        print("  ⚠ mode BLOCAGE actif : charge moteur soutenue au-delà du seuil")
    if args.auto_posture > 0:
        print(f"  comportement autonome simulé : action de posture toutes les {args.auto_posture:g} s")
    async with websockets.serve(lambda ws: handler(ws, sim), "127.0.0.1", args.port):
        await broadcaster(sim)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\narrêt.")
