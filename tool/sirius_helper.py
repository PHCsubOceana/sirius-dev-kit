#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
sirius_helper.py — Helper local de Studio 360 pour Sirius
=====================================================================
Forme courte : « Studio 360 ».

⚠️ PROJET INDÉPENDANT, SANS LIEN AVEC HENGBOT. Ce kit est un travail de
reverse engineering mené par explorations360 ; l'application officielle du
robot est celle de Hengbot, ce n'est pas celle-ci. Aucun partenariat, aucune
validation, aucun support du constructeur.

Le pont entre le navigateur et le robot Hengbot Sirius.

    navigateur  ──HTTP/WS──▶  helper (ce fichier)  ──WS──▶  robot :8765
     (front-end)               127.0.0.1:8787                 REST :8088

Pourquoi il existe : un navigateur ne peut pas ouvrir de socket brut ni de SSH,
et l'état du robot arrive **en flux poussé** (pas en polling). Le helper
maintient donc un cache alimenté par le flux, et expose au front une API
simple et stable (le contrat §8 du cahier des charges).

Lancer contre le SIMULATEUR (aucun robot, aucun risque) :
    python3 mock_robot.py                 # terminal 1
    python3 sirius_helper.py              # terminal 2  (--robot 127.0.0.1 par défaut)

Lancer contre le VRAI ROBOT :
    python3 sirius_helper.py --robot 192.168.1.42

    → API   : http://127.0.0.1:8787/docs
    → Flux  : ws://127.0.0.1:8787/ws

Dépendances : pip install fastapi uvicorn websockets httpx


SÉCURITÉ MOTEURS
----------------
Le robot pousse `motor-load` : 14 moteurs, en pour-mille de ±1000.
Relevé au repos sur le vrai robot : pic ~87 ‰. Un moteur en butée se
reconnaît à une charge élevée **et soutenue** (plateau, pas un pic).

Le helper surveille ce flux et, au-delà de SAFETY_LOAD_THRESHOLD tenu
SAFETY_SUSTAIN_S, il coupe le mouvement de lui-même et verrouille les
commandes jusqu'à réarmement explicite. C'est une protection que
l'interface officielle n'a pas.
"""

import argparse, asyncio, json, re, socket, time, uuid
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
import websockets
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from starlette.websockets import WebSocket, WebSocketDisconnect

# ───────────────────────────── réglages ─────────────────────────────
# ── Identité du produit ─────────────────────────────────────────────────────
# Décision client (26/07) : l'outil s'appelle « Studio 360 pour
# Sirius », forme courte « Studio 360 ». On l'écrit UNE fois ici et on le
# réutilise partout (titre FastAPI, bannière console, snapshot) — pour qu'un
# futur changement de nom ne laisse pas traîner d'ancienne mention.
# La mention d'indépendance n'est pas décorative : le robot est un produit
# Hengbot, l'application officielle est la leur, et rien ici n'émane d'eux.
# Le dire explicitement évite toute confusion sur l'origine de cet outil.
APP_NAME = "Studio 360 pour Sirius"
APP_SHORT = "Studio 360"
APP_NOTICE = "Par explorations360 — projet indépendant, non affilié à Hengbot."

# Version du kit. Source unique de vérité : le fichier VERSION.txt à la racine
# du paquet. Le lanceur .bat le lit aussi, et le helper la publie dans
# /api/status — l'interface web l'affiche telle quelle. Rien ne peut diverger.
_VERSION_REPLI = "1.9"


def _lire_version() -> str:
    try:
        v = (Path(__file__).resolve().parent / "VERSION.txt").read_text(encoding="utf-8").strip()
        return v or _VERSION_REPLI
    except OSError:
        return _VERSION_REPLI


VERSION = _lire_version()

ROBOT_WS_PORT = 8765          # web_bridge_node  (vérifié)
ROBOT_REST_PORT = 8088        # unified_api_node (vérifié)

# ── Seuils de sécurité, CALIBRÉS SUR LE ROBOT RÉEL ──────────────────────────
# Campagne de mesures sur 192.168.1.42 (25/07), pic de charge par condition :
#   repos ..................................  120 – 162 ‰
#   marche avant  0,06 m/s .................  540 ‰
#   marche avant  0,24 m/s (maxi) ..........  530 ‰   (moyenne 265 ‰)
#   marche arrière 0,16 m/s (maxi) .........  490 ‰   (moyenne 302 ‰)
#   rotation      1,20 rad/s (maxi) ........  540 ‰   (moyenne 344 ‰)
#   moteur en butée (simulé) ...............  950 – 985 ‰ SOUTENUS
#
# Constat contre-intuitif : le pic NE dépend PAS de la vitesse (540 ‰ aussi bien
# à 0,06 qu'à 0,24 m/s). Il est imposé par la dynamique du pas — impulsions de
# levée et de pose — pas par la vitesse d'avance. Le plafond du fonctionnement
# normal est donc ~540 ‰, toutes allures confondues.
#
# D'où le seuil retenu : 850 ‰, soit 57 % au-dessus du plafond normal et bien
# en dessous du plateau de butée. Le vrai discriminant reste la DURÉE : la
# marche produit des pics isolés, une butée un plateau. À 1 relevé/s, exiger
# 0,8 s revient à demander deux relevés consécutifs au-dessus du seuil.
SAFETY_LOAD_THRESHOLD = 850   # ‰
SAFETY_SUSTAIN_S = 0.8        # s au-dessus du seuil avant de couper
SAFETY_ENABLED = True

# ── Domaine de validité, RELEVÉ SUR LE ROBOT ────────────────────────────────
# Source : ros2 param dump /sirius_motion_control_node (25/07).
# Ce sont les limites que la pile de mouvement du robot applique elle-même.
# Le helper les fait respecter EN AMONT : une consigne hors domaine est écrêtée
# avant d'être envoyée, plutôt que d'être corrigée après coup.
#
# Le robot dispose en outre de ses propres garde-fous, actifs :
#   joint_clamp_enabled: true   → écrêtage des angles articulaires
#   ws_clamp_enabled:    true   → écrêtage de l'espace de travail
#   joint_jump_thresh_rad: 0.5  → détection des sauts d'angle
#   joint_max_rpm: 200
LIMITS = {
    "vx": (-0.16, 0.24),    # max_backward_velocity / max_forward_velocity (m/s)
    "vy": (-0.20, 0.20),    # max_y_velocity (m/s)
    "wz": (-1.20, 1.20),    # max_yaw_rate (rad/s)
    "pitch": (-0.524, 0.524),   # max_pitch  ≈ ±30°
    "roll": (-0.524, 0.524),    # max_roll   ≈ ±30°
}
# Géométrie de référence (pour la future voie UDP Play_Keyframe)
GEOM = {
    "default_z_ref_m": -0.16,        # hauteur de corps de référence
    "delta_x_m": 0.080, "delta_y_m": 0.078,   # demi-écartement des appuis
    "front_leg_max_height_m": 0.08,  # hauteur de levée avant
    "back_leg_max_height_m": 0.05,   # hauteur de levée arrière
}


def clamp_cmd(vx: float, vy: float, wz: float):
    """Écrête une consigne au domaine du robot. Renvoie (valeurs, liste des écrêtages)."""
    out, notes = {}, []
    for nom, val in (("vx", vx), ("vy", vy), ("wz", wz)):
        lo, hi = LIMITS[nom]
        c = max(lo, min(hi, val))
        if abs(c - val) > 1e-9:
            notes.append(f"{nom} {val:+.3f} → {c:+.3f} (limite {lo:+.2f}…{hi:+.2f})")
        out[nom] = c
    return out, notes


def to_normalized(vx: float, vy: float, wz: float):
    """
    Convertit une consigne physique (m/s, rad/s) vers l'échelle du robot.

    ⚠️ POINT CRUCIAL, vérifié en capturant l'interface officielle :
    `gait_control` n'attend PAS des m/s mais une valeur NORMALISÉE dans [-1, 1],
    fraction de la vitesse maximale. Leur touche « avancer » envoie linear_x = 1.

    Envoyer 0,15 en croyant dire « 0,15 m/s » revient à demander 15 % de la
    vitesse maxi : la foulée devient minuscule et le robot **piétine sur place**
    sans avancer — symptôme trompeur, puisqu'il renvoie fidèlement la valeur
    reçue et que la charge moteur paraît normale.

    On divise donc par la borne du domaine correspondant au sens demandé.
    """
    def norme(val, lo, hi):
        ref = hi if val >= 0 else abs(lo)
        n = 0.0 if ref == 0 else val / ref
        return max(-1.0, min(1.0, n))

    return {
        "linear_x": round(norme(vx, *LIMITS["vx"]), 4),
        "linear_y": round(norme(vy, *LIMITS["vy"]), 4),
        "angular_z": round(norme(wz, *LIMITS["wz"]), 4),
    }


# ── Commandes VÉRIFIÉES sur le robot (25/07) ────────────────────────────────
CMD_PLAY = "play_motion"        # ✅ {action_name} ou {file_path, loop, priority, torque}
CMD_CANCEL = "cancel_motion"    # ✅ {} → {"status":"canceled"}
CMD_GAIT = "gait_control"       # ✅ {linear_x, linear_y, angular_z}
CMD_STEP = "gait_step_move"     # ✅ {linear_x, linear_y, angular_z, steps}
CMD_STOP_ALL = "stop_all_motions"  # ✅ {} → {"status":"canceled"}
CMD_RECOVER = "self_recover"    # signature {} confirmée dans le code de l'app
CMD_ATTITUDE = "attitude_control"  # {body_pitch, body_yaw, head_pitch, …}

# ── Commandes de MODE, vérifiées le 25/07 ───────────────────────────────────
# Découverte importante : le protocole réseau utilise les clés en MAJUSCULES.
# Les noms en minuscules (play_motion, gait_control…) sont des alias hérités,
# encore acceptés ; mais les commandes de mode n'existent qu'en majuscules.
# L'interface officielle se connecte d'ailleurs à ws://<ip>:8765?audience=web
CMD_BEHAVIOR_PAUSE = "BEHAVIOR_SET_PAUSE"          # ✅ {paused: bool}
CMD_RANDOM_ACTION = "BEHAVIOR_SET_RANDOM_ACTION"   # ✅ {enabled: bool}
CMD_AI = "ENABLE_AI_INTERACTION"                   # ✅ {enabled: bool}
CMD_VOICE = "SET_VOICE_TRIGGER"                    # ✅ {enabled: bool}
CMD_VISION = "VISION_SET_DETECTION"           # ✅ {enabled: bool} → active le flux vidéo
CMD_GET_ROBOT_MODE = "USER_GET_ROBOT_MODE"         # ✅ {} → {robot_mode}
CMD_SET_ROBOT_MODE = "USER_SET_ROBOT_MODE"         # ✅ {robot_mode: "ground"|"desktop"}

# ── Commandes NON CONFIRMÉES sur le robot (table §2.3, jamais éprouvées) ─────
# Elles figurent dans la table des 59 commandes extraite du bundle officiel,
# donc le NOM RÉSEAU est sûr ; c'est la charge utile et l'effet qui ne le sont
# pas. Elles sont donc dans UNVERIFIED : `_wrap` attache son avertissement à
# chaque réponse, et l'interface peut le répercuter à l'utilisateur.
#
# Rappel du piège §2.2 : le fil réseau veut les MAJUSCULES.
# `enable_thermal_protection` et `face_tracking_control` sont les handlers
# INTERNES du firmware — les envoyer tels quels renvoie « Unknown request_type ».
CMD_THERMAL = "MOTOR_SET_THERMAL_PROTECTION"
# ⏳ {enabled: bool} — charge utile déduite du topic ROS
# /system/enable_thermal_protection (§12 bis), non confirmée sur le fil.

CMD_FACE_TRACK = "VISION_SET_FACE_TRACKING"
# ⏳ {enabled: bool} — charge utile non documentée, et surtout : le nœud
# `face_tracker` N'EST PAS ACTIF sur ce firmware. L'exécutable est présent, les
# topics existent, mais le nœud n'apparaît pas dans la liste des nœuds vivants
# (relevé du 25/07). La commande a donc de fortes chances d'être acceptée par le
# pont web… et de n'avoir AUCUN effet observable sur le robot. On l'expose quand
# même — c'est la seule façon de le vérifier en présence du matériel — mais on
# ne promet rien, et l'interface doit rester prudente sur le retour.

# MODE ROBOT — le réglage le plus important, et le moins évident :
#   "desktop" : bride la démarche et les mouvements amples pour que le robot
#               ne tombe pas d'une table. Les pattes bougent SUR PLACE.
#   "ground"  : démarche complète et déplacements amples.
# Un robot qui « piétine sans avancer » est presque toujours en mode desktop.
ROBOT_MODES = ("ground", "desktop")

UNVERIFIED = {CMD_RECOVER, CMD_ATTITUDE, CMD_THERMAL, CMD_FACE_TRACK}

# ── TEMPÉRATURE CPU / SoC : la vérité, écrite en dur ────────────────────────
# Il n'existe AUCUNE température CPU sur le WebSocket 8765 ni sur le REST 8088.
# `system_metrics` ne porte que cpu_percent, core_count, load_avg et disk — on a
# vérifié la trame entière, il n'y a pas de champ de température caché.
# La seule source connue sur le robot est le topic ROS
# `/fan_breathing/cpu_temp [std_msgs/Float32]`, qui n'est PONTÉ NULLE PART vers
# le monde WebSocket : ce helper parle WebSocket, pas ROS. Y accéder supposerait
# un petit nœud ROS embarqué sur le robot qui republie la valeur sur le pont web
# — c'est faisable, ce n'est pas fait.
# Conséquence assumée : /api/system renvoie toujours `"cpu": None`, jamais une
# estimation tirée de cpu_percent. On préfère un trou honnête à un chiffre faux.
CPU_TEMP_SOURCE = "ros:/fan_breathing/cpu_temp"

# ── Vision : fenêtre de calcul de la cadence ────────────────────────────────
# L'événement `vision-detection` arrive à ~30 Hz. On estime la cadence sur une
# fenêtre glissante de 2 s (assez longue pour lisser la gigue, assez courte pour
# que l'affichage réagisse), et on considère le flux mort au-delà de 3 s sans
# trame — soit ~90 trames manquées, aucune ambiguïté possible.
VISION_HZ_FENETRE_S = 2.0
VISION_ACTIF_S = 3.0
VISION_IMAGE_DEFAUT = {"width": 640, "height": 360}   # repère du modèle (§9 bis)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


# ═══════════════════════════ état du robot ═══════════════════════════
class State:
    """Cache alimenté par le flux poussé du robot. Aucune interrogation périodique."""

    def __init__(self):
        self.connected = False
        self.robot_ip: Optional[str] = None
        self.server_info: dict = {}
        self.last_event_at: Optional[float] = None

        self.battery = {"percent": None, "voltage": None, "current": None,
                        "temperature": None, "charge": None, "capacity": None}
        self.velocity = {"vx": 0.0, "vy": 0.0, "wz": 0.0}
        self.motors = {"loads": [], "peak": 0, "temps": {}, "unit": "pwm_permille"}
        self.emotion: dict = {}
        self.behavior: dict = {}
        self.system: dict = {}
        self.network: dict = {}
        self.nodes: list = []
        self.player = {"is_playing": False, "status": "unknown", "file_path": ""}

        # None = « on n'a jamais rien commandé, on ne sait pas ». C'est
        # volontaire : le robot ne publie l'état d'aucun de ces modes sur le
        # flux, on ne connaît donc que ce qu'on a soi-même demandé.
        self.modes = {"robot_mode": None, "autonomous": None,
                      "random_action": None, "ai": None, "voice": None,
                      "detection": None, "face_tracking": None,
                      "thermal_protection": None}

        # ── vision : compteurs alimentés par `vision-detection` (~30 Hz) ────
        # Ce dictionnaire est exposé TEL QUEL dans snapshot()["vision"] et dans
        # GET /api/system. `active`, `hz` et `last_s` sont recalculés au moment
        # de la lecture (voir rafraichir_vision) et non à la réception : sinon
        # ils resteraient figés sur leur dernière valeur quand le flux s'arrête,
        # et l'interface afficherait « 30 Hz » devant un flux mort.
        self.vision = {"active": False, "hz": 0.0, "counts": {}, "total": 0,
                       "skeletons": 0, "frames": 0, "last_s": None,
                       "image": dict(VISION_IMAGE_DEFAUT)}
        # horodatages des trames de la fenêtre glissante. deque = ajout en queue
        # et purge en tête en O(1) amorti : indispensable à 30 Hz.
        self._vision_stamps: deque[float] = deque()
        self._vision_last_at: Optional[float] = None

        # posture : le robot NE LA PUBLIE PAS sur ce canal (elle vit sur ROS,
        # /action_player/current_posture). On la tient donc de deux façons, et
        # `posture_source` dit toujours laquelle :
        #   "commande" → posture demandée depuis l'interface
        #   "deduit"   → devinée d'après l'action observée (y compris autonome)
        #   None       → inconnue, on n'affirme rien
        self.posture: Optional[str] = None
        self.posture_source: Optional[str] = None
        self.head = {"yaw": 0.0, "pitch": 0.0, "cible": "head"}

        self.safety = {"enabled": SAFETY_ENABLED, "tripped": False, "reason": "",
                       "peak": 0, "since": None,
                       "threshold": SAFETY_LOAD_THRESHOLD, "sustain_s": SAFETY_SUSTAIN_S}

    def reset_vision(self):
        """Remet les compteurs vision à zéro : `frames` compte DEPUIS la connexion.

        Appelé à l'amorçage d'une nouvelle liaison — sans quoi le compteur de
        trames d'un robot précédent survivrait à un changement de cible.
        """
        self.vision.update({"active": False, "hz": 0.0, "counts": {}, "total": 0,
                            "skeletons": 0, "frames": 0, "last_s": None,
                            "image": dict(VISION_IMAGE_DEFAUT)})
        self._vision_stamps.clear()
        self._vision_last_at = None

    def rafraichir_vision(self) -> dict:
        """Recalcule les champs DÉPENDANTS DU TEMPS de `self.vision`, et le renvoie.

        Purge la fenêtre glissante puis en déduit la cadence. Le coût est celui
        des trames sorties de la fenêtre : O(1) amorti, quelle que soit la durée
        pendant laquelle le flux a tourné.
        """
        maintenant = time.time()
        stamps = self._vision_stamps
        while stamps and maintenant - stamps[0] > VISION_HZ_FENETRE_S:
            stamps.popleft()
        dernier = self._vision_last_at
        self.vision["hz"] = round(len(stamps) / VISION_HZ_FENETRE_S, 1)
        self.vision["active"] = bool(dernier and maintenant - dernier < VISION_ACTIF_S)
        self.vision["last_s"] = round(maintenant - dernier, 1) if dernier else None
        return self.vision

    def snapshot(self) -> dict:
        return {
            "app_version": VERSION,
            # nom du produit : le front n'a plus à le coder en dur
            "app_name": APP_NAME, "app_short": APP_SHORT, "app_notice": APP_NOTICE,
            "connected": self.connected, "robot_ip": self.robot_ip,
            "server_info": self.server_info,
            "stale_s": round(time.time() - self.last_event_at, 2) if self.last_event_at else None,
            "battery": self.battery, "velocity": self.velocity, "motors": self.motors,
            "emotion": self.emotion, "behavior": self.behavior, "system": self.system,
            "network": self.network, "nodes": self.nodes, "player": self.player,
            "modes": self.modes, "safety": self.safety,
            "vision": self.rafraichir_vision(),
            "posture": self.posture, "posture_source": self.posture_source,
            "head": self.head, "timestamp": now_iso(),
        }


state = State()
front_clients: set[WebSocket] = set()


async def broadcast(payload: dict):
    """Pousse vers les clients du front (le navigateur).

    On itère une COPIE de `front_clients`, et ce n'est pas de la prudence
    gratuite. `await ws.send_text(...)` est un point de suspension : quand un
    client n'absorbe plus assez vite (onglet qui vient de se fermer, tampon TCP
    plein), l'envoi rend la main à la boucle — et un autre onglet qui se
    connecte ou se déconnecte pendant ce temps fait un `add`/`discard` sur le
    set. L'itérateur casse alors sur un `RuntimeError: Set changed size during
    iteration`, levé PAR LA BOUCLE `for` : il passe donc à côté du `try` ci-
    dessous et remonte à l'appelant. Symptôme observé le 26/07 : cette
    exception, remontée depuis le `finally` de RobotLink.run(), a tué pour de
    bon la tâche de reconnexion — le helper continuait de servir l'interface
    en répondant « Impossible de joindre le robot, vérifiez qu'il est allumé »
    alors que le robot était parfaitement joignable.
    """
    dead = set()
    msg = json.dumps(payload)
    for ws in list(front_clients):
        try:
            await ws.send_text(msg)
        except Exception:
            dead.add(ws)
    front_clients.difference_update(dead)


# ═══════════════════════════ lien vers le robot ═══════════════════════════
class RobotLink:
    """Client WebSocket du robot : reconnexion automatique et appels requête/réponse."""

    def __init__(self, ip: str, port: int = ROBOT_WS_PORT):
        self.ip, self.port = ip, port
        self.ws = None
        self.pending: dict[str, asyncio.Future] = {}
        self._stop = False

    @property
    def url(self) -> str:
        return f"ws://{self.ip}:{self.port}?audience=web"

    async def retarget(self, ip: Optional[str]):
        """Change l'adresse du robot et force la reconnexion immédiate."""
        self.ip = ip
        state.robot_ip = ip
        ws = self.ws
        self.ws = None
        if ws is not None:
            try:
                await ws.close()          # la boucle run() rebouclera aussitôt
            except Exception:
                pass

    async def run(self):
        backoff = 1
        while not self._stop:
            if not self.ip:               # pas de cible : on attend /api/connect
                state.connected = False
                await asyncio.sleep(0.3)
                continue
            try:
                async with websockets.connect(self.url, ping_interval=20, open_timeout=6) as ws:
                    self.ws = ws
                    state.connected = True
                    state.robot_ip = self.ip
                    backoff = 1
                    print(f"[robot] connecté à {self.url}")
                    await broadcast({"type": "link", "connected": True, "robot": self.ip})
                    # Certains événements ne sont poussés que toutes les ~10 s : on amorce
                    # le cache tout de suite pour que le front ne démarre pas sur du vide.
                    asyncio.create_task(self._prime())
                    async for raw in ws:
                        await self._on_message(raw)
            except Exception as e:
                if self.ip:
                    print(f"[robot] déconnecté ({type(e).__name__}: {e}) — nouvelle tentative dans {backoff}s")
            finally:
                self.ws = None
                if state.connected:
                    state.connected = False
                    # Ceinture ET bretelles : ce qui est levé DANS un `finally`
                    # échappe au `except` d'au-dessus et sort de la boucle —
                    # donc de la tâche, qui meurt sans un mot. Le lien au robot
                    # ne se rétablirait plus jamais. Rien de ce qui se passe
                    # côté navigateur ne doit pouvoir coûter ça.
                    try:
                        await broadcast({"type": "link", "connected": False})
                    except Exception as e:
                        print(f"[robot] diffusion de la coupure ignorée ({type(e).__name__}: {e})")
            if self._stop:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 15)

    async def _prime(self):
        """Remplit le cache dès la connexion, sans attendre les événements lents."""
        await asyncio.sleep(0.3)
        # nouvelle liaison = on ne sait plus dans quelle posture est le robot.
        # Mieux vaut « inconnu » qu'une affirmation périmée.
        state.posture = None
        state.posture_source = None
        state.reset_vision()      # `frames` compte depuis CETTE connexion
        await broadcast({"type": "posture", "posture": None, "source": None})
        for rt, apply in (("get_lifecycle_states", None), ("get_status", None),
                          (CMD_GET_ROBOT_MODE, None)):
            try:
                r = await self.request(rt, timeout=4)
                if r.get("success"):
                    d = r.get("data", {})
                    if rt == "get_lifecycle_states":
                        state.nodes = d.get("nodes", [])
                    elif rt == CMD_GET_ROBOT_MODE:
                        state.modes["robot_mode"] = d.get("robot_mode")
                    else:
                        state.player.update(d)
                        await maj_posture(deduire_posture(d.get("file_path") or ""), "deduit")
            except Exception as e:
                print(f"[robot] amorçage « {rt} » ignoré : {e}")

    async def _on_message(self, raw: str):
        try:
            msg = json.loads(raw)
        except Exception:
            return
        mtype = msg.get("type")

        if mtype == "response":
            fut = self.pending.pop(msg.get("request_id", ""), None)
            if fut and not fut.done():
                fut.set_result(msg)
            return

        if mtype == "event":
            state.last_event_at = time.time()
            await apply_event(msg)
            return

        # ── Signalisation WebRTC (caméra) ──────────────────────────────────
        # Le flux vidéo est du WebRTC : la négociation passe par ce WebSocket,
        # mais la VIDÉO circule ensuite en pair-à-pair entre le navigateur et le
        # robot. Le helper ne peut donc que relayer la signalisation — il ne voit
        # jamais les images. On transmet tout ce qui n'est ni réponse ni
        # événement : `welcome` (qui attribue le client_id WebRTC), la réponse
        # SDP, et les candidats ICE du robot.
        await broadcast({"type": "robot_signal", "payload": msg})

    async def request(self, request_type: str, data: dict | None = None, timeout: float = 6.0) -> dict:
        if not self.ws:
            raise HTTPException(503, "Robot non connecté")
        rid = uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self.ws.send(json.dumps({"type": "request", "request_type": request_type,
                                       "request_id": rid, "data": data or {}}))
        try:
            return await asyncio.wait_for(fut, timeout)
        except asyncio.TimeoutError:
            self.pending.pop(rid, None)
            raise HTTPException(504, f"Le robot n'a pas répondu à « {request_type} »")


link: Optional[RobotLink] = None


# ═══════════════════════════ traitement des événements ═══════════════════════════
# ═══════════════ posture : déduite des actions réellement jouées ═══════════════
#
# CONSTAT VÉRIFIÉ sur le protocole (mock_robot.py reproduit le robot) : aucun
# événement WebSocket ne porte la posture. Le seul signal d'action est
# `behavior-status` → `engine.running` (1 Hz) et il NE CONTIENT PAS le nom du
# fichier. Ce nom ne s'obtient que par `get_status`, et seulement PENDANT la
# lecture (`file_path` est vidé à la fin).
#
# La posture réelle existe sur ROS (`/action_player/current_posture`) mais ce
# pont parle WebSocket, pas ROS : on ne peut donc pas la LIRE, seulement la
# DÉDUIRE. D'où `posture_source`, diffusé avec la posture : on dit toujours
# d'où l'on sait.

POSTURE_COUCHE = frozenset(("lie", "lay", "prone", "ground", "crouch",
                            "down", "rest", "sit"))
POSTURE_DEBOUT = frozenset(("stand", "returnposition", "idle"))


def _mots_action(nom: str) -> set:
    """Découpe un nom d'action en mots : séparateurs ET casse chameau.

    Indispensable, pas cosmétique : « returnPosition » CONTIENT la sous-chaîne
    « sit » (po-SIT-ion), et TOUS les noms d'action du firmware commencent par
    « stand_ ». Une comparaison par sous-chaîne classerait donc
    `stand_default_returnPosition_brief` comme couché — l'exact contraire.
    """
    base = nom.rsplit("/", 1)[-1]
    if base.lower().endswith(".avi"):
        base = base[:-4]
    coupe = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", base)
    return {m.lower() for m in re.split(r"[^A-Za-z0-9]+", coupe) if m}


def deduire_posture(nom: str) -> Optional[str]:
    """« ground » / « stand » d'après un nom d'action, None si indécidable.

    L'ordre compte : la famille COUCHÉE est testée en premier, puisque chaque
    nom commence par « stand_ » — sans quoi tout serait « debout ».
    """
    if not nom:
        return None
    mots = _mots_action(nom)
    if mots & POSTURE_COUCHE:
        return "ground"
    if mots & POSTURE_DEBOUT:
        return "stand"
    return None


async def maj_posture(posture: Optional[str], source: str):
    """Publie la posture et sa provenance vers tous les clients, si ça change."""
    if posture is None:
        return
    # une déduction qui CONFIRME une posture commandée ne dégrade pas la source
    if (posture == state.posture and source == "deduit"
            and state.posture_source == "commande"):
        return
    if posture == state.posture and source == state.posture_source:
        return
    state.posture = posture
    state.posture_source = source
    await broadcast({"type": "posture", "posture": posture, "source": source})


_action_en_cours = False
_sonde_en_vol = False


async def sonder_action_en_cours():
    """Demande QUELLE action joue, pour en déduire la posture.

    Déclenché par le front montant de `engine.running` — ce n'est donc pas de
    la scrutation périodique : c'est le flux qui pose la question, une fois.
    """
    global _sonde_en_vol
    if _sonde_en_vol or link is None:
        return
    _sonde_en_vol = True
    try:
        r = await link.request("get_status", timeout=3)
        if not r.get("success"):
            return
        d = r.get("data", {}) or {}
        if isinstance(d, dict):
            state.player.update(d)
            await maj_posture(deduire_posture(d.get("file_path") or ""), "deduit")
    except Exception as e:
        print(f"[posture] sonde ignorée : {e}")
    finally:
        _sonde_en_vol = False


async def apply_event(msg: dict):
    # ── Tolérance d'enveloppe (26/07) ───────────────────────────────────────
    # Tous les événements relevés sur le robot portent leur nom sous la clé
    # `event_type` (§7). Mais la doc §9 bis montre `vision-detection` sous la
    # clé `event` — et jusqu'ici ce code ne lisait QUE `event_type`, donc une
    # trame de cette seconde forme serait tombée dans le vide : aucune erreur,
    # aucun log, juste des compteurs vision qui ne bougent jamais. Panne
    # silencieuse, la pire à diagnostiquer.
    # On ne sait pas laquelle des deux formes le firmware émet réellement (la
    # capture ayant servi à la doc peut avoir été normalisée à la main), alors
    # on accepte les deux et on renormalise sur `event_type` en sortie : le
    # front ne voit qu'une seule forme, quoi qu'envoie le robot.
    et = msg.get("event_type") or msg.get("event")
    d = msg.get("data") or {}

    if et == "connection_info":
        state.server_info = d.get("server_info", {})

    elif et == "gait-trajectory":
        fv = d.get("filtered_velocity", {})
        state.velocity = {"vx": fv.get("linear_x", 0.0), "vy": fv.get("linear_y", 0.0),
                          "wz": fv.get("angular_z", 0.0)}

    elif et == "battery-status":
        pct = d.get("percentage")
        state.battery = {
            # le robot renvoie un RATIO 0-1 → on normalise en % pour le front
            "percent": round(pct * 100, 1) if isinstance(pct, (int, float)) else None,
            "voltage": d.get("voltage"), "current": d.get("current"),
            "temperature": d.get("temperature"), "charge": d.get("charge"),
            "capacity": d.get("capacity"), "status": d.get("power_supply_status"),
        }

    elif et == "motor-load":
        loads = d.get("loads", [])
        peak = max((abs(v) for v in loads), default=0)
        state.motors.update({"loads": loads, "peak": peak,
                             "unit": d.get("unit", "pwm_permille"),
                             "range": d.get("range", {"min": -1000, "max": 1000})})
        await check_safety(peak)

    elif et == "motor-temperature":
        # ⚠ Sur CE firmware, les quatre sondes renvoient 0 — elles sont muettes.
        # Et 0 ne veut pas dire « 0 °C » : ça veut dire « pas de mesure ». Le
        # helper transmet donc la valeur BRUTE, sans la filtrer ni la remplacer
        # par None : c'est au front de décider comment le dire (« sonde muette »).
        # Traduire ici reviendrait à masquer une donnée réelle si un firmware
        # ultérieur se met à publier de vraies températures.
        state.motors["temps"] = {k: d.get(k) for k in
                                 ("front_left", "front_right", "back_left", "back_right")}

    elif et == "emotion-update":
        state.emotion = {"state": d.get("emotion_state"), "valence": d.get("valence_value"),
                         "arousal": d.get("arousal_value"), "satiety": d.get("satiety_value"),
                         "fatigue": d.get("fatigue_status")}

    elif et == "behavior-status":
        eng = d.get("engine", {})
        state.behavior = {"idle": eng.get("idle"), "intent": eng.get("intent"),
                          "running": eng.get("running"), "active_tree": eng.get("active_tree"),
                          "recent_events": eng.get("recent_events", [])}
        # une action démarre — la nôtre OU celle du comportement autonome :
        # on va demander laquelle, pour en déduire la posture
        global _action_en_cours
        tourne = bool(eng.get("running"))
        if tourne and not _action_en_cours:
            asyncio.create_task(sonder_action_en_cours())
        _action_en_cours = tourne

    elif et == "system_metrics":
        state.system = {"cpu_percent": d.get("cpu_percent"), "core_count": d.get("core_count"),
                        "load_avg": d.get("load_avg"), "disk": d.get("disk")}

    elif et == "network-status":
        state.network = {"ssid": d.get("ssid"), "ip": d.get("ip_address"),
                         "mac": d.get("mac_address"), "signal": d.get("signal_strength"),
                         "connected": d.get("is_connected")}

    elif et == "lifecycle_update":
        state.nodes = d.get("nodes", [])

    elif et == "vision-detection":
        # ── Chemin CHAUD : ~30 Hz. Tout ce qui est ici s'exécute 30 fois par
        # seconde, dans la boucle de lecture du WebSocket robot. Deux règles :
        #   1. O(1) — on écrase les compteurs de la dernière trame, on n'accumule
        #      rien qui grossirait avec le temps (seule la fenêtre de cadence
        #      garde des horodatages, et elle se purge d'elle-même sur 2 s).
        #   2. AUCUN broadcast supplémentaire, et surtout aucun `await` réseau :
        #      le relais générique en fin de fonction suffit déjà à pousser la
        #      trame au front, qui se charge du throttle d'affichage (§9 bis :
        #      stocker dans une ref, dessiner en requestAnimationFrame). Ajouter
        #      un second envoi doublerait le trafic pour rien, et attendre une
        #      réponse du robot ici bloquerait la boucle — même piège que trip().
        v = state.vision
        counts: dict[str, int] = {}
        for det in (d.get("detections") or []):
            # `class_name` est la nomenclature du modèle ; `type` est le repli
            # observé sur certaines trames. Une classe inconnue est comptée
            # telle quelle, sans liste blanche : c'est ainsi qu'on découvre ce
            # que le modèle embarqué sait vraiment détecter (§9 bis).
            nom = det.get("class_name") or det.get("type") or "inconnu"
            counts[nom] = counts.get(nom, 0) + 1
        v["counts"] = counts
        v["total"] = sum(counts.values())
        v["skeletons"] = len(d.get("skeletons") or [])
        v["frames"] += 1
        larg, haut = d.get("image_width"), d.get("image_height")
        if isinstance(larg, int) and larg > 0:
            v["image"]["width"] = larg
        if isinstance(haut, int) and haut > 0:
            v["image"]["height"] = haut
        # horodatage pour la cadence ; `active`/`hz`/`last_s` sont calculés à la
        # lecture (rafraichir_vision), pas ici.
        maintenant = time.time()
        state._vision_last_at = maintenant
        state._vision_stamps.append(maintenant)
        while (state._vision_stamps
               and maintenant - state._vision_stamps[0] > VISION_HZ_FENETRE_S):
            state._vision_stamps.popleft()

    # relais normalisé vers le front
    await broadcast({"type": "event", "event_type": et, "data": d, "timestamp": msg.get("timestamp")})


# ═══════════════════════════ coupe-circuit moteurs ═══════════════════════════
_over_since: Optional[float] = None


async def check_safety(peak: int):
    """Coupe le mouvement si la charge reste au-dessus du seuil (signature d'une butée)."""
    global _over_since
    state.safety["peak"] = peak
    if not state.safety["enabled"] or state.safety["tripped"]:
        return

    if peak >= SAFETY_LOAD_THRESHOLD:
        if _over_since is None:
            _over_since = time.time()
        elif time.time() - _over_since >= SAFETY_SUSTAIN_S:
            await trip(f"Charge moteur {peak} ‰ maintenue plus de {SAFETY_SUSTAIN_S} s "
                       f"(seuil {SAFETY_LOAD_THRESHOLD} ‰)")
    else:
        _over_since = None


async def trip(reason: str):
    """
    Déclenchement du coupe-circuit.

    ⚠️ Cette fonction est appelée DEPUIS la boucle de lecture du WebSocket robot
    (motor-load → check_safety → trip). Il ne faut donc jamais y attendre une
    réponse du robot : la réponse transiterait par cette même boucle, qui est
    bloquée le temps de l'attente — interblocage, et alerte retardée de plusieurs
    secondes. On prévient donc le front d'abord, et on envoie l'arrêt dans une
    tâche séparée.
    """
    state.safety.update({"tripped": True, "reason": reason, "since": now_iso()})
    print(f"[SÉCURITÉ] {reason} → arrêt automatique")

    # 1) alerter immédiatement (aucun aller-retour réseau avant ceci)
    await broadcast({"type": "safety", "tripped": True, "reason": reason, "timestamp": now_iso()})

    # 2) couper le mouvement hors de la boucle de lecture
    asyncio.create_task(_emergency_stop())


async def robust_stop(tentatives: int = 6) -> bool:
    """
    Arrêt VÉRIFIÉ du robot.

    Constat terrain (25/07) : une commande d'arrêt unique ne suffit pas
    toujours — le robot a continué à reculer à 0,16 m/s plusieurs secondes
    après un `gait_control` à zéro. On répète donc l'ordre et on confirme
    l'arrêt sur la télémétrie (`gait-trajectory`, poussée à 10 Hz) avant de
    considérer le robot immobile.
    """
    if not (link and link.ws):
        return False
    for i in range(tentatives):
        try:
            await link.request(CMD_GAIT, {"linear_x": 0.0, "linear_y": 0.0, "angular_z": 0.0}, timeout=3)
            await link.request(CMD_STOP_ALL, {}, timeout=3)
        except Exception as e:
            print(f"[STOP] tentative {i+1}/{tentatives} : {e}")
        await asyncio.sleep(0.6)
        v = state.velocity
        if all(abs(float(v.get(k, 0.0))) < 0.005 for k in ("vx", "vy", "wz")):
            if i:
                print(f"[STOP] arrêt confirmé après {i+1} tentative(s)")
            return True
    print("[STOP] ⚠ vitesse toujours non nulle après "
          f"{tentatives} tentatives — vérifier le robot physiquement")
    await broadcast({"type": "safety", "tripped": True,
                     "reason": "Arrêt non confirmé par la télémétrie — vérifier le robot",
                     "timestamp": now_iso()})
    return False


async def _emergency_stop():
    ok = await robust_stop()
    print(f"[SÉCURITÉ] arrêt {'confirmé' if ok else 'NON CONFIRMÉ'}")


# ═══════════════════════════ API pour le front ═══════════════════════════
class MoveIn(BaseModel):
    vx: float = 0.0
    vy: float = 0.0
    wz: float = 0.0


class ActionIn(BaseModel):
    name: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(link.run())
    yield
    link._stop = True
    task.cancel()


app = FastAPI(title=f"{APP_NAME} — Helper local", version=VERSION,
              description=(f"{APP_SHORT} — pont local entre le navigateur et le robot "
                           f"Hengbot Sirius.\n\n**{APP_NOTICE}** Travail de reverse "
                           f"engineering d'explorations360 ; l'application officielle "
                           f"du robot est celle de Hengbot."),
              lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ConnectIn(BaseModel):
    ip: str


@app.post("/api/connect")
async def connect(p: ConnectIn):
    """
    Change de robot À CHAUD. C'est ainsi que l'interface choisit l'adresse :
    on n'a plus besoin de la passer en ligne de commande au démarrage.
    """
    ip = p.ip.strip()
    if not ip:
        raise HTTPException(422, "Adresse IP vide")

    if link.ip == ip and link.ws is not None:
        return {"ok": True, "already": True, "robot_ip": ip, "connected": True}

    print(f"[robot] changement de cible → {ip}")
    await link.retarget(ip)

    # on laisse au lien le temps de s'établir avant de répondre
    for _ in range(30):                       # ~6 s max
        if state.connected:
            # …puis à l'amorçage d'aboutir, pour que l'interface ne s'ouvre pas
            # sur des champs vides (nœuds ROS, état du lecteur d'actions)
            for _ in range(12):               # ~2,4 s de plus, au plus
                if state.nodes:
                    break
                await asyncio.sleep(0.2)
            return {"ok": True, "robot_ip": ip, "connected": True,
                    "server_info": state.server_info, "nodes": len(state.nodes)}
        await asyncio.sleep(0.2)
    raise HTTPException(504, f"Impossible de joindre le robot {ip}. "
                             f"Vérifiez qu'il est allumé et sur le même réseau.")


@app.post("/api/disconnect")
async def disconnect():
    await link.retarget(None)
    return {"ok": True, "connected": False}


@app.get("/api/status")
async def get_status():
    return state.snapshot()


@app.get("/api/actions")
async def get_actions():
    r = await link.request("get_actions")
    if not r.get("success"):
        raise HTTPException(502, r.get("error", "échec"))
    d = r.get("data", {})
    return {"base_path": d.get("action_base_path"), "actions": d.get("actions", [])}


@app.get("/api/player")
async def get_player():
    r = await link.request("get_status")
    if r.get("success"):
        state.player = r.get("data", {})
    return state.player


@app.get("/api/nodes")
async def get_nodes():
    r = await link.request("get_lifecycle_states")
    return r.get("data", {}).get("nodes", state.nodes)


@app.post("/api/move")
async def move(p: MoveIn):
    if state.safety["tripped"]:
        raise HTTPException(423, f"Sécurité déclenchée : {state.safety['reason']}. "
                                 f"Réarmer via POST /api/safety/clear.")
    # 1) garde-fou a priori : jamais de consigne hors domaine physique
    v, notes = clamp_cmd(p.vx, p.vy, p.wz)
    # 2) conversion vers l'échelle normalisée attendue par le robot
    charge = to_normalized(v["vx"], v["vy"], v["wz"])
    r = await link.request(CMD_GAIT, charge)
    out = _wrap(r, CMD_GAIT)
    out["envoye"] = charge
    out["consigne_ms"] = v
    if notes:
        out["clamped"] = notes
    return out


@app.get("/api/limits")
async def limits():
    """Domaine de validité relevé sur le robot + géométrie de référence."""
    return {"limits": {k: {"min": a, "max": b} for k, (a, b) in LIMITS.items()},
            "geometry": GEOM,
            "robot_side_guards": {"joint_clamp_enabled": True, "ws_clamp_enabled": True,
                                  "joint_jump_thresh_rad": 0.5, "joint_max_rpm": 200},
            "source": "ros2 param dump /sirius_motion_control_node"}


# « RESET » — action et paramètres capturés sur l'interface officielle
ACTION_BASE_PATH = "/root/material/actions"
ACTION_RESET_FILE = ACTION_BASE_PATH + "/stand_default_returnPosition_brief.avi"
RESET_PRIORITY = 5      # priorité haute : sans elle l'action se fait écraser
RESET_TORQUE = 2047     # couple maximal, nécessaire pour se relever


@app.post("/api/reset")
async def reset():
    """
    Remet le robot debout (sortie de posture allongée).

    Reproduit exactement le bouton « Reset » du dashboard officiel : ce n'est
    pas `stand_default_idle` mais l'action `returnPosition`, jouée en priorité
    haute et à couple maximal — sinon le comportement en cours l'écrase et le
    robot reste couché.
    """
    r = await link.request(CMD_PLAY, {"file_path": ACTION_RESET_FILE, "loop": False,
                                      "priority": RESET_PRIORITY, "torque": RESET_TORQUE})
    if r.get("success"):
        # returnPosition remet debout : c'est une commande explicite, pas une déduction
        await maj_posture("stand", "commande")
    return _wrap(r, CMD_PLAY)


@app.post("/api/recovery")
async def recovery():
    """Redressement après chute."""
    r = await link.request(CMD_RECOVER, {})
    return _wrap(r, CMD_RECOVER)


@app.post("/api/reveil_debout")
async def reveil_debout():
    """
    Réveil + « figer debout », de façon ROBUSTE.

    Problème constaté (Phil) : au tout premier démarrage, après le réveil par
    balayage sur l'écran de la tête, un simple bouton « Debout » ne suffit pas —
    le robot se recouche ou se rendort. Deux causes, traitées ici dans l'ordre :

      1. le comportement autonome (priorité 1) rejoue ses propres actions et
         écrase le redressement → on le met en PAUSE et on coupe les actions
         aléatoires ;
      2. le balayage de l'écran bascule peut-être le robot en mode « desktop »
         (démarche bridée, posture instable) → on force le mode « ground ».

    Puis on joue returnPosition en priorité 5 / couple maxi, et on le REJOUE une
    fois après un court instant pour le tenir debout le temps que l'autonome soit
    bien retombé. Le tout premier réveil après mise sous tension exige, lui, le
    balayage physique — ça, aucune commande ne le remplace (cf. API §8).
    """
    etapes = []

    async def _tenter(cmd, data, cle):
        try:
            r = await link.request(cmd, data)
            etapes.append({"etape": cle, "ok": bool(r.get("success"))})
            return r
        except HTTPException as e:
            etapes.append({"etape": cle, "ok": False, "erreur": e.detail})
            return {}

    # 1. mode sol (au cas où le balayage aurait basculé en desktop)
    await _tenter(CMD_SET_ROBOT_MODE, {"robot_mode": "ground"}, "mode_ground")
    state.modes["robot_mode"] = "ground"
    # 2. couper l'autonome et les actions aléatoires qui écrasent le redressement
    await _tenter(CMD_BEHAVIOR_PAUSE, {"paused": True}, "autonome_pause")
    state.modes["autonomous"] = False
    await _tenter(CMD_RANDOM_ACTION, {"enabled": False}, "aleatoire_off")
    state.modes["random_action"] = False
    # 3. redressement tenu : returnPosition, priorité 5, couple maxi, rejoué
    debout = {"file_path": ACTION_RESET_FILE, "loop": False,
              "priority": RESET_PRIORITY, "torque": RESET_TORQUE}
    r = await _tenter(CMD_PLAY, debout, "debout")
    await asyncio.sleep(1.2)
    await _tenter(CMD_PLAY, debout, "debout_tenu")
    await maj_posture("stand", "commande")
    return {"ok": all(e["ok"] for e in etapes), "etapes": etapes,
            "note": "Si c'est le tout premier réveil après mise sous tension, "
                    "il faut d'abord balayer l'écran de la tête vers le haut — "
                    "aucune commande ne remplace ce geste."}


# ═══════════════════════════ posture debout / au sol ═══════════════════════════
#
# « Debout » est certain : c'est l'action du bouton Reset, capturée sur
# l'interface officielle (priorité 5, couple maxi — sinon le comportement en
# cours l'écrase).
#
# « Au sol » ne l'est pas : le nom du fichier d'action varie d'un firmware à
# l'autre et le nôtre est plus récent que le paquet dont on dispose. Plutôt que
# de coder en dur un nom qui n'existera peut-être pas, on CHERCHE dans la
# bibliothèque réelle du robot, par ordre de préférence, et on renvoie le nom
# retenu — ainsi l'interface peut l'afficher et on sait exactement ce qui a été
# joué.
GROUND_PREFERES = (          # noms exacts, essayés en premier
    "stand_default_lie_down", "stand_default_liedown", "lie_default_idle",
    "prone_default_idle", "stand_default_lay_down", "stand_default_down",
)
GROUND_MOTIFS = (            # sinon : motifs dans l'identifiant, du plus au moins sûr
    ("lie", "lay", "prone", "ground", "floor"),
    ("crouch", "down", "rest", "sleep"),
    ("sit",),
)


def _choisir_action_sol(actions: list[dict]) -> Optional[dict]:
    """Meilleure action « se coucher » disponible dans la bibliothèque du robot."""
    par_id: dict[str, dict] = {}
    for a in actions:
        for cle in ("id", "name"):
            v = a.get(cle)
            if isinstance(v, str) and v:
                par_id.setdefault(v.lower(), a)
    for nom in GROUND_PREFERES:
        if nom.lower() in par_id:
            return par_id[nom.lower()]
    for groupe in GROUND_MOTIFS:
        for ident, a in par_id.items():
            if any(m in ident for m in groupe):
                return a
    return None


class PostureIn(BaseModel):
    posture: str            # "stand" | "ground"


@app.post("/api/posture")
async def set_posture(p: PostureIn):
    """Bascule debout ↔ au sol, avec la même priorité que le bouton Reset."""
    cible = (p.posture or "").strip().lower()
    if cible not in ("stand", "ground"):
        raise HTTPException(422, "posture doit valoir 'stand' ou 'ground'.")

    if cible == "stand":
        r = await link.request(CMD_PLAY, {"file_path": ACTION_RESET_FILE, "loop": False,
                                          "priority": RESET_PRIORITY, "torque": RESET_TORQUE})
        out = _wrap(r, CMD_PLAY)
        await maj_posture("stand", "commande")
        out.update(posture="stand", action="stand_default_returnPosition_brief", verifie=True)
        return out

    # ── au sol : on cherche l'action dans la bibliothèque réelle
    lst = await link.request("get_actions")
    actions = lst.get("data", {}).get("actions", []) if lst.get("success") else []
    choix = _choisir_action_sol(actions)
    if choix is None:
        raise HTTPException(501, "Aucune action « se coucher » trouvée dans la bibliothèque du "
                                 "robot. Ouvre l'onglet Actions pour voir la liste complète : "
                                 "si tu repères la bonne, joue-la directement et dis-moi son nom.")
    chemin = choix.get("full_path") or choix.get("file") or choix.get("filename")
    charge: dict[str, Any] = {"loop": False, "priority": RESET_PRIORITY,
                              "torque": choix.get("torque") or RESET_TORQUE}
    if isinstance(chemin, str) and chemin.startswith("/"):
        charge["file_path"] = chemin
    else:
        charge["action_name"] = choix.get("name") or choix.get("id")
    r = await link.request(CMD_PLAY, charge)
    out = _wrap(r, CMD_PLAY)
    await maj_posture("ground", "commande")
    out.update(posture="ground", action=choix.get("id") or choix.get("name"),
               verifie=False,
               note="Action déduite de la bibliothèque du robot — à confirmer visuellement.")
    return out


# ═══════════════════════════════ tête ═══════════════════════════════
#
# `attitude_control` prend {body_pitch, body_yaw, head_pitch, …} d'après le
# firmware — les noms de champs ne sont PAS encore vérifiés sur le robot. D'où
# deux précautions : une amplitude volontairement plus étroite que le domaine
# déclaré (±0,524 rad), et un paramètre `cible` qui permet d'essayer la variante
# « corps » sans rebuild si « tête » ne bouge rien.
HEAD_LIMITS = {"yaw": 0.45, "pitch": 0.35}   # rad — ~26° et ~20°
HEAD_CHAMPS = {"head": ("head_yaw", "head_pitch"),
               "body": ("body_yaw", "body_pitch")}


class HeadIn(BaseModel):
    yaw: float = 0.0        # rad, + = vers la gauche
    pitch: float = 0.0      # rad, + = vers le haut
    cible: str = "head"     # "head" | "body"


@app.post("/api/head")
async def head(p: HeadIn):
    if state.safety["tripped"]:
        raise HTTPException(423, f"Sécurité déclenchée : {state.safety['reason']}.")
    cible = (p.cible or "head").strip().lower()
    if cible not in HEAD_CHAMPS:
        raise HTTPException(422, "cible doit valoir 'head' ou 'body'.")
    yaw = max(-HEAD_LIMITS["yaw"], min(HEAD_LIMITS["yaw"], float(p.yaw)))
    pitch = max(-HEAD_LIMITS["pitch"], min(HEAD_LIMITS["pitch"], float(p.pitch)))
    ky, kp = HEAD_CHAMPS[cible]
    charge = {ky: round(yaw, 4), kp: round(pitch, 4)}
    r = await link.request(CMD_ATTITUDE, charge)
    out = _wrap(r, CMD_ATTITUDE)
    state.head = {"yaw": yaw, "pitch": pitch, "cible": cible}
    out.update(envoye=charge, head=state.head)
    return out


@app.post("/api/head/center")
async def head_center(p: Optional[HeadIn] = None):
    """Ramène la tête au neutre."""
    cible = (p.cible if p else "head") or "head"
    return await head(HeadIn(yaw=0.0, pitch=0.0, cible=cible))


@app.post("/api/action/play")
async def play(p: ActionIn):
    if state.safety["tripped"]:
        raise HTTPException(423, "Sécurité déclenchée — réarmer d'abord.")
    r = await link.request(CMD_PLAY, {"action_name": p.name})
    if r.get("success"):
        # on connaît le nom joué : la posture s'en DÉDUIT (elle n'est pas commandée)
        await maj_posture(deduire_posture(p.name), "deduit")
    return _wrap(r, CMD_PLAY)


class PlayExIn(BaseModel):
    name: str                       # nom de l'action (sans chemin ni extension)
    loop: bool = False              # boucler l'animation (l'éditeur d'enchaînements
                                    # boucle une anim le temps d'un bloc puis annule)
    priority: int = RESET_PRIORITY  # ≥5 : sinon écrasée par le comportement autonome
    torque: int = 0                 # 0 = laisse le couple par défaut de l'action


@app.post("/api/action/play_ex")
async def play_ex(p: PlayExIn):
    """
    Joue une action avec loop + priorité (forme file_path), pour l'éditeur
    d'enchaînements. `/api/action/play` classique ne transporte QUE le nom (pas
    de priorité), donc une action y est vite écrasée par l'autonome. Ici on
    reconstruit le chemin comme le bouton Reset et on force la priorité.
    """
    if state.safety["tripped"]:
        raise HTTPException(423, "Sécurité déclenchée — réarmer d'abord.")
    nom = (p.name or "").strip().strip("/")
    if not nom:
        raise HTTPException(422, "nom d'action vide.")
    data = {"file_path": "%s/%s.avi" % (ACTION_BASE_PATH, nom),
            "loop": bool(p.loop), "priority": int(p.priority)}
    if p.torque and p.torque > 0:
        data["torque"] = int(p.torque)
    r = await link.request(CMD_PLAY, data)
    if r.get("success"):
        await maj_posture(deduire_posture(nom), "deduit")
    return _wrap(r, CMD_PLAY)


@app.post("/api/action/cancel")
async def cancel():
    r = await link.request(CMD_CANCEL, {})
    return _wrap(r, CMD_CANCEL)


@app.post("/api/stop")
async def stop():
    """Arrêt immédiat et VÉRIFIÉ — autorisé même sécurité déclenchée."""
    ok = await robust_stop()
    return {"ok": ok, "confirmed": ok, "velocity": state.velocity,
            "message": "Arrêt confirmé par la télémétrie." if ok else
                       "⚠ Arrêt NON confirmé — vérifier le robot physiquement."}


# ═══════════════════════ modes & comportement ═══════════════════════
class BoolIn(BaseModel):
    enabled: bool


class RobotModeIn(BaseModel):
    mode: str


@app.get("/api/modes")
async def modes_get():
    """État courant des modes. `robot_mode` est relu sur le robot."""
    try:
        r = await link.request(CMD_GET_ROBOT_MODE, {}, timeout=4)
        if r.get("success"):
            state.modes["robot_mode"] = (r.get("data") or {}).get("robot_mode")
    except Exception:
        pass
    return state.modes


@app.post("/api/modes/autonomous")
async def mode_autonomous(p: BoolIn):
    """Mode autonome. Actif = le robot décide seul et peut annuler tes commandes."""
    r = await link.request(CMD_BEHAVIOR_PAUSE, {"paused": not p.enabled})
    out = _wrap(r, CMD_BEHAVIOR_PAUSE)
    state.modes["autonomous"] = p.enabled
    return out


@app.post("/api/modes/random")
async def mode_random(p: BoolIn):
    """Actions aléatoires au repos."""
    r = await link.request(CMD_RANDOM_ACTION, {"enabled": p.enabled})
    out = _wrap(r, CMD_RANDOM_ACTION)
    state.modes["random_action"] = p.enabled
    return out


@app.post("/api/modes/ai")
async def mode_ai(p: BoolIn):
    """Interaction IA (dialogue vocal)."""
    r = await link.request(CMD_AI, {"enabled": p.enabled})
    out = _wrap(r, CMD_AI)
    state.modes["ai"] = p.enabled
    return out


@app.post("/api/modes/voice")
async def mode_voice(p: BoolIn):
    """Déclenchement vocal (mot de réveil)."""
    r = await link.request(CMD_VOICE, {"enabled": p.enabled})
    out = _wrap(r, CMD_VOICE)
    state.modes["voice"] = p.enabled
    return out


@app.post("/api/modes/robot")
async def mode_robot(p: RobotModeIn):
    """
    Mode « sol » ou « bureau ».
    En mode bureau, le robot bride sa démarche : il piétine sans avancer.
    """
    if p.mode not in ROBOT_MODES:
        raise HTTPException(422, f"Mode inconnu : {p.mode}. Attendu : {' ou '.join(ROBOT_MODES)}")
    r = await link.request(CMD_SET_ROBOT_MODE, {"robot_mode": p.mode})
    out = _wrap(r, CMD_SET_ROBOT_MODE)
    state.modes["robot_mode"] = p.mode
    return out


@app.post("/api/camera")
async def camera(p: BoolIn):
    """
    Active/coupe le flux vidéo du robot.
    La négociation WebRTC se fait ensuite entre le NAVIGATEUR et le robot,
    relayée par le WebSocket du helper (voir ws_front).

    Conservée pour COMPATIBILITÉ : c'est exactement la même commande que
    POST /api/vision/detection (VISION_SET_DETECTION active d'un seul geste la
    vidéo ET la sortie du modèle de perception). Elle renseigne donc le même
    état — sans quoi couper la caméra par cette route laisserait l'interface
    croire que la détection tourne encore.
    """
    r = await link.request(CMD_VISION, {"enabled": p.enabled})
    out = _wrap(r, CMD_VISION)
    state.modes["detection"] = p.enabled
    return out


# ═══════════════════════ vision & protection thermique ═══════════════════════
#
# Note sur le coupe-circuit : ces trois routes NE sont volontairement PAS
# gardées par `state.safety["tripped"]`. La garde protège de ce qui FAIT BOUGER
# le robot (/api/move, /api/head, /api/action/play) ; couper une détection ou
# armer une protection thermique ne déplace rien, et interdire ces réglages
# pendant un déclenchement empêcherait justement de diagnostiquer la panne.
# Même politique que /api/modes/* et /api/camera, qui ne sont pas gardées non plus.

@app.post("/api/vision/detection")
async def vision_detection(p: BoolIn):
    """
    Active/coupe la détection visuelle (personnes : body / head / face).

    Même commande que /api/camera : sur ce firmware, `VISION_SET_DETECTION`
    ouvre à la fois le flux WebRTC et l'événement `vision-detection` poussé à
    ~30 Hz sur le canal principal. Les détections sont donc lisibles SANS
    afficher la vidéo — c'est ce qui alimente les compteurs de `state.vision`.
    """
    r = await link.request(CMD_VISION, {"enabled": p.enabled})
    out = _wrap(r, CMD_VISION)
    state.modes["detection"] = p.enabled
    return out


@app.post("/api/vision/face_tracking")
async def vision_face_tracking(p: BoolIn):
    """
    Suivi de visage par la tête. ⏳ NON VÉRIFIÉ, et probablement sans effet.

    Le nom réseau vient de la table §2.3 ; la charge utile {enabled} est déduite
    par analogie avec les autres bascules. Surtout : le nœud `face_tracker`
    n'est pas actif sur ce firmware (binaire et topics présents, nœud absent de
    la liste des nœuds vivants). Le pont web acceptera très probablement la
    commande — et il ne se passera rien. `_wrap` attache l'avertissement, à
    l'interface de ne rien promettre.
    """
    r = await link.request(CMD_FACE_TRACK, {"enabled": p.enabled})
    out = _wrap(r, CMD_FACE_TRACK)
    state.modes["face_tracking"] = p.enabled
    return out


@app.post("/api/thermal/protection")
async def thermal_protection(p: BoolIn):
    """
    Protection thermique des moteurs. ⏳ NON VÉRIFIÉ.

    Nom réseau issu de la table §2.3, charge utile déduite du topic ROS
    `/system/enable_thermal_protection`. À ne pas confondre avec le coupe-circuit
    du helper (/api/safety) : celui-ci surveille la CHARGE moteur depuis le PC,
    celle-là est une protection interne au robot — et on ne sait pas encore ce
    qu'elle fait exactement, ni sur quel seuil elle agit.
    """
    r = await link.request(CMD_THERMAL, {"enabled": p.enabled})
    out = _wrap(r, CMD_THERMAL)
    state.modes["thermal_protection"] = p.enabled
    return out


@app.get("/api/system")
async def system_get():
    """
    Vue « Système » : métriques, températures, nœuds ROS, vision.

    Regroupe en un seul appel ce que l'onglet Système affiche, pour éviter au
    front trois requêtes et trois façons de gérer l'absence de donnée.

    ⚠️ `temperatures.cpu` vaut TOUJOURS None, et ce n'est pas un oubli : aucune
    température CPU n'existe sur le WebSocket ni sur le REST 8088 (voir la note
    CPU_TEMP_SOURCE en tête de fichier). `cpu_temp_source` dit où elle se trouve
    réellement — sur ROS — pour que l'interface puisse l'expliquer plutôt que
    d'afficher un tiret sans justification.
    """
    lst = state.nodes if isinstance(state.nodes, list) else []
    actifs = sum(1 for n in lst if isinstance(n, dict) and n.get("state") == "active")
    return {
        "system": state.system,
        "temperatures": {
            # seule température RÉELLEMENT publiée par le robot
            "battery": state.battery.get("temperature"),
            # 4 sondes de pattes ; renvoient 0 sur ce firmware (sondes muettes),
            # valeur transmise brute — l'interprétation appartient au front
            "motors": state.motors.get("temps") or {},
            "cpu": None,
        },
        "cpu_temp_source": CPU_TEMP_SOURCE,
        "nodes": {"active": actifs, "total": len(lst)},
        "vision": state.rafraichir_vision(),
    }


@app.get("/api/safety")
async def safety_get():
    return state.safety


@app.post("/api/safety/clear")
async def safety_clear():
    global _over_since
    state.safety.update({"tripped": False, "reason": "", "since": None})
    _over_since = None
    await broadcast({"type": "safety", "tripped": False, "timestamp": now_iso()})
    return state.safety


@app.get("/api/ai/character")
async def ai_character():
    """Passe-plat vers l'API REST du robot (unified_api_node, port 8088)."""
    if not state.robot_ip:
        raise HTTPException(503, "Robot non connecté")
    url = f"http://{state.robot_ip}:{ROBOT_REST_PORT}/api/v1/ai/character"
    async with httpx.AsyncClient(timeout=6) as c:
        r = await c.get(url)
    return JSONResponse(status_code=r.status_code, content=_json_or_text(r))


def _json_or_text(r):
    try:
        return r.json()
    except Exception:
        return {"raw": r.text[:2000]}


def _wrap(r: dict, cmd: str) -> dict:
    out = {"ok": bool(r.get("success")), "code": r.get("code"),
           "data": r.get("data", {}), "error": r.get("error", "")}
    if cmd in UNVERIFIED:
        out["warning"] = ("Commande déduite du firmware, non encore vérifiée sur le robot réel. "
                          "À confirmer en présence du robot.")
    if not out["ok"]:
        raise HTTPException(502, json.dumps(out, ensure_ascii=False))
    return out


@app.websocket("/ws")
async def ws_front(ws: WebSocket):
    await ws.accept()
    front_clients.add(ws)
    await ws.send_text(json.dumps({"type": "snapshot", "data": state.snapshot()}))
    try:
        while True:
            brut = await ws.receive_text()
            # Le front peut pousser de la signalisation WebRTC : on la relaie
            # telle quelle vers le robot (offre SDP, candidats ICE).
            try:
                m = json.loads(brut)
            except Exception:
                continue
            if isinstance(m, dict) and str(m.get("type", "")).startswith("webrtc_"):
                if link and link.ws:
                    try:
                        await link.ws.send(json.dumps(m))
                    except Exception as e:
                        print(f"[webrtc] relais échoué : {e}")
    except WebSocketDisconnect:
        pass
    finally:
        front_clients.discard(ws)


# ═══════════════════════════ déambulation libre ═══════════════════════════
# Le nœud `deambulation.py` tourne À BORD du robot (le ToF n'existe que sur
# ROS) et expose un petit service HTTP. Le helper n'est qu'un passe-plat : il
# connaît déjà l'adresse du robot, le navigateur ne parle qu'au helper.
DEAMB_PORT = 8790


def _deamb_base() -> str:
    # On vise `link.ip` — l'adresse CIBLE — et non `state.robot_ip`, qui n'est
    # renseignée qu'une fois le WebSocket établi. C'est délibéré : si la liaison
    # WebSocket tombe pendant que le robot marche, le bouton « Arrêter » doit
    # continuer de fonctionner. Le service de déambulation est indépendant.
    ip = (link.ip if link else None) or state.robot_ip
    if not ip:
        raise HTTPException(409, "Aucune adresse de robot — connecte-le d'abord "
                                 "dans Studio 360.")
    return f"http://{ip}:{DEAMB_PORT}"


async def _deamb(methode: str, chemin: str, params: dict | None = None):
    # Délai COURT (1,2 s) : ce service est interrogé en continu par la page. S'il
    # n'est pas lancé à bord, un délai long faisait s'empiler les requêtes mortes
    # et engorgeait tout le helper (constaté le 28/07 : ~2,2 s par appel, 5 appels
    # par seconde). Mieux vaut échouer vite et laisser la page espacer ses essais.
    url = _deamb_base() + chemin
    try:
        async with httpx.AsyncClient(timeout=1.2) as c:
            r = await c.request(methode, url, params=params)
    except httpx.HTTPError:
        raise HTTPException(
            503, "Service de déambulation injoignable. Sur le robot : "
                 "python3 deambulation.py --service")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text[:200])
    return JSONResponse(r.json())


@app.get("/api/deambulation/etat")
async def deambulation_etat():
    """Grille ToF, décision en cours et contexte, relus sur le robot."""
    return await _deamb("GET", "/etat")


@app.post("/api/deambulation/demarrer")
async def deambulation_demarrer():
    """Arme la marche. Le nœud réapprend son fond EN MARCHANT (~5 s) puis erre."""
    return await _deamb("POST", "/demarrer")


@app.post("/api/deambulation/arreter")
async def deambulation_arreter():
    """Coupe la marche et remet les consignes à zéro."""
    return await _deamb("POST", "/arreter")


@app.post("/api/deambulation/vitesse")
async def deambulation_vitesse(v: float):
    """Règle la consigne d'avance (bornée côté robot entre 0,05 et 1,0)."""
    return await _deamb("POST", "/vitesse", {"v": v})


@app.get("/api/deambulation/animations")
async def deambulation_animations_get():
    """Mapping événement→animation d'évitement courant, relu sur le robot."""
    return await _deamb("GET", "/animations")


@app.post("/api/deambulation/animations")
async def deambulation_animations_set(mapping: dict):
    """Règle les animations d'évitement. Corps JSON {événement: action|null},
    ex. {"approche": "stand_default_peer_brief", "bloque": null}. Contrairement
    aux autres routes, on transmet un CORPS JSON (et non des paramètres), d'où ce
    passe-plat écrit à la main plutôt que via `_deamb`."""
    url = _deamb_base() + "/animations"
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.post(url, json=mapping)
    except httpx.HTTPError:
        raise HTTPException(
            503, "Service de déambulation injoignable. Sur le robot : "
                 "python3 deambulation.py --service")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text[:200])
    return JSONResponse(r.json())


# ═══════════════════════════ écran de la tête ═══════════════════════════
# lvgl_gui_node n'expose que des SERVICES ROS : injoignables depuis le helper,
# qui ne parle que WebSocket. On passe donc par le nœud embarqué (deambulation.py
# --service), qui tourne dans ROS et relaie. Le service doit être lancé à bord.
@app.get("/api/ecran/contenus")
async def ecran_contenus():
    """Animations installées sur le robot (Lottie et GIF)."""
    return await _deamb("GET", "/ecran/contenus")


async def _ecran_post(quoi: str, corps: dict):
    url = _deamb_base() + "/ecran/" + quoi
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.post(url, json=corps)
    except httpx.HTTPError:
        raise HTTPException(503, "Service embarqué injoignable. Sur le robot : "
                                 "python3 deambulation.py --service")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, r.text[:200])
    return JSONResponse(r.json())


@app.post("/api/ecran/toast")
async def ecran_toast(corps: dict):
    """Affiche un message texte sur l'écran de la tête."""
    return await _ecran_post("toast", corps)


@app.post("/api/ecran/lottie")
async def ecran_lottie(corps: dict):
    """Joue une animation Lottie (bibliothèque /root/material/lottie)."""
    return await _ecran_post("lottie", corps)


@app.post("/api/ecran/gif")
async def ecran_gif(corps: dict):
    """Joue un GIF (bibliothèque /root/material/gif)."""
    return await _ecran_post("gif", corps)


# ═══════════════════════ enchaînements (Play Blocks) ═══════════════════════
# L'éditeur d'enchaînements enregistre ses séquences et groupes ICI, dans un
# fichier à côté du helper, plutôt que seulement dans le navigateur : ainsi ils
# survivent à un changement de navigateur, se partagent avec le kit, et se
# retrouvent depuis n'importe quel poste qui parle à ce helper. Le navigateur
# garde une copie locale comme cache hors-ligne.
ENCHAIN_DATA = Path(__file__).resolve().parent / "enchainements_data.json"


@app.get("/api/enchainements")
async def enchainements_get():
    """Séquences + groupes enregistrés sur le PC (vide si aucun)."""
    if not ENCHAIN_DATA.is_file():
        return JSONResponse({"groups": [], "sequence": [], "loop": False})
    try:
        return JSONResponse(json.loads(ENCHAIN_DATA.read_text(encoding="utf-8")))
    except (OSError, ValueError) as e:
        raise HTTPException(500, f"Lecture impossible : {e}")


@app.post("/api/enchainements")
async def enchainements_set(data: dict):
    """Enregistre séquences + groupes sur le PC (corps JSON)."""
    try:
        ENCHAIN_DATA.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                encoding="utf-8")
    except OSError as e:
        raise HTTPException(500, f"Écriture impossible ({ENCHAIN_DATA.name}) : {e}")
    return {"ok": True, "fichier": str(ENCHAIN_DATA)}


# La page elle-même. Elle est autonome (un seul fichier, aucun assemblage) et
# ═══════════════════════════ yeux (écran de la tête) ═══════════════════════════
# L'écran de la tête reçoit la pose des yeux par une voie UDP dédiée (port 8770,
# user_interface_udp_server_node). Une trame = un objet JSON à 4 « bones » :
# l'iris et la pupille (position sur l'écran, dilatation, rotation), et les deux
# paupières (haute/basse = clignement). Format relevé sur le script Blender du
# constructeur — connu au bit près, mais l'EFFET n'a pas encore été filmé sur le
# robot : à vérifier au premier essai.
# ✅ RELEVÉ SUR LE ROBOT le 28/07 (ss -ulnp) : un SEUL port UDP écoute,
#    0.0.0.0:8768 — tenu par user_interface_udp_server_node. Les ports 8770
#    (face_ui), 8769 (overlay) et 8772 (pondération) du script Blender ne sont
#    PAS ouverts sur le firmware 2.5.0. C'est la cause de l'absence d'effet :
#    l'UDP ne signale jamais un port fermé, les trames partaient dans le vide.
#    Le serveur unique aiguille donc selon le CONTENU du message.
EYES_UDP_PORT = 8768      # canal unique, confirmé en écoute
EYES_OVERLAY_PORT = 8769  # ⏳ non ouvert sur ce firmware — gardé pour essai
EYES_FACE_PORT = 8770     # ⏳ idem
EYES_WEIGHT_PORT = 8768   # la pondération passe par le même serveur
EYES_Y = 120        # amplitude gauche/droite (±)
EYES_Z = 142        # amplitude haut/bas (±)
# Valeurs NEUTRES relevées dans l'add-on d'export officiel (blender_export_addon,
# fonction d'export des données d'interface) :
#     default_z = -32 si eye_upper, sinon 63
# Autrement dit, yeux OUVERTS = paupière haute à -32 et paupière basse à +63.
# ⚠ Correction du 28/07 : on envoyait +75 / -75, soit les SIGNES INVERSÉS — les
# deux paupières se croisaient, ce qui explique probablement l'absence d'effet.
EYES_UPPER_OUVERT = -32
EYES_LOWER_OUVERT = 63
EYES_FERME = 16     # les deux paupières se rejoignent au milieu (-32 … 63)


def _robot_ip_ou_409() -> str:
    ip = (link.ip if link else None) or state.robot_ip
    if not ip:
        raise HTTPException(409, "Aucune adresse de robot — connecte-le d'abord "
                                 "dans Studio 360.")
    return ip


class EyesIn(BaseModel):
    pos_y: float = 0.0     # gauche(-)/droite(+)
    pos_z: float = 0.0     # bas(-)/haut(+)
    scale: float = 1.0     # 0..2 : dilatation de l'iris
    rot_x: float = 0.0     # 0..359 : rotation de l'iris
    blink: float = 0.0     # 0 = ouvert, 1 = fermé
    canal: str = "face"    # "face" (8770) ou "overlay" (8769)


class EyesPrioriteIn(BaseModel):
    """Pondération entre l'animation interne du robot et le canal externe.
    Reprise du script Blender du constructeur : {cmd:set_weight_params,
    main_weight, channel2_weight}. Hypothèse à valider sur le robot : sans
    donner la main au canal externe, le moteur d'émotion repeint l'écran en
    continu et écrase ce qu'on envoie."""
    main_weight: float = 0.0
    channel2_weight: float = 1.0


def _trame_yeux(p: EyesIn) -> dict:
    cy = max(-EYES_Y, min(EYES_Y, float(p.pos_y)))
    cz = max(-EYES_Z, min(EYES_Z, float(p.pos_z)))
    sc = max(0.0, min(2.0, float(p.scale)))
    rot = float(p.rot_x) % 360.0
    t = max(0.0, min(1.0, float(p.blink)))          # 0 = ouvert, 1 = fermé
    # les paupières partent de leur position ouverte et convergent vers le milieu
    haut = EYES_UPPER_OUVERT + t * (EYES_FERME - EYES_UPPER_OUVERT)
    bas = EYES_LOWER_OUVERT + t * (EYES_FERME - EYES_LOWER_OUVERT)
    return {
        "eye_iris":  {"pos_y": cy, "pos_z": cz, "scale_y": sc, "scale_z": sc, "rot_x": rot},
        "eye_pupil": {"pos_y": cy, "pos_z": cz, "scale_y": sc, "scale_z": sc, "rot_x": rot},
        "eye_upper": {"pos_z": round(haut), "scale_z": 1.0},
        "eye_lower": {"pos_z": round(bas), "scale_z": 1.0},
    }


def _envoie_udp(ip: str, port: int, obj: dict):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.sendto(json.dumps(obj).encode("utf-8"), (ip, port))
    finally:
        s.close()


@app.post("/api/eyes")
async def eyes(p: EyesIn):
    """Pose des yeux, envoyée en UDP à l'écran de la tête.

    ⚠ Non confirmé sur le robot : l'UDP ne donne aucun accusé de réception, donc
    un « ok » ici prouve seulement que la trame est partie du PC.
    """
    ip = _robot_ip_ou_409()
    canal = (p.canal or "").lower()
    port = {"overlay": EYES_OVERLAY_PORT, "face": EYES_FACE_PORT}.get(canal, EYES_UDP_PORT)
    trame = _trame_yeux(p)
    _envoie_udp(ip, port, trame)
    return {"ok": True, "port": port, "envoye": trame}


@app.post("/api/eyes/priorite")
async def eyes_priorite(p: EyesPrioriteIn):
    """Donne la main au canal externe sur l'écran (port 8772)."""
    ip = _robot_ip_ou_409()
    msg = {"cmd": "set_weight_params",
           "main_weight": float(p.main_weight),
           "channel2_weight": float(p.channel2_weight),
           "timestamp": time.time()}
    _envoie_udp(ip, EYES_WEIGHT_PORT, msg)
    return {"ok": True, "envoye": msg}


@app.post("/api/eyes/center")
async def eyes_center():
    """Recentre les yeux (regard neutre, paupières ouvertes)."""
    ip = _robot_ip_ou_409()
    _envoie_udp(ip, EYES_UDP_PORT, _trame_yeux(EyesIn()))
    return {"ok": True}


# ═══════════════════════════════ LED ═══════════════════════════════
# Les LED ne sont accessibles NI par le WebSocket NI par le REST : la seule voie
# connue est le canal UDP 8768, dont le nœud republie sur
# /robot_led_controller/led_colors. Format relevé dans l'add-on Blender officiel
# (get_led_data_for_frame) : deux LED de tête, six LED de corps, en RVB 0-255.
#   {"head_led": [[r,g,b], [r,g,b]], "body_led": [[r,g,b] × 6]}
# ⚠ L'UDP ne renvoie aucun accusé : un « ok » signifie que la trame est partie.
LED_UDP_PORT = 8768
LED_TETE = 2
LED_CORPS = 6
# Couleur d'origine relevée dans l'add-on officiel (valeurs de repli de
# export_led_data) : un rouge profond, identique pour la tête et le corps.
LED_DEFAUT = [194, 0, 0]


class LedIn(BaseModel):
    couleur: Optional[list] = None   # [r,g,b] appliqué à toutes les LED
    head: Optional[list] = None      # 2 × [r,g,b] — prioritaire sur `couleur`
    body: Optional[list] = None      # 6 × [r,g,b] — idem


def _rvb(c) -> list:
    """Normalise une couleur en [r,g,b] entiers 0-255."""
    try:
        r, v, b = (int(x) for x in list(c)[:3])
    except Exception:
        raise HTTPException(422, "couleur attendue sous la forme [r, v, b] (0-255).")
    borne = lambda x: max(0, min(255, x))
    return [borne(r), borne(v), borne(b)]


def _serie(valeur, defaut, n) -> list:
    """n couleurs : soit la liste fournie (complétée), soit `defaut` répété."""
    if not valeur:
        return [list(defaut) for _ in range(n)]
    out = [_rvb(c) for c in valeur][:n]
    while len(out) < n:
        out.append(list(out[-1] if out else defaut))
    return out


@app.post("/api/led/defaut")
async def led_defaut():
    """Remet les LED à la couleur d'origine du constructeur (194, 0, 0)."""
    ip = _robot_ip_ou_409()
    trame = {"head_led": [list(LED_DEFAUT) for _ in range(LED_TETE)],
             "body_led": [list(LED_DEFAUT) for _ in range(LED_CORPS)]}
    _envoie_udp(ip, LED_UDP_PORT, trame)
    return {"ok": True, "couleur": LED_DEFAUT, "envoye": trame}


@app.post("/api/led")
async def led(p: LedIn):
    """Allume les LED (2 à la tête, 6 sur le corps) via le canal UDP 8768."""
    ip = _robot_ip_ou_409()
    base = _rvb(p.couleur) if p.couleur else [0, 0, 0]
    trame = {"head_led": _serie(p.head, base, LED_TETE),
             "body_led": _serie(p.body, base, LED_CORPS)}
    _envoie_udp(ip, LED_UDP_PORT, trame)
    return {"ok": True, "envoye": trame}


# ═══════════════════════════ marche pas-à-pas ═══════════════════════════
# gait_step_move : le robot exécute un NOMBRE de foulées donné puis s'arrête de
# lui-même — plus sûr qu'un flux gait_control continu qu'il faut penser à couper.
# Vitesse NORMALISÉE [-1,1] comme gait_control (viser ~0,45, pas 0,10).
class StepIn(BaseModel):
    linear_x: float = 0.0
    linear_y: float = 0.0
    angular_z: float = 0.0
    steps: int = 1


@app.post("/api/step")
async def step(p: StepIn):
    """Avance/tourne d'un nombre borné de foulées (gait_step_move)."""
    if state.safety["tripped"]:
        raise HTTPException(423, f"Sécurité déclenchée : {state.safety['reason']}. "
                                 f"Réarmer via POST /api/safety/clear.")
    clamp = lambda v: max(-1.0, min(1.0, float(v)))
    charge = {"linear_x": clamp(p.linear_x), "linear_y": clamp(p.linear_y),
              "angular_z": clamp(p.angular_z), "steps": max(1, min(20, int(p.steps)))}
    r = await link.request(CMD_STEP, charge)
    out = _wrap(r, CMD_STEP)
    out["envoye"] = charge
    return out


# ═══════════════════ passe-plats REST (unified_api_node :8088) ═══════════════════
@app.get("/api/logs")
async def logs():
    """Journaux du robot, sans SSH (REST 8088)."""
    if not state.robot_ip:
        raise HTTPException(503, "Robot non connecté")
    url = f"http://{state.robot_ip}:{ROBOT_REST_PORT}/api/v1/logs/"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.get(url)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Logs injoignables : {e}")
    return JSONResponse(status_code=r.status_code, content=_json_or_text(r))


@app.post("/api/ai/clear_history")
async def ai_clear_history():
    """Réinitialise la mémoire du dialogue IA (REST 8088)."""
    if not state.robot_ip:
        raise HTTPException(503, "Robot non connecté")
    url = f"http://{state.robot_ip}:{ROBOT_REST_PORT}/api/v1/ai/character/clear-history"
    try:
        async with httpx.AsyncClient(timeout=6) as c:
            r = await c.post(url)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"Requête impossible : {e}")
    return JSONResponse(status_code=r.status_code, content=_json_or_text(r))


# ═══════════════════════════════ volume audio ═══════════════════════════════
# Le volume est un PARAMÈTRE ROS `audio_volume` (entier 0-100) du nœud
# `wmix_audio_player_node`, réglé par la commande USER_SET_NODE_PARAMETER.
# Trame capturée le 28/07 sur l'interface officielle Hengbot (WebSocket 8765) :
#   {"type":"request","request_type":"USER_SET_NODE_PARAMETER",
#    "data":{"node_name":"wmix_audio_player_node",
#            "parameter_name":"audio_volume","parameter_value":54}}
CMD_SET_NODE_PARAM = "USER_SET_NODE_PARAMETER"   # ✅ capturé sur l'appli officielle
CMD_GET_NODE_PARAM = "USER_GET_NODE_PARAMETER"   # ⏳ symétrique, non capturé
AUDIO_NODE = "wmix_audio_player_node"
AUDIO_PARAM = "audio_volume"


class VolumeIn(BaseModel):
    value: int                                   # 0-100


@app.get("/api/volume")
async def get_volume():
    """Lit le volume audio courant (0-100). Symétrique du set — non capturé,
    donc l'extraction de la valeur est tolérante à la forme de la réponse."""
    r = await link.request(CMD_GET_NODE_PARAM,
                           {"node_name": AUDIO_NODE, "parameter_name": AUDIO_PARAM})
    out = _wrap(r, CMD_GET_NODE_PARAM)
    d = r.get("data") or {}
    out["value"] = d.get("parameter_value", d.get("value"))
    return out


@app.post("/api/volume")
async def set_volume(p: VolumeIn):
    """Règle le volume audio (0-100). Commande vérifiée sur l'interface officielle."""
    v = max(0, min(100, int(p.value)))
    r = await link.request(CMD_SET_NODE_PARAM,
                           {"node_name": AUDIO_NODE, "parameter_name": AUDIO_PARAM,
                            "parameter_value": v})
    out = _wrap(r, CMD_SET_NODE_PARAM)
    out["value"] = v
    return out


# vit à côté de ce script ; le montage de l'interface React, plus bas, ne la
# voit pas puisque cette route est déclarée avant lui.
DEAMB_PAGE = Path(__file__).resolve().parent / "deambulation.html"


@app.get("/deambulation")
async def deambulation_page():
    if not DEAMB_PAGE.is_file():
        raise HTTPException(404, "deambulation.html absent du dossier du kit")
    return FileResponse(str(DEAMB_PAGE), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


# L'éditeur d'enchaînements de comportement (« Play Blocks »), servi comme la
# page de déambulation : autonome, à côté de ce script.
ENCHAIN_PAGE = Path(__file__).resolve().parent / "enchainements.html"


@app.get("/enchainements")
async def enchainements_page():
    if not ENCHAIN_PAGE.is_file():
        raise HTTPException(404, "enchainements.html absent du dossier du kit")
    return FileResponse(str(ENCHAIN_PAGE), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


YEUX_PAGE = Path(__file__).resolve().parent / "yeux.html"
TABLEAU_PAGE = Path(__file__).resolve().parent / "tableau.html"
ACCUEIL_PAGE = Path(__file__).resolve().parent / "accueil.html"


@app.get("/accueil")
async def accueil_page():
    if not ACCUEIL_PAGE.is_file():
        raise HTTPException(404, "accueil.html absent du dossier du kit")
    return FileResponse(str(ACCUEIL_PAGE), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/yeux")
async def yeux_page():
    if not YEUX_PAGE.is_file():
        raise HTTPException(404, "yeux.html absent du dossier du kit")
    return FileResponse(str(YEUX_PAGE), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


@app.get("/tableau")
async def tableau_page():
    if not TABLEAU_PAGE.is_file():
        raise HTTPException(404, "tableau.html absent du dossier du kit")
    return FileResponse(str(TABLEAU_PAGE), media_type="text/html; charset=utf-8",
                        headers={"Cache-Control": "no-store"})


# ═══════════════════ interface web servie par le helper ═══════════════════
# Si un dossier « ui/ » est présent à côté de ce fichier, on sert le front
# dessus : une seule chose à lancer, une seule adresse à ouvrir.
# ⚠ Ce montage doit rester APRÈS toutes les routes /api, sinon il les capterait.
UI_DIR = Path(__file__).resolve().parent / "ui"


class UiFiles(StaticFiles):
    """StaticFiles + une politique de cache explicite.

    Leçon du 26/07 : après une mise à jour du kit, le navigateur continuait de
    servir son ancien « index.html » depuis le cache. Comme cet index désigne les
    bundles par leur nom haché, il rechargeait aussi l'ANCIEN JavaScript — donc
    une interface périmée, alors que le numéro de version affiché (lu par l'API)
    était bien le nouveau. Symptôme parfaitement trompeur : « je suis en 2.4 mais
    les nouveautés ne sont pas là. »

    La règle : le HTML n'est jamais mis en cache, les fichiers hachés le sont
    pour toujours (leur nom change à chaque build, donc aucun risque).
    """

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        chemin = str(getattr(resp, "path", "") or "")
        # Le manifeste rejoint le HTML côté « jamais en cache » : il porte le
        # nom, les couleurs et la liste des icônes de l'application installée,
        # et un manifeste périmé fige ces valeurs sur le téléphone.
        if (chemin.endswith((".html", ".htm")) or chemin.endswith("index.html")
                or chemin.endswith("manifest.json")):
            resp.headers["Cache-Control"] = "no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
        elif "/assets/" in chemin.replace("\\", "/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


if UI_DIR.is_dir():
    app.mount("/", UiFiles(directory=str(UI_DIR), html=True), name="ui")


def _ip_lan():
    """Adresse IPv4 du PC sur le réseau local, pour l'afficher au démarrage en
    mode réseau. Le socket UDP ne transmet aucune donnée : il sert seulement à
    savoir quelle interface le système utiliserait pour sortir."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return None
    finally:
        s.close()


def main():
    global link
    ap = argparse.ArgumentParser(description=f"Helper local de {APP_NAME} ({APP_SHORT}). "
                                             f"{APP_NOTICE}")
    ap.add_argument("--robot", default=None,
                    help="IP du robot. Optionnel : sans lui, l'adresse se saisit dans l'interface.")
    ap.add_argument("--port", type=int, default=8787, help="port local du helper")
    ap.add_argument("--host", default="127.0.0.1",
                    help="interface d'écoute. 127.0.0.1 = ce PC uniquement (défaut) ; "
                         "0.0.0.0 = joignable depuis le réseau local, p.ex. un téléphone "
                         "(voir demarrer_telephone.bat). En 0.0.0.0 le pilotage est exposé "
                         "à tout le Wi-Fi, sans mot de passe.")
    ap.add_argument("--no-safety", action="store_true", help="désactive le coupe-circuit (déconseillé)")
    ap.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur au démarrage")
    args = ap.parse_args()

    if args.no_safety:
        state.safety["enabled"] = False
        print("⚠ coupe-circuit moteurs DÉSACTIVÉ")

    link = RobotLink(args.robot)
    if args.robot is None:
        cible = "aucune — à choisir dans l'interface"
    elif args.robot in ("127.0.0.1", "localhost"):
        cible = "SIMULATEUR"
    else:
        cible = f"ROBOT RÉEL {args.robot}"
    print(f"{APP_NAME} v{VERSION} — helper local  (docs : /docs)")
    print(f"  {APP_SHORT} · {APP_NOTICE} L'application officielle du robot est")
    print("           celle de Hengbot ; ceci est un reverse d'explorations360.")
    print(f"  cible   : {cible}")
    print(f"  sécurité: {SAFETY_LOAD_THRESHOLD} ‰ soutenus {SAFETY_SUSTAIN_S} s → arrêt automatique")
    reseau = args.host not in ("127.0.0.1", "localhost")
    if UI_DIR.is_dir():
        print(f"  interface: http://127.0.0.1:{args.port}  ← ouvre cette adresse (sur ce PC)")
        if reseau:
            ip = _ip_lan()
            if ip:
                print(f"             http://{ip}:{args.port}  ← à ouvrir sur le téléphone (même Wi-Fi)")
            else:
                print(f"             (adresse LAN introuvable — regarde l'IP Wi-Fi du PC, port {args.port})")
    else:
        print("  interface: dossier ui/ absent → API seule (docs sur /docs)")
    if reseau:
        print("  ⚠ MODE RÉSEAU : le pilotage du robot est accessible à TOUT le Wi-Fi,")
        print("    sans mot de passe. À n'utiliser que sur un réseau de confiance.")
        print("    Le coupe-circuit reste actif ; ferme cette fenêtre pour tout couper.")
    if not args.no_browser:
        import threading, webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{args.port}")).start()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
