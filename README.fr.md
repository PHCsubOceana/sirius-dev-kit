# Sirius Dev Kit

Documentation développeur et outil de pilotage par navigateur pour le robot-chien
**Hengbot Sirius** — reconstitués à la mesure, sur une vraie machine, parce que la
documentation du constructeur s'arrête au mouvement et que sa fiche technique ne
mentionne **aucun capteur**.

Tout ce qui est ici a été vérifié sur un robot physique. Quand ça ne l'a pas été,
c'est écrit.

> **Projet indépendant d'explorations360, sans lien ni affiliation avec
> Hengbot.** Sirius et Hengbot sont des marques de leurs propriétaires
> respectifs. Ce kit est le fruit d'un travail de rétro-ingénierie de l'API du
> robot : il n'est ni fourni, ni approuvé, ni soutenu par le constructeur.

🇬🇧 [English version](README.md) · Référence technique complète :
[`docs/sirius-api-fr.md`](docs/sirius-api-fr.md)

---

## Commencez par là : les cinq pièges

Si votre Sirius accuse réception de vos commandes sans rien faire d'utile, la
réponse est presque toujours dans cette liste. Les cinq produisent le *même*
symptôme : un robot qui répond, renvoie fidèlement la valeur reçue, et piétine.

**1. La vitesse est normalisée, pas en m/s.** `linear_x`, `linear_y` et
`angular_z` attendent une valeur dans `[-1, 1]` — une fraction du débattement.
Envoyer `0.15` demande 15 % de la vitesse maximale, pas 0,15 m/s : la foulée
devient minuscule et le robot marche sur place. La documentation officielle le
dit pour l'API `Control_Move` — mais la même convention s'applique
**silencieusement** à `gait_control` sur le WebSocket et au topic ROS
`/gait_generation_trot/cmd_vel`, où rien ne prévient. Preuve : une consigne
`vx = 0,50` ressort à `0,500` sur `filtered_velocity`, ce qui dépasse la vitesse
maximale déclarée du robot — ce ne peut donc pas être des mètres par seconde.

**2. Le robot sort d'usine en mode `desktop`**, qui bride volontairement la
démarche pour qu'il ne tombe pas d'une table.
`USER_SET_ROBOT_MODE {"robot_mode":"ground"}` le libère.

**3. La priorité d'action.** Un `ACTION_PLAY` joué en priorité 1 (la valeur par
défaut) se fait écraser par le comportement autonome en cours. Il faut la
**priorité 5**.

**4. Les noms de commandes sont en MAJUSCULES sur le fil.**
`BEHAVIOR_SET_PAUSE`, et non `set_behavior_pause` — les noms en minuscules
trouvés dans les binaires sont les handlers internes. Cinq exceptions n'existent
qu'en minuscules, et ce sont précisément celles qui font bouger le robot :
`gait_control`, `gait_step_move`, `attitude_control`, `self_recover`,
`set_motion_mode`.

**5. Aucun nœud ROS visible ?** Il manque l'environnement DDS. Sans
`RMW_IMPLEMENTATION=rmw_cyclonedds_cpp`, `ros2 node list` renvoie une liste vide
alors que le robot tourne parfaitement.

---

## Ce que la doc omet, et ce que nous avons mesuré

Le constructeur documente une application, une API Python et une API WebSocket de
keyframes. Il ne documente **aucune lecture de capteur** — la section
Spécifications ne mentionne ni ToF, ni centrale inertielle, ni même la caméra.
Pas un mot sur ROS 2, alors qu'une version EDU est vendue sur cet argument.

Mesuré sur la machine :

| | |
|---|---|
| **Capteur ToF** | `/state_sensor/tof/distance_array`, `state_sensor_tof/msg/ToFDistanceArray`. **Millimètres**, plage 11–2047 (2047 = pas de cible), ~38 Hz, 16 zones en grille 4×4 |
| **Origine de la grille** | **en bas à gauche** — canal 1 en bas à gauche, 16 en haut à droite. La lire comme une image retourne le champ verticalement et fait prendre le plancher pour le ciel |
| **Position du capteur** | **sous le cou, en haut du poitrail — solidaire du corps, pas de la tête.** Basculer la tête de 17° ne déplace les mesures que de 1 à 2 mm. Sa géométrie ne dépend donc que de l'assiette du corps, et la tête reste libre de regarder ailleurs |
| **Auto-occultation** | Il voit ses **propres pattes avant** en bas du champ (une main passée devant ne fait chuter la rangée basse que de 18 %, contre 80 % pour les rangées hautes) et sa **propre mâchoire** en haut — obstacle fantôme à 191 mm, écart-type 5 mm sur dix sessions |
| **Détection de vide, gratuite** | Les rangées basses voient le plancher à ~20 et ~30 cm. S'il disparaît — bord de table, marche — elles saturent à 2047. ⚠️ **Jamais éprouvée sur un vrai bord.** Ne pas la considérer comme une sécurité acquise |
| **Commande de la tête** | `/kinematics/ik_subscriber/head_euler_follow` (`geometry_msgs/Point`), **radians** : `x` = tangage, `y` = lacet, `z` sans effet. Rester sous 0,35 rad. Aucun retour d'angle n'existe |
| **Centrale inertielle** | `/state_sensor/imu_onbody/imu_publisher/imu_data` et `…/imu_angle` — lisible, et absente de la fiche technique |
| **Charge moteur** | `motor-load`, 14 moteurs, ±1000 ‰ de PWM. Pic normal ~540 ‰ à toute allure ; un moteur en butée tient 950–985 ‰. **Le discriminant est la durée, pas l'amplitude** |
| **Caméra** | Fonctionne en WebRTC, signalisation sur le port **8766** (et non 8765) — alors que la doc de l'application annonce la transmission d'image « non disponible actuellement » |
| **Trois vitesses maximales contradictoires** | Fiche technique 0,4 m/s · doc de l'API WebSocket 0,28 m/s · `ros2 param dump` sur la machine 0,24 m/s. C'est la dernière qui gouverne le comportement réel |

Le détail complet — le protocole à 59 commandes, l'inventaire ROS (29 nœuds
distincts, ~130 topics) — est dans [`docs/`](docs/).

---

## L'outil de pilotage

`tool/` c'est **Studio 360 pour Sirius** — **Studio 360** en
court : un pont Python local (FastAPI) qui parle WebSocket au robot et sert une
interface React à votre navigateur. La vidéo va
**directement du robot au navigateur** en WebRTC — un backend peut relayer la
signalisation, jamais le flux.

Deux joysticks pour marcher et s'orienter, un troisième pour la tête, la caméra en
direct avec les détections dessinées par-dessus, la bibliothèque d'actions du
robot avec ses noms chinois traduits, la télémétrie des 14 moteurs, le journal des
appels d'API, le bascule Sol / Bureau, et un **coupe-circuit qui arrête le robot
au-delà de 850 ‰ de charge moteur maintenus 0,8 s**.

L'interface est **bilingue français / anglais** — un bouton FR / EN dans la barre
du haut.

> **À propos du nom.** L'outil s'appelait *Sirius Studio* jusqu'à la v2.6
> incluse — un nom trop facilement confondu avec l'application **officielle** de
> Hengbot. À partir de la **v2.7**, il s'appelle **Studio 360 pour
> Sirius** (*Studio 360*). Les archives déjà diffusées gardent leur nom de
> fichier — `SiriusStudio_v1.9` à `SiriusStudio_v2.6` — pour ne casser aucun
> lien de téléchargement existant. Les noms de scripts, les routes du pont et
> les commandes réseau sont inchangés.

### Le lancer

Windows, Python 3 installé en cochant **« Add Python to PATH »** :

```
1. Allumez le robot, sur le même réseau Wi-Fi que votre PC.
   Son adresse IP s'affiche sur l'écran de sa tête, menu Réseau.
2. Double-cliquez tool/demarrer.bat — le navigateur s'ouvre sur
   http://127.0.0.1:8787
3. Saisissez l'IP du robot dans l'interface, puis cliquez « Connecter ».
```

La première utilisation installe `fastapi`, `uvicorn`, `websockets` et `httpx`,
une seule fois, en une trentaine de secondes.

**Pas de robot ?** Double-cliquez `tool/demarrer_simulateur.bat` et connectez-vous
à `127.0.0.1`. Un robot simulé répond, au **vrai protocole**, avec des données
calquées sur les mesures relevées sur la machine réelle. Rien ne peut être
endommagé — c'est aussi la façon la plus rapide de voir à quoi ressemble le
protocole.

Les lanceurs sont des `.bat` Windows ; le pont Python lui-même est
multiplateforme, mais n'a pas été testé ailleurs.

### ⚠️ Avant de faire bouger quoi que ce soit

**Au sol, jamais sur une table.** Rien dans ce robot ne détecte le vide, et notre
détection de vide n'a jamais été éprouvée sur un vrai bord. Deux mètres dégagés
devant. **Coupez le mode autonome**, sinon le comportement embarqué reprend la
main et annule vos commandes. Le robot **ne voit rien derrière lui** : toute
marche arrière est aveugle. Gardez un moyen d'arrêt à portée de main *avant* de
lancer quoi que ce soit.

Ce kit est fourni tel quel, sans garantie. Il pilote du matériel qui peut tomber
ou se coincer une articulation.

---

## Comment lire les affirmations

Chaque affirmation de ces documents relève de l'un de quatre états, et
[`docs/data.json`](docs/data.json) porte l'état de chaque valeur, une par une :

**vérifié** — mesuré sur le robot · **documenté** — écrit par le constructeur ·
**déduit** — tiré du firmware ou du comportement, jamais confirmé ·
**à confirmer** — hypothèse de travail, pas un fait.

Le firmware sur lequel tout ceci a été mesuré est la **2.5.0 bêta**, installée le
23 juillet 2026 — relevée dans le Centre de mise à jour du robot lui-même, qui
affiche « System is up to date ». Le constructeur tient deux canaux : RELEASE
(3 versions stables) et BETA (8 versions de test).

**Où lire les notes de version.** Hengbot tient un journal détaillé, version par
version — mais uniquement *à l'intérieur* de la page System Update de sa console,
accessible une fois un robot connecté. Rien n'est publié sur le web, aucun moteur
de recherche ne l'indexe : c'est pourquoi on ne le trouve pas en cherchant. Le
résumé des onze entrées est dans
[`docs/firmware-changelog-fr.md`](docs/firmware-changelog-fr.md). Il répond à
plusieurs questions que la documentation officielle laisse ouvertes, dont ce que
fait vraiment le balayage sur l'écran de la tête : il déverrouille l'écran et
réveille le robot, il **ne change pas** le mode robot.

Un avertissement pour finir : le paquet source `sirius_full_v2.3.6` livré avec les
outils OTA est **plus ancien que le firmware installé**, et ses noms de nœuds ne
correspondent plus. La note de version 2.5.0 dit pourquoi, dans les mots du
constructeur : les nœuds de comportement et d'émotion ont été supprimés et fusionnés
dans un nœud unique de pilotage par arbre de comportement. Fiez-vous à ce qui
répond sur la machine.

---

## Crédits

Travaux indépendants antérieurs de [**dspeers**](https://github.com/dspeers) —
[`sirius-control-panel`](https://github.com/dspeers/sirius-control-panel) et
[`sirius-voice-bridge`](https://github.com/dspeers/sirius-voice-bridge). Le REST
sur `:8088` et le flux MJPEG sur `:8080` ont été trouvés indépendamment de part et
d'autre ; **il les a publiés le premier**.

Documentation officielle du constructeur :
[hengbot-dynamics.github.io/heng-docs](https://hengbot-dynamics.github.io/heng-docs/docs/intro).

Réalisé par [explorations360](https://explorations360.com) — le récit complet est
sur [explorations360.com/sirius](https://explorations360.com/sirius).

Les corrections sont bienvenues. Si vous vérifiez l'un des points marqués
incertains — le topic de gestes, la détection de vide sur un vrai bord, le mode
Développeur de l'écran de tête — ouvrez une issue.

Sous licence **Apache 2.0**, voir [LICENSE](LICENSE) et [NOTICE](NOTICE).

Le fichier `NOTICE` précise deux choses qui comptent ici : ce projet n'est ni
affilié ni approuvé par Hengbot et la licence ne concède aucun droit sur leurs
marques (section 6 de la licence) ; et la documentation du protocole a été
établie par observation d'un robot acquis régulièrement — trafic réseau,
inventaire ROS, fichiers lisibles présents sur la machine — sans décompilation
ni désassemblage, et sans reproduire une ligne du code du constructeur.
