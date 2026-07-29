#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deambulation.py — déambulation autonome avec évitement, À BORD du Sirius
========================================================================

⚠️  À LIRE AVANT DE LANCER — CE PROGRAMME FAIT MARCHER UN ROBOT TOUT SEUL
────────────────────────────────────────────────────────────────────────
    SOL PLAT UNIQUEMENT, ET RIEN D'AUTRE.

    · Sur un sol plan et dégagé. Jamais sur une table, un plan de travail,
      un lit, ni à proximité d'un escalier, d'une marche, d'une estrade ou
      de quelque dénivelé que ce soit.
    · Le robot détecte les obstacles devant lui et sait, en principe, voir
      le vide — mais CETTE DÉTECTION DU VIDE N'A JAMAIS ÉTÉ ÉPROUVÉE au
      bord d'un vrai dénivelé. Ne comptez pas dessus. Elle ne remplace pas
      votre surveillance.
    · Il ne voit RIEN derrière lui, ni sur les côtés au-delà de son champ.
    · Restez à portée de main, prêt à le rattraper ou à couper.

    Par défaut ce programme NE FAIT RIEN BOUGER : il observe, décide, et
    écrit ce qu'il aurait fait. Il faut le lui demander explicitement, par
    « --marche » ou par le bouton Démarrer de Studio 360.

    Fourni sans garantie. Vous êtes seul responsable de votre machine et
    de ce qui l'entoure.
────────────────────────────────────────────────────────────────────────

Pourquoi à bord : le capteur ToF n'existe que sur ROS, il n'est pas exposé
sur le WebSocket. Une boucle qui tournerait sur le PC devrait faire un
aller-retour Wi-Fi par décision — inacceptable pour de l'évitement.

Ce que le robot fournit (relevé le 25/07) :

  /state_sensor/tof/distance_array   state_sensor_tof/msg/ToFDistanceArray
      16 distances en MILLIMÈTRES, portée 11-2047, 2047 = pas de cible.
      Grille 4×4, origine EN BAS À GAUCHE :

            haut   [12][13][14][15]
                   [ 8][ 9][10][11]
                   [ 4][ 5][ 6][ 7]
            bas    [ 0][ 1][ 2][ 3]
                    gche        drte

      Cadence mesurée : ~38 Hz.

  /gait_generation_trot/cmd_vel        geometry_msgs/msg/Twist   (marche)
  /gait_generation_trot/filtered_velocity                        (retour)
  /state_sensor/imu_onbody/imu_publisher/imu_data                (assiette)
  /action_player/current_posture                                 (debout ?)
  /internal_sensor/battery_onbody/battery_publisher/state        (batterie)

OÙ EST LE CAPTEUR — localisé le 25/07, à la main : **sous le cou, en haut
du poitrail**. Solidaire du CORPS, donc, et non de la tête (basculer la
tête de 17° ne déplace les distances que de 1 à 2 mm).

Deux conséquences, une bonne et une gênante.

Bonne : la géométrie ne dépend que de l'assiette du corps, régulée par le
générateur de démarche. Aucun angle de tête à suivre, et la tête reste
libre de regarder ailleurs pour la caméra.

Gênante : placé si haut et si en avant, le capteur a ses PROPRES PATTES
AVANT dans le bas de son champ. Au repos elles occultent partiellement les
zones 0-3 (une main passée devant ne les fait chuter que de 18 %, contre
80 % pour les rangées hautes). Et en marchant, elles BALANCENT : elles
entrent et sortent du champ à chaque foulée.

C'est la raison principale pour laquelle le fond doit être appris EN
MARCHANT. Une référence prise à l'arrêt, pattes immobiles, ferait passer
la première foulée pour un obstacle surgi de nulle part.

LECTURE DU CHAMP — c'est toute la finesse de ce capteur. Le robot étant
posé au sol, les rangées BASSES voient le PLANCHER à
distance croissante (≈200 mm, ≈295 mm, ≈780 mm) et les rangées HAUTES
voient l'infini (2047). Donc :

  · un OBSTACLE devant   → les rangées hautes cessent de valoir 2047,
                           et/ou les rangées basses raccourcissent ;
  · un VIDE devant (bord de table, marche) → les rangées basses, qui
                           voyaient le sol, passent brutalement à 2047.

La détection de vide est donc GRATUITE, avec le capteur d'origine. C'est
la protection la plus importante de tout ce fichier : c'est elle qui
empêche le robot de tomber d'une table.

⚠️ PAR DÉFAUT, CE NŒUD NE FAIT RIEN BOUGER. Il observe, décide, et écrit
ce qu'il aurait fait. Il faut « --marche » pour qu'il publie réellement
des consignes — et on ne le fera qu'après avoir lu ses décisions au sol,
robot surveillé.

    python3 deambulation.py                 # observation seule
    python3 deambulation.py --marche        # il avance pour de vrai
    python3 deambulation.py --duree 60      # arrêt automatique après 60 s
"""

import argparse
import json
import math
import queue
import signal
import threading
import time
import uuid
from collections import deque

# Annoncée au démarrage. Leçon du 25/07 : une session entière a été menée
# avec une version périmée du fichier sans que personne s'en aperçoive —
# les corrections étaient sur le PC, pas sur le robot. Un numéro affiché
# en première ligne rend la confusion impossible.
VERSION = "16 — anticipation vide : arrêt immédiat + bord franc diagonale à 1 zone (29/07)"

# ═══════════════════════════ géométrie du capteur ═══════════════════════════
HORS_PORTEE = 2047        # mm : le capteur ne voit rien d'assez proche
PORTEE_MIN = 11           # mm : plancher de la plage utile

# Index des zones par rangée, de bas en haut (origine en bas à gauche).
RANGEE_BAS = (0, 1, 2, 3)        # voit le sol juste devant les pattes
RANGEE_BASSE = (4, 5, 6, 7)      # sol un peu plus loin
RANGEE_HAUTE = (8, 9, 10, 11)    # sol lointain, ou obstacle bas
RANGEE_HAUT = (12, 13, 14, 15)   # l'horizon : tout obstacle vertical

# Colonnes, de gauche à droite (vues du robot).
COL_GAUCHE = (0, 4, 8, 12)
COL_CENTRE_G = (1, 5, 9, 13)
COL_CENTRE_D = (2, 6, 10, 14)
COL_DROITE = (3, 7, 11, 15)

MOITIE_GAUCHE = COL_GAUCHE + COL_CENTRE_G
MOITIE_DROITE = COL_CENTRE_D + COL_DROITE

# ═══════════════════════════════ réglages ═══════════════════════════════
# ⚠️ Détection RELATIVE, et non absolue. Première leçon du terrain : selon
# l'inclinaison de la tête, le plancher occupe une part variable du champ —
# parfois la totalité. Un seuil absolu prend donc le sol pour un obstacle.
# On apprend le FOND (ce que le robot voit à l'arrêt, sol compris) et on ne
# réagit qu'aux ÉCARTS : ce qui raccourcit est un obstacle, ce qui s'allonge
# est un vide. Cela rend la détection indifférente à la posture de la tête.
# Un obstacle doit être NOUVEAU *et* PROCHE. La détection relative dit
# « quelque chose a changé » ; sans critère de distance, le moindre meuble à
# 60 cm arrêtait le robot — et dans une pièce meublée, il y a toujours quelque
# chose quelque part, donc il tournait sans fin sans jamais trouver d'issue.
# Le robot mesure ~30 cm : en deçà de 45 cm, l'objet est vraiment sur sa route.
SEUIL_OBSTACLE = 450       # mm : au-delà, on voit l'objet mais on continue
# La marge ne peut pas être une constante. Une zone dont le fond est à 200 mm
# ne peut pas raccourcir de 120 mm sans que l'objet soit à 8 cm — autant dire
# collé. Résultat : dans la v11, les rangées BASSES ne pouvaient MATHÉMATIQUE-
# MENT jamais signaler quoi que ce soit, et toute la détection reposait sur le
# haut du champ. D'où une marge proportionnelle au fond, bornée des deux côtés.
MARGE_OBSTACLE = 120       # mm : plafond de la marge, pour les zones lointaines
MARGE_MINI = 50            # mm : plancher, pour ne pas réagir au bruit
MARGE_PART = 0.30          # part du fond retenue comme marge
SEUIL_ABSOLU = 250         # mm : si près, c'est un obstacle même sans référence
SEUIL_RECUL = 200          # mm : trop près pour tourner sur place → on recule
# ── Départage GAUCHE / DROITE quand les deux côtés se valent ────────────────
# Remarque de Phil (28/07) : à l'évitement, le robot partait presque toujours
# sur sa gauche. La cause n'était pas la mesure — elle fuit bien le côté le
# plus chargé — mais le DÉPARTAGE des cas symétriques : obstacle bien centré,
# détection d'un vide, ou rien de vraiment latéralisé. Dans ces cas gauche et
# droite s'équivalent, et l'ancien code retombait TOUJOURS du même côté (le
# « else » valait gauche). Désormais, en deçà de ce seuil d'écart cumulé, on
# considère les deux moitiés équivalentes et on ALTERNE le sens d'une manœuvre
# à l'autre, au lieu de repartir systématiquement à gauche.
SEUIL_SYMETRIE = 80        # mm cumulés : en deçà, les deux moitiés s'équivalent
# ── La réponse est GRADUÉE, du plus doux au plus brutal ────────────────────
# Jusqu'à la v12 tout obstacle confirmé provoquait un pivot sur place, moteurs
# à l'arrêt : brutal, et inutile quand l'objet est encore loin. Désormais :
#
#   obstacle entre SEUIL_CONTOURNE et SEUIL_OBSTACLE → il CONTOURNE, c'est-à-
#       dire qu'il continue d'avancer en braquant du côté le plus dégagé ;
#   obstacle plus proche que SEUIL_CONTOURNE          → pivot sur place ;
#   obstacle plus proche que SEUIL_RECUL, ou coincé   → recul.
#
# On ne recule donc que si c'est vraiment nécessaire — le recul est aveugle,
# le robot ne voit rien derrière lui.
SEUIL_CONTOURNE = 300      # mm : au-dessus, on esquive sans cesser d'avancer
FACTEUR_CONTOURNE_V = 0.6  # on lève le pied pendant l'esquive
FACTEUR_CONTOURNE_W = 0.9  # sans braquer tout à fait autant qu'un pivot
CONTOURNE_MAX = 3.0        # s d'esquive sans dégagement → on pivote pour de bon

# ── Animation d'évitement (demande de Phil, 28/07) ─────────────────────────
# Quand le robot s'approche trop d'un obstacle, on peut lui faire jouer une
# ANIMATION de la bibliothèque (ex. « peer » curieux, « ponder » réflexion)
# AVANT de reculer — c'est plus expressif qu'un recul sec. Le Cerveau se
# contente d'ÉMETTRE une intention (self.anim_a_jouer) ; c'est la couche ROS
# qui la joue réellement, pour que decide() reste pur et testable au sol.
# Deux garde-fous : jamais d'animation pour un VIDE (on ne fige pas le robot au
# bord d'un dénivelé — cf. _anim_pour), et un cooldown pour ne pas la rejouer
# en boucle face à un obstacle tenace.
SEUIL_ANIM = 240           # mm : sous ce seuil, si une animation est assignée à
                           # « approche », on la joue avant de reculer (entre
                           # SEUIL_RECUL et SEUIL_CONTOURNE)
DUREE_ANIM = 2.5           # s : durée estimée d'une action ; borne l'état « anime »
                           # même si la fin d'action n'est pas signalée par le robot
ANIM_COOLDOWN = 8.0        # s : délai minimal entre deux animations (anti-boucle)

# ── Le masque anti-mâchoire ────────────────────────────────────────────────
# Signature relevée sur dix sessions : un « obstacle » à 191 mm en moyenne,
# écart-type 5 mm, qui surgit et disparaît sans que rien ne bouge devant le
# robot. La même valeur se retrouve figée dans l'enveloppe des zones HAUTES
# d'une session à l'autre (13 : 190-198, 15 : 193-193, 14 : 216-216).
#
# Ce n'est pas un obstacle : c'est la MÂCHOIRE du robot. Le capteur est sous
# le cou ; quand le corps tangue au trot, la tête entre par le haut du champ,
# toujours à la même distance puisqu'elle est solidaire de la machine.
#
# La parade doit rester ÉTROITE. Masquer tout ce qui est proche en haut du
# champ reviendrait à ignorer une étagère basse ou un plateau de table — des
# obstacles bien réels, et à hauteur de tête. On ne masque donc que la BANDE
# de distances où la mâchoire se manifeste, et seulement si rien ne corrobore
# en bas : un objet réellement là serait vu aussi par les rangées basses, qui
# regardent plus près et plus bas.
MASQUE_BANDE = (170, 225)  # mm : la signature de la mâchoire, et rien d'autre
FOND_LOINTAIN = 350        # mm : en deçà, une zone de fond regarde déjà le sol
MARGE_VIDE = 400           # mm : une zone de sol qui s'allonge de tant = un vide

# ── Qui a le droit de crier au vide ? ──────────────────────────────────────
# Deuxième leçon du terrain, et la plus coûteuse. Toutes les zones ne se
# valent pas :
#   · une zone qui ne voyait RIEN pendant l'apprentissage (saturée) n'a aucun
#     sol à perdre — sa saturation en navigation n'est pas un vide ;
#   · une zone qui ne s'est valorisée qu'une poignée de fois sur 900 trames
#     n'a pas de référence, elle a une aberration ;
#   · une zone qui voit le sol LOIN (60 cm et plus) ne peut pas distinguer un
#     trou d'une pièce qui s'ouvre au-delà de la portée de 2 m.
# Seules les zones qui voyaient le sol de PRÈS et de façon CONSTANTE sont
# admises à déclarer un vide. Les autres restent utiles pour les obstacles.
FIABILITE_MINI = 0.80      # part des trames d'apprentissage où la zone mesurait
SOL_PROCHE = 500           # mm : au-delà, on ne sait pas si c'est le sol
PERSISTANCE = 3            # cycles consécutifs avant d'agir (≈0,3 s à 10 Hz)
# ⚠️ UNITÉ CONFIRMÉE le 25/07 : /gait_generation_trot/cmd_vel attend une
# valeur NORMALISÉE dans [-1, 1], comme gait_control sur le WebSocket — et
# NON des m/s. Preuve : une consigne de 0,50 ressort telle quelle sur
# /filtered_velocity, or 0,50 dépasse la vitesse maximale déclarée du robot
# (0,24 m/s). À 0,10 il piétinait sans avancer ; à 0,50 il marche.
VITESSE_AVANT = 0.45       # fraction du débattement
VITESSE_ROTATION = 0.6     # rad/s
DUREE_ROTATION = 1.2       # s de rotation par décision d'évitement
ROTATION_MAX = 5.0         # s de rotation continue avant de conclure à un piège
DUREE_RECUL = 0.8          # s
# Le robot ne voit RIEN derrière lui. Reculer est donc une manœuvre aveugle :
# on la fait plus lentement que l'avance, et on la borne dans le temps. Sans
# cette borne, un obstacle tenace le faisait reculer plusieurs secondes
# d'affilée — il a traversé la pièce à l'envers plus d'une fois aujourd'hui.
FACTEUR_RECUL = 0.5        # le recul se fait à la moitié de la vitesse d'avance
RECUL_MAX = 1.5            # s de recul continu avant de tourner quoi qu'il arrive
BATTERIE_MINI = 0.15       # ratio : en dessous, on ne déambule plus
INCLINAISON_MAX = 0.45     # rad (~26°) : au-delà, le robot n'est pas d'aplomb
DERIVE_ASSIETTE = 0.10     # rad (~6°) d'écart au fond appris → géométrie douteuse
FRAICHEUR_MAX = 0.5        # s sans trame ToF → arrêt


def median(xs):
    """Médiane sans numpy — le robot n'a pas forcément numpy dans ce contexte."""
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


class Cerveau:
    """
    La décision, isolée de ROS — donc testable au sol, sans robot.

    Il n'y a volontairement AUCUNE carte, aucune odométrie : c'est de
    l'errance réactive. Le robot ne sait pas où il est, il sait seulement
    ce qu'il a devant lui à l'instant présent. C'est suffisant pour
    déambuler sans rien heurter, et c'est honnête sur ce que le matériel
    permet — sans lidar, prétendre cartographier serait un mensonge.
    """

    def __init__(self, vitesse=None, rotation=None, animations=None):
        # Bug de la v7 : --vitesse existait mais n'était lu nulle part, la
        # constante du module s'appliquait quoi qu'on demande.
        self.vitesse = VITESSE_AVANT if vitesse is None else float(vitesse)
        self.vitesse_recul = self.vitesse * FACTEUR_RECUL
        self.rotation = VITESSE_ROTATION if rotation is None else float(rotation)
        self.reference_sol = None   # médiane par zone
        self.enveloppe = None       # (min, max) par zone — voir apprend_le_sol
        self.fiabilite = {}         # part des trames où la zone mesurait vraiment
        self.eligibles_vide = set() # zones admises à déclarer un vide
        self._compteur_vide = 0     # persistance temporelle
        self._compteur_obst = 0
        self._rotation_depuis = None   # début de la rotation en cours
        self._recul_depuis = None      # début du recul en cours
        self._contourne_depuis = None  # début du contournement en marche
        self._reoriente_vide_depuis = None  # pivot de réorientation après recul-vide trop long
        self.assiette_ref = None    # tangage du CORPS au moment de l'apprentissage
        self.geometrie_douteuse = False
        self.etat = "attente"
        self.depuis = time.monotonic()
        self.motif = "démarrage"
        self.sens_rotation = 1.0    # +1 = vers la gauche
        # Sens retenu quand les deux côtés s'équivalent (obstacle centré, vide,
        # rien de latéralisé). On l'ALTERNE à la fin de chaque manœuvre pour ne
        # plus repartir toujours du même côté — le biais gauche relevé par Phil.
        # Il démarre à droite (−1), à l'opposé de l'ancien réflexe gauche.
        self._sens_defaut_symetrie = -1.0
        # Animations d'évitement : mapping événement → nom d'action (ou None).
        # `anim_a_jouer` est l'INTENTION one-shot lue puis remise à None par la
        # couche ROS ; `_anim_derniere_a` horodate la dernière pour le cooldown.
        self.animations = dict(animations or {})
        self.anim_a_jouer = None
        self._anim_derniere_a = -1e9
        self.historique = deque(maxlen=8)

    # ---------- lecture du champ ----------
    @staticmethod
    def _valides(grille, idx):
        """Distances exploitables d'un groupe de zones (hors saturation)."""
        return [grille[i] for i in idx
                if grille[i] is not None and PORTEE_MIN <= grille[i] < HORS_PORTEE]

    def apprend_le_sol(self, grilles, assiette=None):
        """
        Mémorise ce que le robot voit — LES SEIZE ZONES, sous forme
        d'ENVELOPPE (min, médiane, max) et non d'une valeur unique.

        Pourquoi une enveloppe : l'orientation du capteur ne dépend pas que
        de la tête, elle dépend aussi de l'assiette du CORPS. À l'arrêt le
        corps est figé ; en marchant, le trot le fait tanguer à chaque
        foulée, et les distances au plancher oscillent d'autant. Une
        référence ponctuelle prise à l'arrêt déclencherait donc de faux
        obstacles au premier pas.

        Apprendre l'enveloppe PENDANT LA MARCHE absorbe cette oscillation :
        on ne retient plus « le sol est à 198 mm » mais « le sol oscille
        entre 176 et 221 mm ». Tout ce qui sort de cette bande est réel.

        On mémorise aussi l'assiette du corps : si elle dérive trop par la
        suite, la géométrie n'est plus celle de l'apprentissage et on cesse
        de faire confiance à la détection de vide.
        """
        profil, env, fia = {}, {}, {}
        total = max(1, len(grilles))
        for i in range(16):
            vals = [g[i] for g in grilles
                    if g[i] is not None and PORTEE_MIN <= g[i] < HORS_PORTEE]
            fia[i] = len(vals) / total
            if vals:
                profil[i] = median(vals)
                env[i] = (min(vals), max(vals))
            else:
                profil[i] = None
                env[i] = None
        self.reference_sol = profil
        self.enveloppe = env
        self.fiabilite = fia
        self.assiette_ref = assiette
        # Une zone n'est admise à déclarer un vide que si elle voyait le sol
        # PRESQUE TOUJOURS et de PRÈS. Sans ce filtre, les zones lointaines
        # saturées passent leur temps à annoncer des précipices imaginaires.
        # Restriction géométrique en plus des critères statistiques : seules
        # les DEUX RANGÉES BASSES peuvent voir le plancher devant le robot. Les
        # rangées hautes regardent l'horizon — et, sur ce robot, la mâchoire :
        # l'enveloppe du 25/07 leur donnait ~200 mm constants, ce qui est la
        # tête elle-même. Les admettre au vote reviendrait à déclarer un
        # précipice chaque fois que la tête bouge.
        self.eligibles_vide = {
            i for i in (RANGEE_BAS + RANGEE_BASSE)
            if env[i] is not None and fia[i] >= FIABILITE_MINI and env[i][1] < SOL_PROCHE
        }
        return profil

    def _ecart(self, grille, i):
        """
        De combien la zone i s'est-elle RACCOURCIE par rapport au fond ?
        Renvoie None si la comparaison n'a pas de sens.
        """
        d = grille[i]
        if d is None or not (PORTEE_MIN <= d < HORS_PORTEE):
            return None
        env = (self.enveloppe or {}).get(i)
        if env is None:
            # zone qui ne voyait rien : toute mesure y est une apparition
            return HORS_PORTEE - d
        # on compare au PLUS PROCHE que le fond ait jamais été : ainsi
        # l'oscillation de la marche ne compte pas comme un rapprochement
        return env[0] - d

    def _marge(self, i):
        """Marge de détection de la zone i, proportionnée à son fond."""
        env = (self.enveloppe or {}).get(i)
        if env is None:
            return MARGE_OBSTACLE
        return max(MARGE_MINI, min(MARGE_OBSTACLE, env[0] * MARGE_PART))

    def _zones_alertees(self, grille, zones):
        """Zones du groupe qui signalent quelque chose de nouveau ET de proche."""
        out = []
        for i in zones:
            d = grille[i]
            if d is None or not (PORTEE_MIN <= d < HORS_PORTEE):
                continue
            e = self._ecart(grille, i)
            ref = (self.reference_sol or {}).get(i)
            if d > SEUIL_OBSTACLE:
                continue                     # trop loin pour gêner : on le laisse
            proche_dans_l_absolu = (d < SEUIL_ABSOLU and
                                    (ref is None or ref > FOND_LOINTAIN))
            if (e is not None and e > self._marge(i)) or proche_dans_l_absolu:
                out.append((i, d))
        return out

    def obstacle(self, grille, detail=False):
        """
        Distance à l'obstacle le plus proche, ou None si la voie est libre.

        Un obstacle, c'est une zone qui s'est raccourcie par rapport au fond
        appris — pas une zone « proche ». Le sol est proche en permanence et
        ne doit jamais déclencher. Et une alerte isolée en haut du champ, à
        entre %d et %d mm, est la mâchoire du robot : on l'ignore si rien ne
        la corrobore en bas.
        """ % MASQUE_BANDE
        bas = self._zones_alertees(grille, RANGEE_BAS + RANGEE_BASSE)
        haut = self._zones_alertees(grille, RANGEE_HAUTE + RANGEE_HAUT)
        if not bas:
            haut = [(i, d) for i, d in haut
                    if not (MASQUE_BANDE[0] <= d <= MASQUE_BANDE[1])]
        retenus = bas + haut
        if not retenus:
            return ([], None) if detail else None
        d = min(d for _, d in retenus)
        return (sorted(i for i, _ in retenus), d) if detail else d

    def urgence(self, grille):
        """
        Faut-il reculer plutôt que tourner ?

        La question n'est pas « qu'est-ce qui a changé » — ça, `obstacle()`
        y a déjà répondu — mais « ai-je la place de pivoter ». En dessous de
        %d mm, tourner sur place ferait racler le museau : on recule d'abord.
        """ % SEUIL_RECUL
        d = self.obstacle(grille)
        return d is not None and d < SEUIL_RECUL

    def vide(self, grille):
        """
        Le sol a-t-il disparu ? Une zone qui voyait le plancher et qui ne
        voit plus rien signale un bord de table ou une marche.
        """
        if not self.reference_sol:
            return []
        if self.geometrie_douteuse:
            # le corps n'est plus dans l'assiette d'apprentissage : les
            # distances au sol ont changé pour une raison géométrique, pas
            # parce qu'un vide est apparu. Mieux vaut ne rien affirmer.
            return []
        perdues = []
        for i in sorted(self.eligibles_vide):
            env = (self.enveloppe or {}).get(i)
            d = grille[i]
            if env is None or d is None:
                continue
            if d >= HORS_PORTEE or d > env[1] + MARGE_VIDE:
                perdues.append(i)

        # Corroboration : un vrai bord de table efface toute une rangée.
        # Une zone isolée qui décroche, c'est un reflet, une moquette sombre,
        # une surface trop inclinée pour renvoyer l'infrarouge. On l'ignore,
        # sinon le robot recule sans cesse pour rien.
        #
        # ⚠️ On compte sur les DEUX rangées basses (0-7), pas seulement la
        # toute première. Mesure du 25/07 : une main passée devant le capteur
        # ne fait chuter la rangée 0-3 que de 18 %, contre 80 % pour les
        # rangées hautes. Cette rangée est en grande partie occultée par le
        # robot lui-même ; s'y fier seule pour détecter un vide serait bâtir
        # la sécurité la plus importante sur les zones les moins fiables.
        en_bas = sum(1 for i in perdues if i in RANGEE_BAS + RANGEE_BASSE)
        # Bord FRANC : une zone basse fiable qui ne renvoie plus RIEN (aucune
        # cible) a perdu le sol pour de bon — un vrai bord, pas un reflet. En
        # approche DIAGONALE le vide n'apparaît d'abord que dans UN seul coin :
        # exiger deux zones le laissait passer, et le robot basculait. Le sol
        # normal ne sature jamais une zone fiable, donc ce critère ne crée pas de
        # faux positifs en navigation à plat. La persistance (PERSISTANCE cycles,
        # cf. decide) reste exigée avant d'agir.
        francs_bas = sum(1 for i in perdues if i in RANGEE_BAS + RANGEE_BASSE
                         and (grille[i] is None or grille[i] >= HORS_PORTEE))
        if francs_bas >= 1 or en_bas >= 2 or len(perdues) >= 3:
            return perdues
        return []

    def _anim_pour(self, evenement, maintenant):
        """
        Nom d'animation à jouer pour un événement d'évitement, ou None.

        Deux garde-fous durs, ici et pas ailleurs pour qu'ils soient testables :
        · JAMAIS d'animation pour un « vide » — on ne fige pas le robot au bord
          d'un dénivelé, quoi que l'utilisateur ait configuré ;
        · cooldown : pas de nouvelle animation tant que ANIM_COOLDOWN n'est pas
          écoulé, pour ne pas la rejouer en boucle face à un obstacle tenace.
        """
        if evenement == "vide":
            return None
        nom = (self.animations or {}).get(evenement)
        if not nom:
            return None
        if maintenant - self._anim_derniere_a < ANIM_COOLDOWN:
            return None
        return nom

    def cote_le_plus_libre(self, grille):
        """
        +1 pour la gauche, -1 pour la droite : on fuit le côté le plus
        encombré, mesuré en écart cumulé au fond — même raisonnement que
        pour la détection, donc insensible à la posture de la tête.

        L'encombrement d'une zone est BORNÉ à sa proximité absolue
        (SEUIL_OBSTACLE − distance). Sans cette borne, une zone qui n'avait
        pas de fond de référence (elle ne voyait que du vide à l'apprentissage)
        pesait `HORS_PORTEE − distance` ≈ 1600 mm, écrasant le vrai signal des
        zones qui voient le sol (quelques centaines de mm). Comme, sur ce
        robot, ces zones-là sont surtout à DROITE, tout obstacle frontal
        paraissait « bien plus chargé à droite » et le robot fuyait toujours à
        gauche : le biais relevé par Phil (28/07). Bornée à la proximité, la
        mesure est à la même échelle partout, et le sol — symétrique — se
        compense entre les deux moitiés.

        Cas SYMÉTRIQUE (obstacle bien centré, vide, ou rien de latéralisé) :
        les deux moitiés s'équivalent, à SEUIL_SYMETRIE près. On ne retombe
        alors PLUS toujours à gauche : on renvoie le sens de départage courant,
        ALTERNÉ d'une manœuvre à l'autre (voir _passe). Ce sens reste STABLE
        pendant une même manœuvre — pas recalculé au bruit près à chaque
        cycle —, donc pas de tremblement quand un obstacle centré est esquivé.
        """
        def encombrement(idx):
            total = 0.0
            for i in idx:
                d = grille[i]
                if d is None or not (PORTEE_MIN <= d < HORS_PORTEE):
                    continue
                if d >= SEUIL_OBSTACLE:
                    continue                     # trop loin pour peser
                plafond = SEUIL_OBSTACLE - d     # proximité absolue = borne haute
                env = (self.enveloppe or {}).get(i)
                if env is None:
                    total += plafond             # pas de fond : la proximité seule
                else:
                    total += min(max(0.0, env[0] - d), plafond)
            return total

        g = encombrement(MOITIE_GAUCHE)
        d = encombrement(MOITIE_DROITE)
        if abs(g - d) <= SEUIL_SYMETRIE:
            return self._sens_defaut_symetrie   # côtés équivalents : on alterne
        return -1.0 if g > d else 1.0   # plus encombré à gauche → on tourne à droite

    # ---------- machine à états ----------
    def decide(self, grille, maintenant, contexte):
        """
        Renvoie (vx, wz, etat, motif). vx en m/s, wz en rad/s.
        `contexte` porte les sécurités : batterie, inclinaison, fraîcheur.
        """
        # 1. les refus catégoriques passent avant toute logique de navigation
        if contexte.get("fraicheur", 0) > FRAICHEUR_MAX:
            return self._fige("capteur muet depuis %.1f s" % contexte["fraicheur"])
        if contexte.get("batterie") is not None and contexte["batterie"] < BATTERIE_MINI:
            return self._fige("batterie sous %d %%" % int(BATTERIE_MINI * 100))
        if contexte.get("inclinaison") is not None and abs(contexte["inclinaison"]) > INCLINAISON_MAX:
            return self._fige("robot pas d'aplomb (%.2f rad)" % contexte["inclinaison"])
        if contexte.get("posture") not in (None, "stand", "standing", "debout"):
            return self._fige("posture « %s » — il faut être debout" % contexte["posture"])

        # L'assiette du corps a-t-elle dérivé depuis l'apprentissage ? Si oui,
        # le capteur ne regarde plus le même endroit du sol : on suspend la
        # détection de vide plutôt que de crier au loup. (Remarque de Phil :
        # l'angle de la tête ne suffit pas, il faut l'assiette du corps.)
        a, ar = contexte.get("inclinaison"), self.assiette_ref
        self.geometrie_douteuse = (a is not None and ar is not None
                                   and abs(a - ar) > DERIVE_ASSIETTE)

        # 2. le vide l'emporte sur tout le reste : c'est ce qui casse le robot.
        #    Mais on exige qu'il PERSISTE : à 38 Hz, une trame isolée est du
        #    bruit, pas un précipice. Trois cycles consécutifs (~0,3 s) suffisent
        #    à trancher, et c'est encore très en deçà du temps qu'il faut au
        #    robot pour parcourir la moindre distance à 0,10 m/s.
        perdues = self.vide(grille)
        self._compteur_vide = self._compteur_vide + 1 if perdues else 0
        if not perdues:
            self._reoriente_vide_depuis = None   # plus de vide : on oublie la réorientation
        # ANTICIPATION (anti-chute en diagonale) : dès qu'un vide est DÉTECTÉ mais
        # pas encore CONFIRMÉ par la persistance, on cesse d'avancer sur-le-champ.
        # Reculer serait aveugle si c'était une fausse alerte ; mais continuer
        # d'avancer vers un bord possible est précisément ce qui fait basculer le
        # robot en approche diagonale. Vitesse nulle le temps de trancher = sûr.
        if perdues and self._compteur_vide < PERSISTANCE and self._reoriente_vide_depuis is None:
            return self._passe("prudence", "vide possible devant — arrêt, confirmation en cours",
                               maintenant, 0.0, 0.0)
        if perdues and self._compteur_vide >= PERSISTANCE:
            # Le recul est AVEUGLE (rien derrière le robot). Même face à un vide
            # qui persiste, on ne recule pas indéfiniment vers l'arrière qu'on ne
            # voit pas : passé RECUL_MAX, on PIVOTE sur place — la rotation ne
            # translate pas, donc elle reste sûre au bord d'un dénivelé. Sans
            # cette borne (bug du 28/07), un bord devant ET derrière (petite
            # table) faisait reculer le robot jusqu'à la chute arrière, car cette
            # branche renvoyait « recule » à chaque cycle AVANT le garde-fou 3bis.
            #
            # Le pivot de réorientation est PROTÉGÉ pendant DUREE_ROTATION : tant
            # qu'il tourne, on ne le renvoie pas en marche arrière même si le vide
            # persiste (sans quoi il ne durerait qu'un cycle et ne réorienterait
            # rien). Une fois le pivot fini, si le vide est toujours là, on repart
            # pour un cycle recul→pivot — le robot finit par se détourner du bord.
            if self._reoriente_vide_depuis is not None:
                if maintenant - self._reoriente_vide_depuis < DUREE_ROTATION:
                    pass  # pivot en cours : on laisse la section 4 le poursuivre
                else:
                    self._reoriente_vide_depuis = None
            if self._reoriente_vide_depuis is None:
                if self.etat == "recule":
                    if self._recul_depuis is None:
                        self._recul_depuis = maintenant
                    if maintenant - self._recul_depuis > RECUL_MAX:
                        self._recul_depuis = None
                        self._reoriente_vide_depuis = maintenant
                        self.sens_rotation = self.cote_le_plus_libre(grille)
                        return self._passe("tourne",
                                           "vide devant mais recul trop long — on pivote",
                                           maintenant, 0.0, self.sens_rotation * self.rotation)
                self.sens_rotation = self.cote_le_plus_libre(grille)
                return self._passe("recule", "VIDE devant — zones %s" % perdues,
                                   maintenant, -self.vitesse_recul, 0.0)
            # sinon : réorientation en cours → on tombe dans la suite (section 4
            # fera tourner le robot jusqu'à la fin du pivot).

        # 2ter. animation d'évitement en cours : la démarche est à l'ARRÊT (gait
        #       nul) le temps que l'action se joue, PUIS on recule. Le VIDE
        #       (section 2, au-dessus) reste prioritaire et interrompt l'animation
        #       si un bord surgit. Bornée par DUREE_ANIM — le robot ne reste
        #       jamais figé même si la fin d'action n'est pas signalée.
        if self.etat == "anime":
            if maintenant - self.depuis < DUREE_ANIM:
                return 0.0, 0.0, self.etat, self.motif
            return self._passe("recule", "fin d'animation — on recule",
                               maintenant, -self.vitesse_recul, 0.0)

        # 3bis. le recul est aveugle : on ne le laisse jamais s'éterniser.
        if self.etat == "recule":
            if self._recul_depuis is None:
                self._recul_depuis = maintenant
            if maintenant - self._recul_depuis > RECUL_MAX:
                self._recul_depuis = None
                self.sens_rotation = self.cote_le_plus_libre(grille)
                return self._passe("tourne", "recul trop long — on pivote",
                                   maintenant, 0.0, self.sens_rotation * self.rotation)
        else:
            self._recul_depuis = None

        # 3. quelque chose a surgi de très près : on recule avant de tourner.
        #    Même exigence de persistance : une aberration de mesure ne doit
        #    pas faire reculer un robot.
        zones_obst, d = self.obstacle(grille, detail=True)
        self._compteur_obst = self._compteur_obst + 1 if d is not None else 0
        confirme = d is not None and self._compteur_obst >= PERSISTANCE
        if confirme and d < SEUIL_ANIM:
            self.sens_rotation = self.cote_le_plus_libre(grille)
            # Une animation est-elle assignée à « approche » (et le cooldown
            # passé) ? Si oui, on la joue AVANT de reculer : on entre dans l'état
            # « anime » (gait nul), qui enchaînera le recul au bout de DUREE_ANIM.
            anim = self._anim_pour("approche", maintenant)
            if anim is not None:
                self.anim_a_jouer = anim
                self._anim_derniere_a = maintenant
                return self._passe("anime",
                                   "obstacle à %d mm — animation « %s » avant recul"
                                   % (d, anim), maintenant, 0.0, 0.0)
            # Pas d'animation (aucune assignée, ou cooldown) : comportement
            # historique — on ne recule que sous le seuil de recul.
            if d < SEUIL_RECUL:
                return self._passe("recule", "obstacle à %d mm (zones %s)" % (d, zones_obst),
                                   maintenant, -self.vitesse_recul, 0.0)

        # 3ter. contournement en cours : on avance en braquant tant que l'objet
        #       reste à distance. Trois façons d'en sortir — la voie se dégage,
        #       l'objet se rapproche (on cesse d'avancer), ou l'esquive s'éternise.
        if self.etat == "contourne":
            if self._contourne_depuis is None:
                self._contourne_depuis = maintenant
            depuis = maintenant - self._contourne_depuis
            if not confirme:
                self._contourne_depuis = None
                return self._passe("avance", "voie dégagée", maintenant,
                                   self.vitesse, 0.0)
            if d is not None and d < SEUIL_CONTOURNE:
                self._contourne_depuis = None
                self.sens_rotation = self.cote_le_plus_libre(grille)
                return self._passe("tourne", "obstacle à %d mm — trop près pour "
                                             "esquiver en marchant" % d,
                                   maintenant, 0.0,
                                   self.sens_rotation * self.rotation)
            if depuis > CONTOURNE_MAX:
                self._contourne_depuis = None
                self.sens_rotation = self.cote_le_plus_libre(grille)
                return self._passe("tourne", "esquive sans effet depuis %.0f s — "
                                             "on pivote" % depuis,
                                   maintenant, 0.0,
                                   self.sens_rotation * self.rotation)
            # on garde le cap d'esquive, en réévaluant le côté le plus dégagé
            self.sens_rotation = self.cote_le_plus_libre(grille)
            return (self.vitesse * FACTEUR_CONTOURNE_V,
                    self.sens_rotation * self.rotation * FACTEUR_CONTOURNE_W,
                    self.etat, self.motif)

        # 4. sorties temporisées des manœuvres en cours
        ecoule = maintenant - self.depuis
        if self.etat == "recule":
            if ecoule < DUREE_RECUL:
                return -self.vitesse_recul, 0.0, self.etat, self.motif
            return self._passe("tourne", "dégagement vers la %s" %
                               ("gauche" if self.sens_rotation > 0 else "droite"),
                               maintenant, 0.0, self.sens_rotation * self.rotation)
        if self.etat == "tourne":
            if self._rotation_depuis is None:
                self._rotation_depuis = maintenant
            tourne_depuis = maintenant - self._rotation_depuis

            # Anti-blocage : tourner sur place sans jamais trouver d'issue est
            # le piège classique de l'errance réactive — un coin de pièce suffit.
            # Passé ce délai, on recule pour changer de point de vue et on
            # repart dans l'autre sens.
            if tourne_depuis > ROTATION_MAX:
                self._rotation_depuis = None
                self.sens_rotation = -self.sens_rotation
                # Coincé pour de bon : si une animation est assignée à « bloque »,
                # on la joue avant de reculer et de changer de sens.
                anim = self._anim_pour("bloque", maintenant)
                if anim is not None:
                    self.anim_a_jouer = anim
                    self._anim_derniere_a = maintenant
                    return self._passe("anime", "coincé — animation « %s » puis recul"
                                       % anim, maintenant, 0.0, 0.0)
                return self._passe("recule", "rotation sans issue depuis %.0f s — "
                                             "on recule et on change de sens" % tourne_depuis,
                                   maintenant, -self.vitesse_recul, 0.0)

            if ecoule < DUREE_ROTATION:
                return 0.0, self.sens_rotation * self.rotation, self.etat, self.motif
            if self.obstacle(grille) is not None:
                # toujours bloqué : on prolonge la rotation (et on le DIT —
                # la v6 gardait l'ancien motif, d'où un journal trompeur)
                self.depuis = maintenant
                self.motif = "toujours bloqué (%.0f s)" % tourne_depuis
                return 0.0, self.sens_rotation * self.rotation, self.etat, self.motif
            self._rotation_depuis = None
            return self._passe("avance", "voie libre", maintenant, self.vitesse, 0.0)

        # 5. régime normal — la réponse est graduée : tant que l'objet est
        #    encore à distance, on l'esquive SANS cesser d'avancer.
        if confirme:
            self.sens_rotation = self.cote_le_plus_libre(grille)
            cote = "gauche" if self.sens_rotation > 0 else "droite"
            if d is not None and d >= SEUIL_CONTOURNE:
                return self._passe("contourne",
                                   "obstacle à %d mm (zones %s) — esquive par la %s"
                                   % (d, zones_obst, cote),
                                   maintenant, self.vitesse * FACTEUR_CONTOURNE_V,
                                   self.sens_rotation * self.rotation * FACTEUR_CONTOURNE_W)
            return self._passe("tourne", "obstacle à %d mm (zones %s) — évitement"
                               % (d, zones_obst),
                               maintenant, 0.0, self.sens_rotation * self.rotation)
        return self._passe("avance", "voie libre", maintenant, self.vitesse, 0.0)

    def _passe(self, etat, motif, maintenant, vx, wz):
        if etat != "tourne":
            self._rotation_depuis = None
        if etat != "contourne":
            self._contourne_depuis = None
        if etat != self.etat:
            # Fin d'une manœuvre d'évitement (retour à « avance ») : on prépare
            # le départage des cas SYMÉTRIQUES de la prochaine manœuvre en
            # l'alternant. Ainsi deux obstacles centrés successifs ne partent
            # plus du même côté — c'est ce qui corrige le biais gauche. Le sens
            # reste inchangé PENDANT la manœuvre (il n'est retouché qu'ici, au
            # passage à « avance »), donc l'esquive ne tremble pas.
            if etat == "avance" and self.etat in ("tourne", "contourne", "recule"):
                self._sens_defaut_symetrie = -self._sens_defaut_symetrie
            self.depuis = maintenant
            self.historique.append((round(maintenant, 2), etat, motif))
        self.etat, self.motif = etat, motif
        return vx, wz, etat, motif

    def _fige(self, motif):
        self.etat, self.motif = "arret", motif
        return 0.0, 0.0, "arret", motif


# ═══════════════════════ exécuteur d'animations (à bord) ═══════════════════════
# Le Cerveau ne fait qu'ÉMETTRE une intention (self.anim_a_jouer). C'est ici
# qu'elle est réellement jouée, dans un THREAD séparé : la boucle de décision à
# 10 Hz se contente de déposer un nom dans une file et ne bloque jamais sur le
# réseau.
#
# Pourquoi un WebSocket local et non ROS : il n'existe (au 28/07) aucune
# interface ROS confirmée pour jouer une action ARBITRAIRE de la bibliothèque
# avec une priorité. Le seul service, play_reset_action, ne joue que le
# redressement. On passe donc par le pont web du robot (ws://127.0.0.1:8765),
# avec le protocole confirmé — le même que le bouton Reset : play_motion avec
# file_path + priority (≥5, sinon écrasé par le comportement autonome) + torque.
ANIM_WS_URL = "ws://127.0.0.1:8765?audience=web"
ANIM_BASE_PATH = "/root/material/actions"
ANIM_PRIORITY = 5          # ≥5 : sinon l'action se fait écraser par l'autonome
ANIM_TORQUE = 2047         # couple maxi, comme l'action de redressement officielle

try:
    import websocket as _ws_client      # paquet « websocket-client »
except Exception:                        # absent : les animations sont désactivées,
    _ws_client = None                    # mais la déambulation reste intacte


class ExecuteurAnimation:
    """Joue une action de la bibliothèque via le pont web LOCAL du robot.

    `jouer(nom)` et `couper()` sont non bloquants : ils déposent une consigne
    dans une file, un thread s'occupe du WebSocket (connexion paresseuse,
    reconnexion au coup suivant en cas de coupure).
    """

    def __init__(self, logger, url=ANIM_WS_URL):
        self.logger = logger
        self.url = url
        self.ws = None
        self.actif = _ws_client is not None
        self.q = queue.Queue(maxsize=4)
        if not self.actif:
            logger.warn("Paquet « websocket-client » absent : animations "
                        "désactivées (pip install websocket-client). "
                        "La déambulation fonctionne normalement, sans animation.")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def jouer(self, nom):
        if not self.actif or not nom:
            return
        try:
            self.q.put_nowait(("play", nom))
        except queue.Full:
            pass

    def couper(self):
        """Interrompt l'action en cours et rend les moteurs à la démarche.

        Envoyé en sortie de l'état « anime » (fin normale OU vide qui surgit) :
        stop_all_motions coupe à la fois l'action et tout mouvement résiduel.
        """
        if not self.actif:
            return
        try:
            while True:
                self.q.get_nowait()          # on vide les play en attente
        except queue.Empty:
            pass
        try:
            self.q.put_nowait(("stop", None))
        except queue.Full:
            pass

    def _run(self):
        while True:
            action, nom = self.q.get()
            try:
                if self.ws is None:
                    self.ws = _ws_client.create_connection(self.url, timeout=3)
                if action == "stop":
                    self._envoie("stop_all_motions", {})
                else:
                    self._envoie("play_motion", {
                        "file_path": "%s/%s.avi" % (ANIM_BASE_PATH, nom),
                        "loop": False, "priority": ANIM_PRIORITY, "torque": ANIM_TORQUE})
            except Exception as e:
                # une coupure ferme le socket : on le rouvrira au prochain coup
                try:
                    if self.ws is not None:
                        self.ws.close()
                except Exception:
                    pass
                self.ws = None
                self.logger.warn("animation « %s » non jouée : %s" % (nom, e))

    def _envoie(self, request_type, data):
        # play_motion répond « sending » tout de suite : on n'attend pas la fin.
        self.ws.send(json.dumps({"type": "request", "request_type": request_type,
                                 "request_id": uuid.uuid4().hex[:12], "data": data}))


# ═══════════════════════════ service HTTP (à bord) ═══════════════════════════
def _lancer_service(noeud, port):
    """Petit serveur HTTP, à bord du robot, que le helper Studio 360 appelle.

    Le helper parle WebSocket au robot, pas ROS ; ce service est le pont. Il
    n'expose QUE la déambulation : la grille ToF, la décision, et démarrer /
    arrêter / vitesse. Rien de sensible. Écoute sur toutes les interfaces pour
    être joignable depuis le PC du même réseau.

      GET  /etat                → instantané JSON (grille, décision, contexte)
      GET  /animations          → mapping événement → animation courant
      GET  /ecran/contenus      → animations disponibles sur l'écran (lottie, gif)
      POST /ecran/toast         → message texte à l'écran
      POST /ecran/lottie        → joue une animation Lottie
      POST /ecran/gif           → joue un GIF
      POST /demarrer            → arme la marche (réapprend le sol en marchant)
      POST /arreter             → coupe la marche, consignes nulles
      POST /vitesse?v=0.4       → règle la consigne d'avance (0.05–1.0)
      POST /animations          → règle le mapping (corps JSON {événement: action})
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from urllib.parse import urlparse, parse_qs

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # pas de bruit dans la console de déambulation

        def _repond(self, code, obj):
            corps = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def _lire_json(self):
            n = int(self.headers.get("Content-Length") or 0)
            if not n:
                return {}
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except Exception:
                return {}

        def do_GET(self):
            chemin = urlparse(self.path).path
            if chemin in ("/etat", "/"):
                self._repond(200, noeud.instantane())
            elif chemin == "/animations":
                self._repond(200, {"animations": dict(noeud.cerveau.animations)})
            elif chemin == "/ecran/contenus":
                self._repond(200, noeud.ecran_contenus())
            else:
                self._repond(404, {"erreur": "route inconnue"})

        def do_POST(self):
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if u.path == "/demarrer":
                noeud.demarrer()
                self._repond(200, noeud.instantane())
            elif u.path == "/arreter":
                noeud.arreter()
                self._repond(200, noeud.instantane())
            elif u.path == "/vitesse":
                try:
                    noeud.regle_vitesse(float(q.get("v", ["0"])[0]))
                    self._repond(200, noeud.instantane())
                except (TypeError, ValueError):
                    self._repond(422, {"erreur": "vitesse invalide"})
            elif u.path == "/animations":
                noeud.regle_animations(self._lire_json())
                self._repond(200, {"animations": dict(noeud.cerveau.animations)})
            elif u.path.startswith("/ecran/"):
                quoi = u.path[len("/ecran/"):]
                code, corps = noeud.ecran_commande(quoi, self._lire_json())
                self._repond(code, corps)
            else:
                self._repond(404, {"erreur": "route inconnue"})

    srv = ThreadingHTTPServer(("0.0.0.0", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


# ═══════════════════════════════ partie ROS ═══════════════════════════════
def principal():
    ap = argparse.ArgumentParser(description="Déambulation autonome du Sirius")
    ap.add_argument("--marche", action="store_true",
                    help="publier réellement les consignes (sinon : observation seule)")
    ap.add_argument("--duree", type=float, default=0.0,
                    help="arrêt automatique après N secondes (0 = sans limite)")
    ap.add_argument("--vitesse", type=float, default=VITESSE_AVANT,
                    help="consigne d'avance (défaut %.2f). ⚠️ On ignore encore si "
                         "cmd_vel attend des m/s ou une valeur normalisée [-1,1] "
                         "comme le fait gait_control sur le WebSocket. Si le robot "
                         "piétine sans avancer, monte à 0.4 puis 0.6." % VITESSE_AVANT)
    ap.add_argument("--rotation", type=float, default=VITESSE_ROTATION,
                    help="consigne de rotation (défaut %.2f)" % VITESSE_ROTATION)
    ap.add_argument("--service", action="store_true",
                    help="expose un petit serveur HTTP (grille ToF + décision en "
                         "direct, démarrer / arrêter / vitesse) que le helper "
                         "Studio 360 appelle. En mode service, le robot NE bouge "
                         "PAS tant que « démarrer » n'a pas été demandé.")
    ap.add_argument("--port-service", type=int, default=8790,
                    help="port du serveur de service (défaut 8790)")
    ap.add_argument("--animations", type=str, default=None,
                    help='animations d\'évitement, JSON événement→action, ex : '
                         '\'{"approche":"stand_default_peer_brief",'
                         '"bloque":"stand_default_ponder_brief"}\'. Événements : '
                         '« approche » (obstacle proche, jouée avant le recul) et '
                         '« bloque » (coincé). Une action est jouée en priorité 5 '
                         'via le pont web local ; nécessite le paquet '
                         'websocket-client sur le robot. Réglable aussi en direct '
                         'par POST /animations (Studio 360).')
    ap.add_argument("--apprendre-a-l-arret", action="store_true",
                    help="apprendre le fond robot immobile. DÉCONSEILLÉ en mode "
                         "--marche : les pattes avant entrent dans le bas du "
                         "champ à chaque foulée, et le corps tangue. Un fond "
                         "appris à l'arrêt prend donc le premier pas pour un "
                         "obstacle. Par défaut, en mode --marche, le fond est "
                         "appris pendant quelques pas.")
    # (Il y avait ici une option --tete pour fixer l'inclinaison de la tête
    #  avant d'apprendre le fond. Elle a été retirée : la mesure du 25/07
    #  montre que le capteur ToF ne suit PAS la tête — 17° de basculement
    #  n'ont pas déplacé les distances de 2 mm. Le capteur est solidaire du
    #  CORPS. Seule l'assiette du corps entre donc dans la géométrie, ce qui
    #  simplifie tout : c'est exactement ce que l'enveloppe apprise en
    #  marchant sait absorber.)
    args = ap.parse_args()
    # Le mapping d'animations peut venir de la ligne de commande (JSON) ; il est
    # aussi réglable en direct via POST /animations. Un JSON invalide ne doit pas
    # empêcher de déambuler : on le signale et on continue sans animation.
    try:
        args.animations = json.loads(args.animations) if args.animations else {}
        if not isinstance(args.animations, dict):
            raise ValueError("le JSON --animations doit être un objet")
    except (ValueError, TypeError) as e:
        print("⚠ --animations ignoré (%s) : déambulation sans animation." % e)
        args.animations = {}

    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from geometry_msgs.msg import Twist
    from sensor_msgs.msg import Imu, BatteryState
    from std_msgs.msg import String
    from state_sensor_tof.msg import ToFDistanceArray

    class Deambulation(Node):
        def __init__(self):
            super().__init__("deambulation")
            self.cerveau = Cerveau(vitesse=args.vitesse, rotation=args.rotation,
                                   animations=args.animations)
            self.executeur_anim = ExecuteurAnimation(self.get_logger())
            self._etait_anime = False
            # ── écran de la tête ──────────────────────────────────────────
            # lvgl_gui_node expose des SERVICES ROS (et non des topics) pour
            # afficher du texte et jouer des animations. On les atteint donc
            # depuis ce nœud embarqué : le helper, lui, ne parle que WebSocket.
            # Import tolérant : si le paquet manque, la déambulation continue.
            self.srv_ecran = {}
            try:
                from lvgl_ros2_gui.srv import PlayGif, PlayLottie, ShowToast
                self.srv_ecran = {
                    "gif": self.create_client(PlayGif, "/lvgl_gui_node/play_gif"),
                    "lottie": self.create_client(PlayLottie, "/lvgl_gui_node/play_lottie"),
                    "toast": self.create_client(ShowToast, "/lvgl_gui/show_toast"),
                }
                self._types_ecran = {"gif": PlayGif, "lottie": PlayLottie, "toast": ShowToast}
                self.get_logger().info("Écran de la tête : services disponibles.")
            except Exception as e:
                self._types_ecran = {}
                self.get_logger().warn("Écran de la tête indisponible (%s)." % e)
            self.grille = [None] * 16
            self.dernier_tof = 0.0
            self.batterie = None
            self.inclinaison = None
            self.posture = None
            self.demarrage = time.monotonic()
            self.apprentissage = []
            self.sol_appris = False
            # Interrupteur de marche à l'exécution. En mode --service, il démarre
            # à False : le robot attend « démarrer ». Sinon il suit --marche.
            self.en_marche = bool(args.marche) and not args.service
            self.etat_courant = {}   # dernier instantané, lu par le service HTTP

            qos = QoSProfile(depth=5, reliability=ReliabilityPolicy.BEST_EFFORT,
                             history=HistoryPolicy.KEEP_LAST)
            self.create_subscription(ToFDistanceArray,
                                     "/state_sensor/tof/distance_array", self.on_tof, qos)
            self.create_subscription(Imu,
                                     "/state_sensor/imu_onbody/imu_publisher/imu_data",
                                     self.on_imu, qos)
            self.create_subscription(BatteryState,
                                     "/internal_sensor/battery_onbody/battery_publisher/state",
                                     self.on_batterie, 5)
            self.create_subscription(String, "/action_player/current_posture",
                                     self.on_posture, 5)
            # Le générateur de démarche publie ce qu'il applique VRAIMENT.
            # C'est le seul moyen de savoir si nos consignes passent, et dans
            # quelle unité — le robot piétine-t-il parce qu'il refuse, ou
            # parce qu'on lui demande trop peu ?
            self.mesure = {"vx": 0.0, "wz": 0.0}
            self.mesure_max = 0.0
            self.create_subscription(Twist, "/gait_generation_trot/filtered_velocity",
                                     self.on_vitesse, qos)
            self.pub = self.create_publisher(Twist, "/gait_generation_trot/cmd_vel", 5)
            self.create_timer(0.1, self.boucle)   # 10 Hz : inutile de décider à 38

            if args.marche and args.apprendre_a_l_arret:
                self.get_logger().warn(
                    "Fond appris à l'arrêt alors que le robot va marcher : les "
                    "pattes avant vont entrer dans le champ à chaque foulée et "
                    "seront prises pour des obstacles. À n'utiliser que pour "
                    "comparer.")
            if args.marche and not args.apprendre_a_l_arret:
                self.get_logger().info(
                    "Apprentissage EN MARCHANT : il va avancer tout droit ~5 s. "
                    "Dégage bien la ligne droite devant lui.")
            self.get_logger().info(
                "Déambulation — mode %s." % ("MARCHE" if args.marche else "OBSERVATION"))

        # -------- entrées --------
        def on_tof(self, msg):
            d = list(msg.distances)
            if len(d) >= 16:
                self.grille = d[:16]
                self.dernier_tof = time.monotonic()
                if not self.sol_appris:
                    self.apprentissage.append(self.grille[:])

        def on_imu(self, msg):
            # tangage à partir du quaternion — on ne veut qu'un ordre de grandeur
            x, y, z, w = msg.orientation.x, msg.orientation.y, msg.orientation.z, msg.orientation.w
            sinp = 2.0 * (w * y - z * x)
            self.inclinaison = math.asin(max(-1.0, min(1.0, sinp)))

        def on_batterie(self, msg):
            self.batterie = msg.percentage

        def on_posture(self, msg):
            self.posture = msg.data

        def on_vitesse(self, msg):
            self.mesure = {"vx": msg.linear.x, "wz": msg.angular.z}
            self.mesure_max = max(self.mesure_max, abs(msg.linear.x))

        # -------- sortie --------
        def publie(self, vx, wz):
            # Une consigne non nulle ne part que si la marche est armée
            # (--marche, ou « démarrer » en mode service). Une consigne NULLE
            # part toujours : un arrêt ne doit jamais être bloqué.
            if not self.en_marche and (vx or wz):
                return
            t = Twist()
            t.linear.x = float(vx)
            t.angular.z = float(wz)
            self.pub.publish(t)

        # -------- pilotage par le service HTTP --------
        def instantane(self):
            """État complet lu par le service : décision courante + contexte."""
            snap = dict(self.etat_courant)
            snap.update({"version": VERSION, "en_marche": bool(self.en_marche),
                         "sol_appris": bool(self.sol_appris),
                         "vitesse": round(float(self.cerveau.vitesse), 3),
                         "animations": dict(self.cerveau.animations),
                         "animations_actives": bool(self.executeur_anim.actif)})
            return snap

        def demarrer(self):
            """Arme la marche et relance l'apprentissage du sol EN MARCHANT."""
            self.sol_appris = False
            self.apprentissage = []
            self.demarrage = time.monotonic()
            self.mesure_max = 0.0
            self.en_marche = True
            self.get_logger().info("Service : DÉMARRER — apprentissage puis errance.")

        def arreter(self):
            """Coupe la marche et envoie plusieurs consignes nulles."""
            self.en_marche = False
            self._etait_anime = False
            self.executeur_anim.couper()   # interrompt une éventuelle animation
            for _ in range(5):
                self.publie(0.0, 0.0)
                time.sleep(0.02)
            self.get_logger().info("Service : ARRÊTER — consignes nulles envoyées.")

        def regle_vitesse(self, v):
            """Change la consigne d'avance (bornée 0.05–1.0)."""
            self.cerveau.vitesse = max(0.05, min(1.0, float(v)))

        MATERIEL = "/root/material"

        def ecran_contenus(self):
            """Animations installées sur le robot (Lottie et GIF)."""
            import os
            def liste(sous, ext):
                d = os.path.join(self.MATERIEL, sous)
                try:
                    return sorted(f for f in os.listdir(d) if f.lower().endswith(ext))
                except OSError:
                    return []
            return {"lottie": liste("lottie", ".json"), "gif": liste("gif", ".gif"),
                    "dossier": self.MATERIEL,
                    "disponible": bool(self.srv_ecran)}

        def _appelle_service(self, cle, requete, delai=4.0):
            """Appel de service depuis le fil HTTP. Le nœud tourne (rclpy.spin)
            dans le fil principal : on dépose la requête et on attend le
            résultat, sans jamais faire tourner d'exécuteur ici."""
            cli = self.srv_ecran.get(cle)
            if cli is None:
                return 503, {"erreur": "service d'écran indisponible sur ce robot"}
            if not cli.wait_for_service(timeout_sec=1.5):
                return 503, {"erreur": "le service %s ne répond pas" % cle}
            fut = cli.call_async(requete)
            t0 = time.monotonic()
            while not fut.done() and time.monotonic() - t0 < delai:
                time.sleep(0.02)
            if not fut.done():
                return 504, {"erreur": "délai dépassé"}
            r = fut.result()
            return 200, {"ok": bool(getattr(r, "success", True)),
                         "message": getattr(r, "message", "")}

        def ecran_commande(self, quoi, corps):
            """toast | lottie | gif — voir les définitions de services ROS."""
            corps = corps if isinstance(corps, dict) else {}
            T = self._types_ecran
            if quoi == "toast" and "toast" in T:
                q = T["toast"].Request()
                q.message = str(corps.get("message", ""))[:200]
                q.type = int(corps.get("type", 0))          # 0 info … 3 erreur
                q.position = int(corps.get("position", 1))  # 1 = centre
                q.duration_ms = int(corps.get("duree_ms", 2500))
                return self._appelle_service("toast", q)
            if quoi == "lottie" and "lottie" in T:
                q = T["lottie"].Request()
                nom = str(corps.get("fichier", "")).strip().strip("/")
                if not nom:
                    return 422, {"erreur": "fichier manquant"}
                q.file_path = nom if nom.startswith("/") else "%s/lottie/%s" % (self.MATERIEL, nom)
                q.x = int(corps.get("x", -1)); q.y = int(corps.get("y", -1))
                q.width = int(corps.get("largeur", 0)); q.height = int(corps.get("hauteur", 0))
                q.loop = bool(corps.get("boucle", False))
                q.bg_color = int(corps.get("fond", 0))
                q.bg_opacity = int(corps.get("opacite", 0))
                q.hide_eye_layer = bool(corps.get("masquer_yeux", False))
                return self._appelle_service("lottie", q)
            if quoi == "gif" and "gif" in T:
                q = T["gif"].Request()
                nom = str(corps.get("fichier", "")).strip().strip("/")
                if not nom:
                    return 422, {"erreur": "fichier manquant"}
                q.file_name = nom
                q.absolute_path = ""
                q.x = int(corps.get("x", -1)); q.y = int(corps.get("y", -1))
                q.width = int(corps.get("largeur", 0)); q.height = int(corps.get("hauteur", 0))
                q.loop_count = int(corps.get("boucles", 1))
                q.hide_eye_layer = bool(corps.get("masquer_yeux", False))
                return self._appelle_service("gif", q)
            return 404, {"erreur": "commande d'écran inconnue : %s" % quoi}

        def regle_animations(self, maj):
            """Met à jour le mapping événement→animation (fusion). Une valeur
            vide (None/"") retire l'animation de l'événement."""
            if isinstance(maj, dict):
                for cle, val in maj.items():
                    self.cerveau.animations[str(cle)] = (val or None)

        def boucle(self):
            maintenant = time.monotonic()

            # Instantané lu par le service HTTP (défauts ; enrichi après décision).
            self.etat_courant = {
                "grille": [None if x is None else int(x) for x in self.grille],
                "fraicheur": round((maintenant - self.dernier_tof) if self.dernier_tof else 99.0, 2),
                "etat": "apprentissage" if not self.sol_appris else "?",
                "motif": "apprentissage du sol en cours" if not self.sol_appris else "",
                "vx": 0.0, "wz": 0.0,
                "batterie": None if self.batterie is None else round(float(self.batterie), 3),
                "inclinaison": None if self.inclinaison is None else round(float(self.inclinaison), 3),
                "mesure": {"vx": round(self.mesure["vx"], 3), "wz": round(self.mesure["wz"], 3)},
                "geometrie_douteuse": bool(self.cerveau.geometrie_douteuse),
                "eligibles_vide": sorted(self.cerveau.eligibles_vide),
                "posture": self.posture,
                # Ce qui permet à l'interface de COLORER la grille plutôt que
                # d'afficher seize nombres bruts : l'enveloppe apprise par zone,
                # les zones qui crient, et les constantes de lecture.
                "enveloppe": {str(i): (None if (self.cerveau.enveloppe or {}).get(i) is None
                                       else [int((self.cerveau.enveloppe or {})[i][0]),
                                             int((self.cerveau.enveloppe or {})[i][1])])
                              for i in range(16)},
                "zones_obstacle": [], "distance_obstacle": None, "zones_vide": [],
                "masque_bande": list(MASQUE_BANDE),
                "hors_portee": HORS_PORTEE,
            }

            if not self.sol_appris:
                # Apprentissage en marchant : on avance tout droit le temps de
                # couvrir plusieurs foulées, pour que l'enveloppe contienne le
                # tangage du trot. Sans cela, le premier pas ferait passer le
                # plancher pour un obstacle.
                en_marchant = self.en_marche and not args.apprendre_a_l_arret
                duree_appr = 5.0 if en_marchant else 2.0
                if en_marchant and maintenant - self.demarrage < duree_appr:
                    self.publie(args.vitesse * 0.6, 0.0)
                if maintenant - self.demarrage > duree_appr and len(self.apprentissage) > 10:
                    self.publie(0.0, 0.0)
                    profil = self.cerveau.apprend_le_sol(self.apprentissage,
                                                         assiette=self.inclinaison)
                    self.sol_appris = True
                    env = self.cerveau.enveloppe
                    lisible = {i: (None if env[i] is None
                                   else "%d-%d" % (int(env[i][0]), int(env[i][1])))
                               for i in sorted(env)}
                    self.get_logger().info(
                        "Fond appris %s sur %d trames : %s"
                        % ("EN MARCHANT" if en_marchant else "à l'arrêt",
                           len(self.apprentissage), lisible))
                    elig = sorted(self.cerveau.eligibles_vide)
                    self.get_logger().info(
                        "Zones admises à déclarer un VIDE : %s "
                        "(vues %d%% du temps et à moins de %d mm)."
                        % (elig or "AUCUNE", int(FIABILITE_MINI * 100), SOL_PROCHE))
                    if not elig:
                        self.get_logger().warn(
                            "Aucune zone ne voit le sol de façon fiable : la "
                            "détection de vide sera INACTIVE. Ne le fais pas "
                            "circuler près d'un bord.")
                    self.get_logger().info(
                        "Obstacle = plus proche que la borne basse − %d mm, "
                        "confirmé sur %d cycles. Vide = plus loin que la borne "
                        "haute + %d mm, même confirmation."
                        % (MARGE_OBSTACLE, PERSISTANCE, MARGE_VIDE))
                return

            if self.en_marche and args.duree and maintenant - self.demarrage > args.duree:
                self.publie(0.0, 0.0)
                self.get_logger().info(
                    "Durée écoulée — arrêt. Vitesse réelle maximale atteinte : "
                    "%.3f (consigne %.2f)." % (self.mesure_max, args.vitesse))
                if self.mesure_max < 0.02:
                    self.get_logger().warn(
                        "Le robot n'a JAMAIS avancé. Deux causes possibles : il est "
                        "en mode « Bureau » (bascule sur « Sol » dans Sirius Studio), "
                        "ou la consigne est trop faible — relance avec --vitesse 0.5.")
                if args.service:
                    self.en_marche = False       # en service : on stoppe, on ne quitte pas
                    return
                raise SystemExit(0)

            contexte = {
                "fraicheur": maintenant - self.dernier_tof if self.dernier_tof else 99.0,
                "batterie": self.batterie,
                "inclinaison": self.inclinaison,
                "posture": self.posture,
            }
            vx, wz, etat, motif = self.cerveau.decide(self.grille, maintenant, contexte)

            # --- exécution de l'INTENTION d'animation émise par le Cerveau ------
            # On ne joue rien en observation (comme publie() ne publie rien) : il
            # faut la marche armée. L'état « anime » impose vx=wz=0, donc publie()
            # met la démarche à 0 AVANT que l'action prenne la main sur les
            # moteurs. À la SORTIE de « anime » (fin normale, ou vide qui a forcé
            # le recul en amont), on coupe l'action pour rendre les moteurs à la
            # démarche/au recul.
            if self.en_marche and self.cerveau.anim_a_jouer:
                self.executeur_anim.jouer(self.cerveau.anim_a_jouer)
            self.cerveau.anim_a_jouer = None
            if self.en_marche and self._etait_anime and etat != "anime":
                self.executeur_anim.couper()
            self._etait_anime = (etat == "anime")

            self.publie(vx, wz)
            self.etat_courant.update({"etat": etat, "motif": motif,
                                      "vx": round(float(vx), 3), "wz": round(float(wz), 3)})
            # Quelles zones crient, et pourquoi. `obstacle()` et `vide()` sont
            # en lecture seule : les interroger ici ne perturbe pas la décision.
            try:
                z_obst, d_obst = self.cerveau.obstacle(self.grille, detail=True)
                self.etat_courant.update({
                    "zones_obstacle": list(z_obst),
                    "distance_obstacle": None if d_obst is None else int(d_obst),
                    "zones_vide": list(self.cerveau.vide(self.grille)),
                })
            except Exception:
                pass

            # Toutes les 2 s en mouvement : consigne envoyée vs vitesse mesurée.
            if self.en_marche and abs(vx) > 0.001:
                if not hasattr(self, "_dernier_bilan"):
                    self._dernier_bilan = 0.0
                if maintenant - self._dernier_bilan > 2.0:
                    self._dernier_bilan = maintenant
                    self.get_logger().info(
                        "  consigne vx=%+.2f → mesuré vx=%+.3f  (rapport %s)"
                        % (vx, self.mesure["vx"],
                           "%.2f" % (self.mesure["vx"] / vx) if abs(vx) > 1e-6 else "—"))

            if not hasattr(self, "_dernier_etat") or (etat, motif) != self._dernier_etat:
                self._dernier_etat = (etat, motif)
                prefixe = "" if self.en_marche else "[observation] "
                suffixe = "  (géométrie douteuse : vide non surveillé)" \
                    if self.cerveau.geometrie_douteuse else ""
                self.get_logger().info(
                    "%s%-7s vx=%+.2f wz=%+.2f — %s%s"
                    % (prefixe, etat, vx, wz, motif, suffixe))

    print("=" * 68)
    print("  deambulation.py — version %s" % VERSION)
    if args.service:
        print("  mode : SERVICE — le robot attend « démarrer » (port %d)" % args.port_service)
    else:
        print("  mode : %s" % ("MARCHE — le robot va se déplacer"
                               if args.marche else "OBSERVATION — rien ne bougera"))
    print("-" * 68)
    print("  ⚠  SOL PLAT UNIQUEMENT. Jamais sur une table ou un plan de")
    print("     travail, jamais près d'un escalier, d'une marche ou d'un")
    print("     bord. La détection du vide n'a jamais été éprouvée au bord")
    print("     d'un vrai dénivelé : ne comptez pas dessus.")
    print("     Le robot ne voit rien derrière lui. Restez à portée de main.")
    print("=" * 68)

    rclpy.init()
    noeud = Deambulation()

    srv = None
    if args.service:
        srv = _lancer_service(noeud, args.port_service)
        print("  service : http://<ip_du_robot>:%d/etat  (+ POST /demarrer /arreter /vitesse)"
              % args.port_service)

    # ── Arrêt garanti ────────────────────────────────────────────────────
    # Le 25/07, une coupure Wi-Fi a gelé la session SSH pendant que le robot
    # marchait. Or rien ne prouve que le générateur de démarche s'arrête
    # quand plus personne ne publie : il peut très bien conserver la dernière
    # consigne. Un processus tué net laisserait donc un robot lancé.
    #
    # On intercepte donc TOUS les signaux d'arrêt — dont SIGHUP, celui que
    # reçoit un processus quand sa session SSH meurt — pour publier une
    # consigne nulle avant de rendre la main.
    def arret_propre(signum, _frame):
        noeud.get_logger().warn("Signal %d reçu — arrêt immédiat." % signum)
        raise SystemExit(0)

    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        try:
            signal.signal(sig, arret_propre)
        except (ValueError, AttributeError):
            pass   # SIGHUP n'existe pas partout

    try:
        rclpy.spin(noeud)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        # Consigne nulle, répétée : un seul message peut se perdre, et l'enjeu
        # est un robot qui continue de marcher tout seul.
        try:
            for _ in range(10):
                noeud.publie(0.0, 0.0)
                time.sleep(0.05)
        except Exception:
            pass
        try:
            if srv is not None:
                srv.shutdown()
        except Exception:
            pass
        try:
            noeud.destroy_node()
        except Exception:
            pass
        rclpy.shutdown()
        print("déambulation arrêtée, consigne remise à zéro (10 envois).")


if __name__ == "__main__":
    principal()
