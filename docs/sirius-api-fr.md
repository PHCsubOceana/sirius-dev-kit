# API réelle du Sirius — référence technique

> Reverse-engineering mené **en direct sur le robot** (192.168.1.42), en croisant
> l'analyse du firmware et la capture du trafic de l'interface officielle.
> Tout ce qui porte ✅ a été **vérifié sur la machine**.
>
> ⚠️ Le robot fait tourner un firmware **plus récent que le paquet 2.3.6** dont on
> dispose : l'architecture a été refondue (`core_api_node`, `sirius_motion_control_node`,
> `behavior_engine_node`). Se fier à ce document plutôt qu'au contenu du .tar.gz.

---

## 1. Les quatre canaux

| Canal | Adresse | Rôle | Statut |
|---|---|---|---|
| **WebSocket** | `ws://<IP>:8765?audience=web` | Canal principal : état poussé + requêtes/réponses | ✅ |
| **REST** | `http://<IP>:8088/api/v1/…` | Config IA, identifiants, compétences, logs | ✅ |
| **UDP** | `<IP>:8768` (motion+LED), `:8770` (yeux) | Streaming de poses `Play_Keyframe` (voie Blender) | documenté |
| **SSH** | `root@<IP>:22` | Accès ROS 2, déploiement | ✅ |

> Le paramètre **`?audience=web`** figure dans l'URL de l'interface officielle.
> La connexion fonctionne sans, mais autant rester fidèle.

---

## 2. WebSocket — protocole ✅

### 2.1 Enveloppes

Handshake reçu à la connexion :
```json
{"type":"event","event_type":"connection_info",
 "data":{"client_id":30,"status":"connected",
   "server_info":{"name":"Sirius Core API","version":"4.0.0",
     "architecture":"Service-based",
     "capabilities":["play_motion","status_monitoring","factory_test","ota_update"]}}}
```

Requête → réponse :
```json
{"type":"request","request_type":"<NOM>","request_id":"<id>","data":{…}}
{"type":"response","request_id":"<id>","success":true,"code":"ok","data":{…},"error":""}
```

Battement de cœur émis par le client : `{"type":"ping","data":{"timestamp":…}}`

Codes d'erreur : `invalid_request`, `not_found` (`Unknown request_type: …`),
`invalid_argument`, `service_unavailable`. Sonder un nom inconnu est **sans effet**.

### 2.2 ⚠️ Les noms de commandes sont en MAJUSCULES

**C'est le piège principal de cette API.** Le protocole réseau utilise les clés
en majuscules (`BEHAVIOR_SET_PAUSE`). Les noms en minuscules qu'on trouve dans
les binaires (`set_behavior_pause`) sont les **handlers internes**, pas le fil.

Certaines commandes acceptent les deux (`play_motion`, `gait_control`,
`get_status`, `get_actions` fonctionnent en minuscules — alias hérités), mais
**les commandes de mode n'existent qu'en majuscules**. Chercher `set_behavior_pause`
sur le fil renvoie « Unknown request_type » et fait croire à tort qu'elle est
inaccessible.

### 2.3 Table complète des commandes (59, extraite du bundle officiel)

| Clé réseau | Handler interne |
|---|---|
| `ACTION_PLAY` | play_motion |
| `ACTION_STOP` | cancel_motion |
| `ACTION_STOP_ALL` | stop_all_motions |
| `ACTION_GET_LIST` | get_actions |
| `ACTION_FILE_UPLOAD` / `_DOWNLOAD` / `_RENAME` / `_DELETE` | upload/download/rename/delete_action |
| `BEHAVIOR_SET_PAUSE` | set_behavior_pause |
| `BEHAVIOR_SET_RANDOM_ACTION` | enable_random_action |
| `BEHAVIOR_SET_ORCHESTRATION_MODE` | set_orchestration_mode |
| `EMOTION_SET_STATE` | set_emotion_state |
| `EMOTION_INTERACTION` | emotion_interaction |
| `EMOTION_GET_HISTORY` / `EMOTION_ADJUST_SATIETY` | … |
| `USER_GET_ROBOT_MODE` / `USER_SET_ROBOT_MODE` | get/set_robot_mode |
| `USER_GET_THEME` / `SET_THEME` / `GET_MBTI` / `SET_MBTI` / `GET_LANGUAGE` / `SET_LANGUAGE` | … |
| `USER_GET_NODE_PARAMETER` / `SET_NODE_PARAMETER(S)` | … |
| `MOTOR_SET_TORQUE` / `SET_MODE` / `GET_MODE` | … |
| `MOTOR_SET_THERMAL_PROTECTION` | enable_thermal_protection |
| `BATTERY_GET_STATUS` | get_battery_status |
| `VISION_SET_DETECTION` | enable_detection |
| `VISION_SET_FACE_TRACKING` | face_tracking_control |
| `LIFECYCLE_GET_STATES` / `SET_STATE` | … |
| `NETWORK_SCAN` / `CONNECT` / `HOTSPOT_CONTROL` / `GET_HOTSPOT_STATUS` | … |
| `OTA_*` (check, start, cancel, rollback, list, config, status) | … |
| `SYNC_*` (chrony, system time) | … |
| `MATERIAL_*` (upload, save, stop, combo_play) | … |

Hors table (noms en minuscules uniquement) : `gait_control`, `gait_step_move`,
`attitude_control`, `self_recover`, `set_motion_mode`.

### Capture du 28/07 — trames réelles de l'interface officielle ✅

En écoutant les trames SORTANTES du WebSocket de l'interface officielle Hengbot
(connectée au robot, `ws://<ip>:8765/?audience=web`), on a relevé le format
exact de plusieurs commandes. **Enveloppe confirmée identique à la nôtre** :
`{"type":"request","request_id":"req_<horodatage>_<n>","request_type":<CLÉ>,"data":{…}}`.

- **`USER_SET_NODE_PARAMETER`** — `{node_name, parameter_name, parameter_value}` ✅.
  C'est le mécanisme qui règle le **VOLUME** :
  `{node_name:"wmix_audio_player_node", parameter_name:"audio_volume", parameter_value:<entier 0-100>}`.
  Ouvre en principe le réglage de tout paramètre ROS exposé par un nœud.
- **`ACTION_PLAY`** — `{file_path, loop, priority, torque}` ✅ (relevé :
  `/root/material/actions/stand_default_littleBark_brief.avi`, `loop:false`,
  `priority:3`, `torque:2047`). ⚠ Sur l'interface officielle, changer le volume
  déclenche cette action « petit aboiement » en aperçu sonore : le robot se lève
  et aboie. Ce n'est donc pas un dysfonctionnement.
- **`OTA_CHECK_UPDATE`** `{}`, **`OTA_GET_STATUS`** `{}`, **`OTA_GET_CONFIG`** `{}`,
  **`OTA_LIST_VERSIONS`** `{channel}` ✅ (lectures, chargées par la page « System Update »).
- **`LIFECYCLE_GET_STATES`** `{}` ✅ (page « Node Management »).
- **`GET_AI_STATE`** `{}`, **`USER_GET_LANGUAGE`** `{}` ✅ (lectures au chargement).
- Battement de cœur : `{"type":"ping","data":{"timestamp":<ms>}}`, ~1 Hz.

Non capturé (volontairement pas déclenché, pour ne pas faire bouger le robot) :
les SET de mode/allure (`set_motion_mode`), `MOTOR_*`, MBTI/langue/thème en
écriture, `BEHAVIOR_SET_ORCHESTRATION_MODE`. Restent au statut « déduit ».

### Le canal UDP 8768 — et pourquoi les YEUX ne répondent pas ✅

Relevé **sur le robot** le 28/07 (firmware 2.5.0), en SSH.

**Un seul port UDP écoute** : `0.0.0.0:8768`, tenu par
`user_interface_udp_server_node`. Les ports du script Blender du constructeur —
8770 (`face_ui`), 8769 (overlay), 8772 (pondération `set_weight_params`) — ne
sont **pas ouverts**. Comme l'UDP ne signale jamais un port fermé, toute trame
qu'on y envoie disparaît en silence : c'est le piège qui nous a coûté du temps.

**Ce que ce canal pilote réellement** (topics publiés par ce nœud) :

| Topic publié | Type | Intérêt |
|---|---|---|
| `/gait_generation_trot/cmd_vel` | `geometry_msgs/Twist` | marche |
| `/kinematics/ik_subscriber/body_pose` | `Pose` | assiette du corps |
| `/kinematics/ik_subscriber/head_quaternion` | `Quaternion` | tête |
| `/kinematics/ik_subscriber/{left,right}_{front,back}_point` | `Point` | pattes |
| `/robot_led_controller/led_colors` | `String` | **LED** (aucun autre accès connu) |
| `/lvgl_layer` | `String` | l'écran / les yeux — **orphelin, voir ci-dessous** |
| `/udp_server/status` | `UInt8` | état du serveur |

**Les yeux : conclusion définitive (négative).** Le binaire du serveur contient
bien les clés `eye_iris`, `eye_upper`, `eye_lower`, `head_led` — notre format
était donc correct. Il republie ces données sur `/lvgl_layer`. Mais :

```
$ ros2 topic info /lvgl_layer
Type: std_msgs/msg/String
Publisher count: 2
Subscription count: 0
```

**Zéro abonné**, et `lvgl_gui_node` (qui tient l'écran) ne figure pas parmi les
abonnés. Le chemin existe côté émetteur mais **plus personne ne le consomme sur
ce firmware** : piloter les pupilles par UDP est impossible, quel que soit le
port, le format ou l'ordre des messages. Le rig des yeux (`eye_upper`,
`eye_lower`, `eye_pupil`, `eye_iris`) sert en revanche à l'authoring Blender :
l'add-on d'export embarque les données d'yeux **dans les fichiers d'action**
(valeurs neutres relevées : `eye_upper` = −32, `eye_lower` = 63). L'écran est
donc animé par le lecteur d'actions et le moteur d'émotion, pas de l'extérieur.

**Ce qui, en revanche, pilote l'écran** — services ROS actifs :
`/lvgl_gui_node/play_lottie`, `/play_gif`, `/lvgl_gui/show_toast`,
`/show_dialog`, `/show_ip_address`, `/camera_display/toggle`.

**Et les émotions** : `/emotion_manager/set_emotion_state`,
`/adjust_emotion`, `/adjust_satiety` **existent en ROS**, alors que la commande
WebSocket équivalente répond « service_unavailable ». À sonder : la voie ROS
pourrait rendre l'humeur commandable, contrairement à ce qu'on avait conclu.

**Trace du sommeil (capturée le 28/07).** Sous *Autonomous Mode*, l'événement
`emotion-update` montre `emotion_state:"sleeping"`, `valence_value:50`,
`fatigue_status:0` et surtout un **`arousal_value` ≈ 3/100 qui décroît à chaque
trame** ; en parallèle le moteur de comportement joue en boucle l'action
`lie_sleep_idle`. C'est la mécanique du couchage : l'éveil décroît avec le temps
→ état `sleeping` → `lie_sleep_idle` (le robot se couche). Une stimulation
(aboiement, toucher, son) remonte l'éveil, il se relève, puis l'éveil redescend
et il se recouche. Le bouton « Debout » de notre outil (pause de l'autonome +
`returnPosition` tenu) est la parade.

---

## 3. ⚠️ Déplacement : la vitesse est NORMALISÉE, pas en m/s

**Le piège le plus coûteux de tout ce reverse.**

```json
{"request_type":"gait_control","data":{"linear_x":1,"linear_y":0,"angular_z":0}}
```

`linear_x`, `linear_y`, `angular_z` sont des valeurs dans **[-1, 1]** : une
**fraction de la vitesse maximale**, pas des m/s. La touche « avancer » de
l'interface officielle envoie `linear_x: 1`.

Envoyer `0.15` en croyant demander 0,15 m/s revient à demander **15 % de la
vitesse maxi** : la foulée devient minuscule et le robot **piétine sur place**.

Ce symptôme est particulièrement trompeur : le robot **renvoie fidèlement** la
valeur reçue, la charge moteur paraît plausible, et rien dans la télémétrie ne
signale l'anomalie.

**Conversion** (avec les limites du §6) :
`linear_x = vx / 0.24` en marche avant · `vx / 0.16` en marche arrière ·
`linear_y = vy / 0.20` · `angular_z = wz / 1.20`

Autres commandes de déplacement :
- `gait_step_move` — `{linear_x, linear_y, angular_z, steps}` : marche sur un
  nombre de foulées donné, le robot les compte lui-même. ✅
- `attitude_control` — `{body_pitch, body_yaw, head_pitch, …}` : posture.
- `self_recover` — `{}` : redressement après chute.
- `set_motion_mode` — `{mode, mode_name}` : profils DEFAULT / SLOW / WALK /
  PRECISION / CLIMB / FAST_RUN.

---

## 4. ⚠️ Mode robot : « ground » ou « desktop »

```json
USER_GET_ROBOT_MODE {}                    → {"robot_mode":"desktop"}
USER_SET_ROBOT_MODE {"robot_mode":"ground"} → {"robot_mode":"ground"}
```

Le firmware est explicite :
- **`desktop`** — « limite les mouvements amples et la démarche pour empêcher le
  robot de tomber de la table ». Les pattes bougent **sur place**.
- **`ground`** — « active toutes les actions, y compris la démarche et les
  déplacements amples ».

Sortie d'usine, le robot est en **desktop**. Deuxième cause classique du
« il piétine sans avancer » (la première étant l'unité de vitesse, §3).

---

## 5. Redressement (« Reset ») ✅

Capturé sur le bouton Reset de l'interface officielle :

```json
ACTION_PLAY {"file_path":"/root/material/actions/stand_default_returnPosition_brief.avi",
             "loop":false, "priority":5, "torque":2047}
```

Trois détails comptent : l'action est **`returnPosition`** (pas `stand_default_idle`),
la **priorité 5** (avec la priorité 1 par défaut, le comportement en cours l'écrase
et le robot reste couché), et le **couple maximal**.

`ACTION_PLAY` accepte aussi `{"action_name":"<nom>"}` — mais sans priorité, donc
inadapté au redressement.

---

## 5 bis. Posture debout / au sol ✅ / ⏳

**Debout** est certain : c'est l'action du bouton Reset (§5).

**Au sol** ne l'est pas. Le nom du fichier d'action varie selon le firmware, et
le nôtre est plus récent que le paquet dont on dispose. Le helper ne code donc
aucun nom en dur : il interroge `ACTION_GET_LIST`, choisit la meilleure
correspondance (`lie`, `lay`, `prone`, `ground`, puis `crouch`, `down`, `rest`,
enfin `sit`) et **renvoie le nom retenu** dans sa réponse — ainsi on sait
toujours ce qui a réellement été joué, et l'interface l'affiche.

```
POST /api/posture {"posture":"stand"}   → action returnPosition, priorité 5, couple 2047
POST /api/posture {"posture":"ground"}  → action déduite de la bibliothèque du robot
```

Dans les deux cas la **priorité 5** est indispensable : en priorité 1 le
comportement en cours écrase l'action.

**✅ Vérifié sur le robot réel le 26/07** : les deux commandes de posture — se
coucher et se relever — ont été exécutées sur la machine et fonctionnent. Ce
n'est donc plus une déduction du firmware ni un essai sur simulateur. Restent
deux points non confirmés : que l'état émotionnel `sleeping` quitte réellement
cet état après le redressement, et que la **déduction automatique** de posture du
helper (celle qui suit le comportement autonome sans qu'on ait cliqué) se
comporte bien sur le robot — elle n'a été éprouvée que contre le simulateur.

---

## 5 ter. Tête — `attitude_control` ⏳

Le firmware décrit `attitude_control` avec `{body_pitch, body_yaw, head_pitch, …}`.
**Les noms de champs ne sont pas encore confirmés sur le robot réel.**

```json
{"type":"request","request_type":"attitude_control",
 "data":{"head_yaw":0.30,"head_pitch":-0.20}}
```

Précautions prises côté helper (`POST /api/head`) :

- Amplitude bridée **sous** le domaine déclaré : ±0,45 rad en lacet (~26°),
  ±0,35 rad en tangage (~20°), là où le robot annonce ±0,524 rad.
- Un paramètre `cible` bascule entre les préfixes `head_*` et `body_*`, pour
  départager « le nom du champ est faux » de « la commande entière est
  inopérante » — sans rebuild.
- Aucun champ non demandé n'est envoyé : pas question d'imposer une posture de
  corps à zéro en voulant seulement tourner la tête.

Ce qu'il reste à trancher sur le matériel : est-ce que `head_yaw` / `head_pitch`
bougent quelque chose ; sinon, relever les noms réels via
`ros2 param dump /sirius_motion_control_node` ou l'inspection du nœud
`ik_subscriber`.

---

## 6. Domaine de validité (ros2 param dump /sirius_motion_control_node) ✅

| Grandeur | Domaine |
|---|---|
| Vitesse avant | 0,24 m/s |
| Vitesse arrière | 0,16 m/s |
| Vitesse latérale | ± 0,20 m/s |
| Rotation | ± 1,2 rad/s |
| Pitch / roll | ± 0,524 rad (± 30°) |

Géométrie : hauteur de corps −160 mm · demi-écartement des appuis 80 × 78 mm ·
levée maxi 80 mm avant / 50 mm arrière.

**Garde-fous actifs côté robot** : `joint_clamp_enabled: true` (écrêtage des
angles), `ws_clamp_enabled: true` (écrêtage de l'espace de travail),
`joint_jump_thresh_rad: 0.5`, `joint_max_rpm: 200`. Une consigne hors domaine
est donc écrêtée, pas poussée contre la butée.

---

## 7. Flux d'événements poussés ✅

Enveloppe : `{"type":"event","event_type":"…","timestamp":"ISO","data":{…}}`

| event_type | Fréquence | Contenu |
|---|---|---|
| `gait-trajectory` | 10 Hz | `filtered_velocity {linear_x, linear_y, angular_z}` |
| `motor-load` | 1 Hz | `loads[14]`, `range ±1000`, `unit: pwm_permille` |
| `motor-temperature` | 1 Hz | 4 pattes — **renvoie 0 sur ce firmware** (sondes muettes) |
| `battery-status` | 1 Hz | `percentage` = **ratio 0–1**, voltage, current, temperature |
| `emotion-update` | 1 Hz | `emotion_state`, valence, arousal, satiety, fatigue |
| `behavior-status` | 1 Hz | `engine{active_tree, idle, intent, recent_events[]}` — remonte les `touch_tap` |
| `system_metrics` | 1 Hz | cpu, cœurs, load_avg, disque |
| `lifecycle_update` | ~0,1 Hz | tous les nœuds ROS + état |
| `network-status` / `hotspot-status` | rare | ssid, ip, mac, signal |

### Calibration de la charge moteur (mesures réelles)

| Condition | Pic |
|---|---|
| Repos | 120 – 162 ‰ |
| Marche 0,06 m/s | 540 ‰ |
| Marche 0,24 m/s (maxi) | 530 ‰ |
| Rotation 1,2 rad/s (maxi) | 540 ‰ |
| Moteur en butée | 950 – 985 ‰ **soutenus** |

**Le pic ne dépend pas de la vitesse** : il est imposé par la cadence du pas.
Plafond normal ~540 ‰ toutes allures confondues. Le discriminant d'une butée est
la **durée** (plateau), pas l'amplitude. Seuil retenu dans le helper : 850 ‰
maintenus 0,8 s.

---

## 8. Modes & comportement ✅

| Commande | Charge utile | Effet |
|---|---|---|
| `BEHAVIOR_SET_PAUSE` | `{paused: bool}` | `true` = comportement autonome **en pause** |
| `BEHAVIOR_SET_RANDOM_ACTION` | `{enabled: bool}` | animations spontanées au repos |
| `ENABLE_AI_INTERACTION` | `{enabled: bool}` | dialogue vocal |
| `SET_VOICE_TRIGGER` | `{enabled: bool}` | réveil à la voix |

**Sommeil.** Le robot passe en `emotion_state: "sleeping"` après inactivité, avec
un `arousal` proche de 0, et s'accroupit. Dans cet état la marche ne produit rien
d'utile.

**Le réveil EST pilotable à distance** — correction du 26/07, une formulation
antérieure disait le contraire et elle était fausse. Ce qui ne l'est pas, c'est
l'**état émotionnel** : `EMOTION_SET_STATE` répond `service_unavailable` sur ce
firmware, et `EMOTION_INTERACTION` refuse tous les types tentés (`touch_tap`,
`touch`, `pet`, `dog_bone` → « Unknown interaction type »). Mais jouer l'action de
redressement remet le robot debout et opérant :

```json
ACTION_PLAY {"file_path":"/root/material/actions/stand_default_returnPosition_brief.avi",
             "loop":false, "priority":5, "torque":2047}
```

C'est ce que fait le bouton **Debout** de l'outil Studio 360, et ça marche.
**Une exception, et elle compte : le tout premier réveil après la mise sous
tension.** Là, aucune commande à distance ne suffit — il faut un **balayage
physique vers le haut sur l'écran de la tête**. C'est cohérent avec les notes de
version du constructeur : le balayage vers le haut est décrit comme le
**déverrouillage de l'écran** et le **geste de réveil** (versions 2.4.7 et
2.4.9). Tant que ce déverrouillage n'a pas eu lieu, la machine ne prend pas la
main à distance. Une fois qu'il est fait, tout le reste — y compris le réveil
après une mise en veille par inactivité — se pilote depuis l'interface.

Reste une nuance à mesurer : on ne sait pas si `emotion_state` quitte réellement `sleeping`
ou si seule la posture change — regarder l'événement `emotion-update` avant et
après le redressement tranchera en dix secondes.

---

## 9. Caméra — WebRTC ✅

Ce n'est **pas** une image à récupérer : c'est un flux **WebRTC**, négocié sur le
même WebSocket. La vidéo circule ensuite **directement entre le navigateur et le
robot**, en pair-à-pair — un backend ne peut donc que **relayer la signalisation**,
jamais servir le flux.

Séquence observée sur l'interface officielle :
```json
1. {"type":"request","request_type":"VISION_SET_DETECTION","data":{"enabled":true}}
   → {"success":true,"message":"Web streaming enabled"}
2. {"type":"webrtc_offer","client_id":"ws_1","sdp":"v=0\r\no=- …"}
3. {"type":"webrtc_ice","client_id":"ws_1","candidate":"candidate:… typ host …","sdpMid":"0"}
```

### Ce qui est établi

Le message **`welcome`** est la clé de la négociation :
```json
{"type":"welcome","client_id":"ws_2"}
```
C'est lui qui attribue l'identifiant WebRTC — une **chaîne** (`ws_2`), distincte
du `client_id` **numérique** du handshake (`connection_info`). C'est cet
identifiant-là qu'il faut reprendre dans `webrtc_offer` et `webrtc_ice`.
Reconstruire `ws_<numéro du handshake>` ne fonctionne pas.

Les candidats ICE du robot arrivent **préfixés `a=`** — à retirer avant
`addIceCandidate`.

### La seconde WebSocket — résolu ✅ (25/07)

`VISION_SET_DETECTION` **ne déclenche pas** le `welcome` sur la WebSocket
principale : le robot n'y renvoie que « Web streaming enabled ». L'hypothèse
d'une seconde socket était la bonne — la signalisation vidéo vit sur un
**port distinct** :

```
ws://<IP>:8766          ← signalisation vidéo, sans paramètre d'URL
ws://<IP>:8765?audience=web   ← canal principal
```

Séquence complète, telle qu'implémentée dans `lib/webrtc.ts` :

1. sur `:8765` — `VISION_SET_DETECTION {enabled:true}`
2. le navigateur ouvre `ws://<IP>:8766`
3. le robot y envoie `{"type":"welcome","client_id":"ws_N"}`
4. navigateur → `{"type":"webrtc_offer","client_id":"ws_N","sdp":…}`
5. robot → `{"type":"webrtc_answer","sdp":…}`
6. échange de `webrtc_ice` (candidats du robot préfixés `a=`, à retirer)

La vidéo circule ensuite en **pair-à-pair** entre le navigateur et le robot.
Un backend ne peut donc rien relayer d'utile : le front se connecte
**directement** au robot sur `:8766`, sans passer par le helper.

Piste alternative plus simple, si le pair-à-pair est bloqué par le réseau :
le service ROS `camera/capture_jpeg` (affichage par images successives).

Services caméra côté ROS : `/camera/capture_jpeg`,
`/camera_publisher_node/enable_web_streaming`, `/camera_publisher_node/enable_yolo_shm`.

---

## 9 bis. Vision — l'événement `vision-detection` ✅

Une fois `VISION_SET_DETECTION` actif, le robot pousse sur le **canal
principal** un événement à ~30 Hz — c'est la sortie du modèle de perception,
disponible **sans** toucher au flux vidéo :

```json
{"type":"event","event":"vision-detection","data":{
  "detections":[
    {"class_id":0,"class_name":"body","type":"body","confidence":1,
     "rect":{"x":239,"y":1,"width":126,"height":192}},
    {"class_name":"head", "rect":{…}},
    {"class_name":"face", "rect":{…}}
  ],
  "skeletons":[
    {"track_id":1,"type":"body",
     "points":[{"x":191,"y":3,"score":0.859}, … 14 points …]}
  ],
  "image_width":640,"image_height":360}}
```

Points à retenir :

- Les coordonnées sont exprimées dans le repère **640 × 360** du modèle, pas
  dans celui de la vidéo affichée : il faut les remettre à l'échelle, et tenir
  compte du letterboxing si la vidéo est en `object-fit: contain`.
- `track_id` persiste entre les trames — c'est du **suivi**, pas de la simple
  détection image par image.
- Classes observées à ce jour : **`body`, `head`, `face`**. Les objets
  « os / balle / peluche » de `interaction_objects.json` sont des items
  **virtuels** du système d'émotions (animations Lottie), pas des classes de
  vision. Le service `/camera_publisher_node/enable_yolo_shm` laisse penser
  qu'un modèle YOLO existe par ailleurs — non confirmé.
- Côté interface : le panneau **Suivi en temps réel** liste une nomenclature
  fixe avec un compteur par classe, **et révèle automatiquement** toute classe
  inconnue qui apparaîtrait. C'est le moyen le plus simple de découvrir ce que
  le modèle embarqué sait réellement détecter — laisser tourner devant une
  balle, une main, un animal, et regarder si une ligne s'ajoute.
- À 30 Hz, ne jamais passer ces trames par l'état React : les stocker dans une
  `ref` et dessiner dans un `requestAnimationFrame` (le compteur affiché, lui,
  est limité à ~6 Hz).

---

## 10. REST `http://<IP>:8088/api/v1/…` ✅

`GET /ai/character` · `POST /ai/character/clear-history` · `/ai/credentials` ·
`/ai/credentials/status` · `/skill/config` · `/logs/`

CORS permissif : appelable depuis une autre origine.

---

## 11. Services ROS 2 utiles (relevés sur le robot)

`/gait_generation_trot/step_move` · `/action_player/{play_reset_action,
get_current_posture, is_playing}` · `/kinematics/set_sparky_mode` (modes
High Performance / Power Saving / **Unlimited Developer**) ·
`/device_modbus/set_motor_torque` · `/emotion_manager/{adjust_emotion,
set_emotion_state, adjust_satiety}` · `/robot_led_controller/led_control` ·
`/lvgl_gui_node/{play_lottie, play_gif, show_toast}` · `/camera/capture_jpeg` ·
`/network/*` · `/ota/*` · `/lifecycle_manager_node/manage_node`

Accès ROS depuis le robot — **penser à l'environnement DDS**, sinon aucun nœud
n'est visible :
```bash
source /opt/ros/humble/setup.bash && source /root/sirius_ros2/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
[ -f /root/cyclonedds.xml ] && export CYCLONEDDS_URI=file:///root/cyclonedds.xml
```

---

## 12. L'écran de la tête et l'état « Ground » ⏳

L'écran de la tête accepte un **swipe vertical** qui bascule un réglage — et
c'est ce geste qui « débraye » le robot quand il s'est mis de lui-même dans
l'état affiché **Ground** après une période d'inactivité.

Deux lectures possibles de ce que fait le swipe, à départager :

| Hypothèse | Équivalent distant | Comment trancher |
|---|---|---|
| Il bascule le **mode robot** | `USER_SET_ROBOT_MODE {"robot_mode":"desktop"\|"ground"}` (§4) | lire `USER_GET_ROBOT_MODE` avant / après un swipe physique : si la valeur change, c'est ça |
| Il **réveille** le robot du sommeil | `ACTION_PLAY` returnPosition priorité 5 (§5) | observer `emotion_state` : `sleeping` → autre |

Le vocabulaire pousse vers la première : l'écran affiche « Ground », le
firmware nomme le mode `ground`. Mais le déclenchement *après inactivité*
ressemble au sommeil (§8) — les deux peuvent d'ailleurs coexister.

**Voie générique — rejouer le geste tactile.** L'écran est piloté par le nœud
`lvgl_gui_node` (paquet `lvgl_ros2_gui`), dont on a relevé le type de message
`lvgl_ros2_gui/msg/TouchState` et les services `play_lottie`, `play_gif`,
`show_toast`. Si le tactile transite par un topic ROS, le swipe est
enregistrable puis rejouable :

```bash
ros2 topic echo <topic tactile>      # pendant un swipe physique
ros2 topic pub --once <topic> <type> '{ … }'   # rejoué à distance
```

Le script **`ecran_tete.sh`** (livré dans le paquet) automatise l'inventaire
puis la capture. Si aucun topic tactile n'apparaît, c'est que LVGL traite
l'événement dans son propre process sans le publier — et la voie WebSocket
reste alors la seule.

---

## 12 bis. Inventaire ROS complet — relevé du 25/07 ✅

Relevé en direct sur le robot (`capteurs.sh`). **31 nœuds, ~130 topics.**
Ce que la doc précédente ignorait, et qui change la donne :

### Capteurs de perception

| Topic | Type | Contenu |
|---|---|---|
| `/state_sensor/tof/distance_array` | `state_sensor_tof/msg/ToFDistanceArray` | **16 distances, grille 4×4, en MILLIMÈTRES** |
| `/state_sensor/tof/heatmap` | `sensor_msgs/msg/Image` | même mesure en `mono16`, 4×4 |
| `/state_sensor/imu_onbody/imu_publisher/imu_data` | `sensor_msgs/msg/Imu` | centrale 6 axes |
| `…/imu_angle` | `geometry_msgs/msg/Vector3` | angles, faible cadence |
| `…/diagnostic` | `diagnostic_msgs/msg/DiagnosticStatus` | « IMU sensor is operating normally » |

### Le ToF, entièrement caractérisé ✅ (étalonné le 25/07)

Le commentaire du fichier `.msg` donne l'agencement, et il est contre-intuitif :

```
# channel排列：从左到右从下往上（左下角为channel1，右上角为channel16）
        haut   [12] [13] [14] [15]
               [ 8] [ 9] [10] [11]
               [ 4] [ 5] [ 6] [ 7]
        bas    [ 0] [ 1] [ 2] [ 3]
                gche            drte
```

**L'origine est en BAS À GAUCHE**, et on remonte. Lire ce tableau comme une
image (origine en haut à gauche) retourne le champ verticalement — l'erreur
coûte cher, elle fait prendre le plancher pour le ciel.

| Grandeur | Valeur mesurée |
|---|---|
| Unité | millimètre |
| Plage | 11 – 2047 mm (2047 = **pas de cible**) |
| Cadence | **≈ 38 Hz** (384 trames en 10 s) |
| Zones | 16, toutes vivantes |

**Signature au repos**, robot debout tête au neutre, champ dégagé :

```
   ··   765    ··    ··      ← horizon : hors portée
  780   786    ··    ··      ← sol lointain
  304   295   291   298      ← sol à ~30 cm
  198   219   218   201      ← sol à ~20 cm, juste devant les pattes
```

Les rangées basses voient le **plancher** à distance croissante. D'où les deux
lectures qui fondent toute navigation autonome :

- **obstacle** → les rangées hautes cessent de saturer, les basses raccourcissent ;
- **vide** (bord de table, marche) → les rangées basses, qui voyaient le sol,
  passent brutalement à 2047.

La **détection de vide est donc gratuite**, avec le capteur d'origine. C'est la
protection la plus importante d'un mode déambulation, et elle ne demande aucun
matériel supplémentaire.

⚠️ Ce profil dépend de l'inclinaison de la tête : il faut le **réapprendre**
après tout mouvement de tête. `deambulation.py` le fait à chaque démarrage.

Le champ `raw_registers` (11 valeurs, souvent 65535) est du débogage : sans intérêt.

### Commande de la tête — canal confirmé ✅ (25/07)

```
topic : /kinematics/ik_subscriber/head_euler_follow
type  : geometry_msgs/msg/Point
unité : RADIANS
```

C'est un topic d'**entrée** du nœud de cinématique inverse : il reçoit une
consigne, il ne publie rien. Vérifié sur le robot — la tête obéit.

- `x` commande le **tangage** (haut / bas) — confirmé de visu.
- `y` commande le **lacet** (gauche / droite).
- `z` : sans effet observable. La tête n'a que deux degrés de liberté.
- 0,10 à 0,35 rad donnent des mouvements progressifs ; au-delà de ~1 rad
  c'est la **butée articulaire**, à éviter. Rester sous 0,35 rad.

Ce canal remplace avantageusement `attitude_control` (§5 ter), jamais confirmé.

**Aucun retour d'angle** : `/kinematics/fk_publisher`,
`/kinematics/ik_subscriber/pose` et `/…/head_quaternion` existent dans le
graphe mais **ne publient rien** (0 trame en 2 s). L'angle de la tête n'est donc
pas lisible — ce qui n'est pas grave : on le **fixe**, donc on le connaît.

### ⚠️ Le ToF est SOUS LE COU, en haut du poitrail ✅

Mesure décisive du 25/07 : la tête basculée de **±0,30 rad (17°)** sur son axe
de tangage, les distances ToF n'ont varié que de **1 à 2 mm**. Sur les trois
axes, aucun écart supérieur à 2 mm.

| axe | écart rangée basse | écart rangée haute |
|---|---|---|
| x (tangage, tête bouge de visu) | 1 mm | 2 mm |
| y (lacet) | 0 mm | 0 mm |
| z | 0 mm | 0 mm |

Un capteur logé dans la tête verrait ses distances au sol changer de plusieurs
dizaines de millimètres pour un tel basculement. Le capteur ne suit donc pas la
tête.

Conséquences, toutes favorables :

- la géométrie du ToF ne dépend **que de l'assiette du corps**, régulée par le
  générateur de démarche — il n'y a aucun angle de tête à suivre ;
- la tête peut regarder ailleurs (suivi de visage, caméra) **sans perturber**
  la navigation ;
- en contrepartie, orienter le capteur pour balayer les côtés est impossible :
  le champ est fixe par rapport au corps, et c'est le corps qu'il faut tourner ;
- et surtout, placé si haut et si en avant, le capteur a **ses propres pattes
  avant dans le bas de son champ**. Au repos elles occultent partiellement les
  zones 0-3 : une main passée devant ne les fait chuter que de 18 %, contre 80 %
  pour les rangées hautes. En marchant, elles **balancent** — elles entrent et
  sortent du champ à chaque foulée.

| rangée | au repos | main devant | chute |
|---|---|---|---|
| 12-15 (haut) | 866 | 168 | **79 %** |
| 8-11 | 838 | 170 | **81 %** |
| 4-7 | 334 | 211 | 37 % |
| 0-3 (bas) | 237 | 195 | **18 %** — occultée |

D'où deux règles de conception : ne jamais fonder la détection de vide sur la
seule rangée 0-3, et **apprendre le fond en marchant** — sinon la première
foulée fait passer les pattes pour un obstacle surgi de nulle part.

Reste l'oscillation du **trot**, qui fait tanguer le corps à chaque foulée et
osciller les distances au sol — d'autant plus fortement que la zone regarde
loin. D'où l'apprentissage du fond **en marchant**, sous forme d'enveloppe
min/max par zone (voir `deambulation.py`).

---

### Ce qui répond aux questions restées ouvertes

- **Le swipe de l'écran** (§12) : le topic existe —
  `/lvgl_gui_node/touch_state` de type `lvgl_ros2_gui/msg/TouchState`.
  Le geste est donc enregistrable puis rejouable (`ecran_tete.sh`).
- **Orientation de la tête** : `/kinematics/ik_subscriber/head_euler_follow`
  (`Point`) et `/head_quaternion` (`Quaternion`) — la voie ROS existe, sans
  dépendre du `attitude_control` non confirmé (§5 ter).
- **Posture réelle** : `/action_player/current_posture` (`String`) — le robot
  la publie, on n'a plus besoin de la déduire.
- **Sommeil** : `/dog/awake` (`Bool`), `/boot/wake_gesture`
  (`sirius_msg/msg/WakeGesture`), `/debug/resleep` (`Empty`).
- **Marche** : `/gait_generation_trot/cmd_vel` (`Twist`) en entrée,
  `/filtered_velocity` en retour.
- **Modes** : `/system/behavior_pause`, `/system/enable_random_action`,
  `/system/orchestration_mode`, `/system/enable_thermal_protection`.

### Nœuds notables jusque-là inconnus

`person_finder_node` (recherche de personne), `gamepad_node` +
`xbox_bluetooth_gamepad` + topic `/joy` (**manette Xbox nativement gérée**),
`hey_sirius_wake_node` (mot de réveil), `face_tracker`, `gait_analysis_node`,
`motion_control_with_action_node`, `picoclaw_bridge_node`,
`production_test_node`, `sync_manager_node`.

### Ce qui n'existe PAS

Aucun topic de chute, de collision, ni de détection de vide. Le
`fall_detector` que je citais dans les versions précédentes de ce document
**n'est pas dans la liste réelle** — c'était une extrapolation, elle est
retirée. Conséquence directe : en déambulation autonome, la protection contre
les bords de table et les escaliers est **à construire**, elle n'est pas
fournie.

---

## 12 ter. Marche par ROS — `cmd_vel` est NORMALISÉ lui aussi ✅ (25/07)

```
entrée : /gait_generation_trot/cmd_vel          geometry_msgs/msg/Twist
retour : /gait_generation_trot/filtered_velocity geometry_msgs/msg/Twist
```

**L'unité est la même que sur le WebSocket : une fraction du débattement dans
[-1, 1], et NON des m/s.** La preuve tient en une ligne de télémétrie :

```
consigne vx=+0.50 → mesuré vx=+0.500   (rapport 1.00)
```

La consigne ressort à l'identique sur `filtered_velocity`, or 0,50 dépasse la
vitesse maximale déclarée du robot (0,24 m/s, §6). Ce ne peut donc pas être des
mètres par seconde.

Conséquence pratique, et c'est le **cinquième visage du même piège** : une
consigne de 0,10 fait *piétiner sur place*, parce que 10 % du débattement ne
suffit pas à déclencher une vraie foulée. À 0,45–0,50, le robot marche
franchement. Ordres de grandeur relevés :

| consigne | comportement observé |
|---|---|
| 0,10 | piétine sur place |
| 0,45 – 0,50 | marche normale |

`filtered_velocity` est le juge de paix : il dit ce que le générateur applique
vraiment, et permet de distinguer « le robot refuse » de « on lui demande trop
peu ».

⚠️ **Le robot ne voit rien derrière lui** : le ToF regarde vers l'avant et il
n'existe aucun capteur arrière. Toute marche arrière est aveugle — à faire à
vitesse réduite et bornée dans le temps.

---

## 13. Les quatre pièges, en résumé

Ils produisent **tous le même symptôme** — un robot qui semble recevoir les
commandes sans rien faire d'utile :

1. **Unité de vitesse** — normalisée [-1,1], pas des m/s (§3).
2. **Mode robot** — `desktop` bride la démarche (§4).
3. **Priorité d'action** — un `ACTION_PLAY` en priorité 1 se fait écraser (§5).
4. **Sommeil** — accroupi, il n'exécute rien d'utile (§8).

À quoi s'ajoute, côté protocole, le piège des **noms en majuscules** (§2.2).
