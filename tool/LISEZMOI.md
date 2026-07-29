# Studio 360 pour Sirius — mode d'emploi

**Studio 360** — kit de développement *pour Hengbot Sirius, projet
indépendant*.

> **Projet indépendant d'explorations360, sans lien ni affiliation avec
> Hengbot.** Sirius et Hengbot sont des marques de leurs propriétaires
> respectifs. Ce kit est le fruit d'un travail de rétro-ingénierie de l'API du
> robot : il n'est ni fourni, ni approuvé, ni soutenu par le constructeur.

> ## ⚠️ À qui s'adresse ce kit — à lire avant de commencer
>
> **Cet outil s'adresse à des personnes qui savent coder et qui savent ce
> qu'elles font.** Il pilote un robot réel : des moteurs qui bougent, un
> appareil qui marche, se lève et peut tomber. Il ne comporte aucun
> garde-fou parental, aucune authentification, et il expose des commandes
> issues de rétro-ingénierie que le constructeur ne documente pas.
>
> **Fourni tel quel, sans assistance et sans garantie d'aucune sorte.**
> Personne ne s'engage à répondre à une question, à corriger un défaut, ni à
> maintenir la compatibilité avec les futurs firmwares. Certaines commandes
> sont marquées « non vérifiées » : elles peuvent ne rien faire, ou faire
> autre chose que ce qu'on croit.
>
> **Vous êtes seul responsable de votre robot, de son environnement et de ce
> qui pourrait être endommagé.** Utilisez-le sur un sol plat et dégagé, en
> restant à portée de main, et n'exécutez pas une commande dont vous ne
> comprenez pas l'effet. Si ces conditions ne vous conviennent pas, ne
> l'utilisez pas.


*L'outil s'appelait « Sirius Studio » jusqu'à la v2.6 ; renommé à la v2.7 pour
ne plus se confondre avec l'application officielle du constructeur. Les archives
déjà diffusées gardent leur nom de fichier.*

**L'interface s'installe sur le téléphone (rendu fonctionnel en v2.8.1).** Par
défaut le helper n'écoute que sur ce PC ; lance **`demarrer_telephone.bat`** pour
le rendre joignable depuis le Wi-Fi. La fenêtre affiche alors l'adresse à taper
dans le navigateur du téléphone (la ligne « à ouvrir sur le téléphone » — même
réseau que le PC). Ouvre-la, puis « Ajouter à l'écran d'accueil » : l'application
s'ouvre en plein écran, sans barre d'adresse, avec sa propre icône. Les cinq
écrans sont utilisables à 390 px de large, et le zoom reste actif si tu en as
besoin.

⚠️ Le mode téléphone rend le pilotage du robot accessible à **tout le Wi-Fi, sans
mot de passe** : à n'utiliser que sur un réseau de confiance. Le coupe-circuit
reste actif, et le mode PC (`demarrer.bat`) n'expose rien.

Sur iPhone, l'ajout à l'écran d'accueil suffit. Sur Android, Chrome réserve la
proposition d'installation aux adresses sécurisées : la page reste parfaitement
utilisable, mais sans l'installation en un clic — c'est une contrainte du
navigateur, pas du kit.

**Le thème suit maintenant l'ordinateur.** Le bouton de la barre du haut
parcourt sombre, clair, puis « système ». Dans ce dernier mode, l'interface
bascule avec le réglage jour/nuit de la machine, même en cours d'utilisation.
Le thème choisi s'applique désormais avant le premier affichage : plus de flash
clair au chargement.

La version s'affiche à trois endroits : dans la fenêtre noire au démarrage,
sur l'écran de connexion, et dans la barre du haut de l'interface. Elle vient
du fichier `VERSION.txt` — un seul endroit à changer, tout suit.

---

## Démarrage

### Avec ton robot

1. Allume le robot, vérifie qu'il est sur **le même réseau Wi-Fi** que ton PC.
2. **Double-clique `demarrer.bat`** — le navigateur s'ouvre tout seul.
3. **Saisis l'adresse IP du robot dans l'interface**, puis clique « Connecter ».
   Elle est mémorisée : les fois suivantes, un clic sur l'adresse récente suffit.

L'IP du robot s'affiche sur son écran, dans le menu Réseau.

### Sans robot (découverte, démonstration)

**Double-clique `demarrer_simulateur.bat`**, puis connecte-toi à `127.0.0.1`
dans l'interface. Un robot simulé répond, avec des données calquées sur les
mesures du vrai. Rien ne peut être endommagé — idéal pour montrer l'outil.

### Déambulation — le robot se promène seul

L'onglet **Déambulation** montre ce que le robot perçoit devant lui (son capteur
de distance, seize zones en grille 4×4), ce qu'il en déduit, et permet de le
lancer. Mais l'évitement lui-même tourne **à bord du robot** : le capteur de
distance n'existe que sur le ROS embarqué, jamais sur le canal réseau que parle
ce kit. Il faut donc y déposer un fichier, une fois :

```
scp deambulation.py root@<IP_DU_ROBOT>:/root/
ssh root@<IP_DU_ROBOT>
python3 /root/deambulation.py --service
```

L'onglet Déambulation devient alors vivant. Tant que ce programme ne tourne pas,
il affiche « service injoignable » — c'est normal, il ne manque que ça.

> ⚠️ **SOL PLAT UNIQUEMENT.** Jamais sur une table, un plan de travail ou un lit,
> jamais près d'un escalier, d'une marche ou d'un bord. Le robot sait voir un
> obstacle devant lui, et sait *en principe* voir le vide — mais **cette
> détection du vide n'a jamais été éprouvée au bord d'un vrai dénivelé** : ne
> comptez pas dessus. Il ne voit rien derrière lui. Restez à portée de main.
>
> Au lancement, **rien ne bouge** : le programme observe et écrit ce qu'il ferait.
> Le robot ne marche que si vous cliquez **Démarrer**. **Arrêter**, ou les touches
> **Échap** et **Espace**, le stoppent et remettent les consignes à zéro.

### Sur le téléphone

**Double-clique `demarrer_telephone.bat`** (au lieu de `demarrer.bat`). La
fenêtre affiche une adresse du type `http://192.168.x.x:8787` : tape-la dans le
navigateur de ton téléphone, sur le **même Wi-Fi** que le PC, puis « Ajouter à
l'écran d'accueil » pour l'installer.

⚠️ Ce mode ouvre le pilotage du robot à tout le réseau Wi-Fi, **sans mot de
passe** — réseau de confiance uniquement.

> La première utilisation installe les dépendances Python (~30 s). Ensuite le
> démarrage est immédiat. Python doit être installé — https://www.python.org/downloads/
> en cochant **« Add Python to PATH »**.

Pour tout arrêter : ferme la fenêtre noire.

---

## ⚠️ Le réglage à connaître : Sol ou Bureau

Le robot a deux **environnements**, et c'est le piège numéro un :

- **Bureau** — il bride sa démarche et ses mouvements amples pour ne pas tomber
  d'une table. Résultat : **il bouge les pattes sans avancer**.
- **Sol** — démarche complète, déplacements réels.

Sorti d'usine il est en mode **Bureau**. Si ton robot piétine sur place, c'est
presque toujours ça — pas la batterie, pas le réseau. Le réglage est dans
**Dashboard → Modes & comportement → Environnement**.

Autre chose utile : le robot **s'endort après un moment d'inactivité** et se
met accroupi. Dans cet état, un ordre de marche ne donne rien. Réveille-le en
jouant une action (par exemple « Posture debout standard ») avant de le piloter.

Sur le robot, ce réglage se change aussi par un **swipe vertical sur l'écran de
la tête**. Le bouton **Sol / Bureau** de l'interface fait la même chose à
distance ; le bouton **Redresser** joue le rôle du réveil.

---

## L'interface

**Dashboard** — batterie, températures moteurs, posture, émotion, nœuds ROS,
vue caméra, pilotage rapide, actions favorites.

**Pilotage** — deux joysticks comme sur la manette Xbox : le gauche pour la
translation, le droit pour l'orientation. Souris et tactile. Au clavier :
`W`/`S` avancer-reculer, `A`/`D` latéral, `Q`/`E` rotation, **`Espace` = arrêt**.
En dessous : télémétrie en direct et journal des appels d'API.

Le sélecteur **Posture** couche et relève le robot. « Debout » rejoue exactement
l'action du bouton Reset — c'est la voie sûre, capturée sur l'interface
officielle. « Au sol » cherche l'action correspondante dans la bibliothèque de
ton robot et t'affiche le nom retenu : vérifie du regard que c'est bien la
bonne la première fois.

**Tête** — un troisième joystick, à part, sur la page Pilotage. Il est
*collant* : la tête garde la direction qu'on lui donne quand on lâche le
pommeau, ce qui est le comportement utile pour regarder autour de soi avec la
caméra. Le bouton **Recentrer** la ramène au neutre. L'amplitude est bridée à
±26° en lacet et ±20° en tangage, sous le domaine déclaré du robot. Cette
commande est la seule du kit qui n'ait pas encore été confirmée sur le
matériel : si la tête ne bouge pas, bascule le sélecteur sur **Corps** et
regarde la réponse du robot dans le journal d'API — elle nous dira lequel des
deux noms de champ est le bon.

**Vue caméra** (sur le Dashboard) — le flux vidéo arrive en direct du robot,
en pair-à-pair. Par-dessus l'image, les **boîtes de détection** et les **points
du squelette** sont dessinés en temps réel. Juste en dessous, le panneau
**Suivi en temps réel** liste ce que la vision sait reconnaître avec, en face
de chaque nom, le nombre d'objets actuellement suivis : `Corps (1)`,
`Main (0)`… Une classe inconnue qui apparaîtrait s'ajoute d'elle-même à la
liste — c'est ainsi qu'on découvrira ce que le modèle embarqué sait vraiment
détecter.

**Actions** — la bibliothèque du robot, filtrable, avec traduction française
des noms (le robot les stocke en chinois).

**Système** *(nouveau en v2.7)* — la page de diagnostic, et celle qui dit le
plus franchement ce que le robot **ne mesure pas**.

- *Vision* — les interrupteurs de détection et de suivi de visage, et les
  compteurs de la perception en temps réel : `face`, `body`, `head`, la cadence
  des trames et l'âge de la dernière.
- *Thermique* — la **température de la batterie** est la seule que le robot
  publie vraiment, et elle est affichée. Les **quatre sondes de patte sont
  muettes** sur ce firmware : elles renvoient 0, c'est écrit à l'écran plutôt
  que maquillé. La **température CPU n'est pas disponible**, et l'interface dit
  pourquoi : elle n'existe ni sur le WebSocket ni sur l'API REST du robot ; sa
  seule source connue est un topic ROS interne (`/fan_breathing/cpu_temp`) que
  rien ne relaie vers le pont web. Un tiret honnête vaut mieux qu'un chiffre
  inventé.
- *Moteurs* — la charge des 14 moteurs et l'état du coupe-circuit.
- *Métriques* — processeur, disque, nœuds ROS actifs, réseau, fraîcheur du lien.

⏳ **Deux interrupteurs de cette page ne sont pas éprouvés**, et l'interface le
signale : la **protection thermique des moteurs**
(`MOTOR_SET_THERMAL_PROTECTION`) et le **suivi de visage**
(`VISION_SET_FACE_TRACKING`). Leur nom réseau est sûr, leur effet ne l'est pas —
et pour le second, le nœud `face_tracker` **ne tourne pas** sur ce firmware : la
commande sera sans doute acceptée sans que rien ne bouge. Si tu constates le
contraire sur ta machine, dis-le-nous : c'est exactement ce qu'on cherche à
savoir.

📌 Il s'agit de **détection** de visage — savoir qu'un visage est là et où il
est. **Pas de reconnaissance faciale identitaire** : le robot ne sait pas *qui*
est devant lui, et rien dans son API ne le permet.

**Modes & comportement** (sur le Dashboard) — l'environnement Sol/Bureau, le
mode autonome, les actions aléatoires, l'interaction IA et le déclenchement
vocal. Le **mode autonome** mérite attention : quand il est actif, le robot
décide seul et peut annuler tes commandes.

Un bouton **Arrêt** reste accessible en permanence dans la barre du haut, à
côté de l'interrupteur **autonome / manuel**. Depuis la v2.7, cet interrupteur
agit pour de bon sur le robot — il envoyait auparavant sa bascule à l'affichage
seulement.

---

## Sécurité

Trois protections se cumulent.

**Le robot** écrête lui-même les angles articulaires et son espace de travail
(`joint_clamp_enabled`, `ws_clamp_enabled`) et détecte les sauts d'angle.

**Le helper** refuse les consignes hors domaine *avant* de les envoyer. Limites
relevées sur le robot : avant 0,24 m/s, arrière 0,16 m/s, latéral ±0,20 m/s,
rotation ±1,2 rad/s, pitch et roll ±30°.

**Le coupe-circuit** surveille la charge des 14 moteurs. Au-delà de
**850 ‰ maintenus 0,8 s**, il arrête le robot et verrouille les commandes
jusqu'à réarmement depuis l'interface. Seuil calibré sur mesures réelles : le
fonctionnement normal plafonne à ~540 ‰ quelle que soit l'allure, un moteur en
butée dépasse 950 ‰ de façon *soutenue*.

L'arrêt est **vérifié** : le helper répète l'ordre jusqu'à ce que la télémétrie
confirme la vitesse nulle, et alerte si ce n'est pas le cas.

### Bonnes pratiques

Robot **au sol**, espace dégagé, gardé à l'œil lors des premiers essais.
Désactive le **mode autonome** pendant tes tests (interface officielle du robot
→ Inner World) : sinon il reprend la main et annule tes commandes. Évite les
sessions très longues en continu, les moteurs chauffent.

---

## Contenu du dossier

```
VERSION.txt                  le numéro de version du kit
demarrer.bat                 lancement avec le robot
demarrer_simulateur.bat      lancement sans robot
demarrer_telephone.bat       lancement en mode réseau (accès téléphone)
sirius_helper.py             le pont robot ↔ navigateur (+ sécurité)
deambulation.html            la page Déambulation, servie sur /deambulation
deambulation.py              l'évitement d'obstacles — à DÉPOSER SUR LE ROBOT
                             (voir « Déambulation » plus haut · sol plat)
mock_robot.py                le robot simulé
ui/                          l'interface web
lire_limites_servos.sh       relevé des limites (avancé, SSH)
ecran_tete.sh                diagnostic de l'écran de la tête (avancé, SSH)
```

---

## Nouveautés de la v2.8.5

- **LED — pilotage mini-LED par mini-LED.** Les deux oreilles s'affichent en
  cercles (6 points chacune, 1 = midi, sens horaire) et se pilotent LED par LED,
  comme les 6 LED de dos ; un mode **Identifier** allume une diode à la fois. Les
  4 voyants des jonctions/queue ne sont pas colorables : ce sont les témoins de
  batterie (relevé du manuel officiel). Le helper passe de 2 à 12 canaux de tête.
- **Plan Humeur corrigé.** Valence / éveil / satiété sont lus sur l'échelle 0–100
  du robot : le curseur reflète enfin l'état réel (couché = calme, en bas) au lieu
  de rester bloqué en haut.
- **Vie du robot réorganisée** : Volume audio et Écran de la tête remontés,
  Interactions récentes et Dialogue IA regroupés au-dessus de la charge moteurs.
- **Interface principale** : bouton **Reset** dans la barre du haut, et
  **Recovery** (affiché **Relever** en français) corrigé — il déclenche la vraie
  mécanique de relevage après chute (`/api/recovery`), distincte de la remise debout.
- **Déambulation** : un bandeau en tête de page rappelle que rien ne fonctionne
  sans le service embarqué (à lancer en SSH / par `deambulation_robot.bat`), avec
  lien vers le wiki ; et **anticipation du vide renforcée** (nœud v16) — arrêt
  immédiat dès qu'un vide est suspecté, et détection d'un bord franc sur une seule
  zone pour rattraper les approches en diagonale. ⚠ Réduit le risque, ne rend pas
  la table sûre : reste à portée de main.
- **README anglais** ajouté à côté du LISEZMOI.

## Nouveautés de la v2.8.4

**Les nouveaux outils sont des onglets de l'interface principale** — plus rien
à ouvrir à part. Ordre du menu : Dashboard · Système · Vie du robot · Actions ·
Enchaînements · Pilotage · Déambulation.

- **Vie du robot** — tableau de bord : humeur du robot (plaisir, éveil,
  satiété, fatigue), **volume audio**, **LED** (2 à la tête, 6 sur le corps),
  **écran de la tête** (message texte et animations de sa bibliothèque),
  batterie, réseau, charge des 14 moteurs, interactions tactiles, journaux,
  réinitialisation de la mémoire du dialogue IA.
- **Enchaînements** — éditeur « Play Blocks » : animations, groupes à tirage
  aléatoire, pauses et blocs d'errance mis bout à bout, en boucle ou non ;
  sauvegarde sur le PC, export/import JSON.
- **Déambulation** — refondue en trois colonnes (voir / mesurer / agir), avec
  **marche pas-à-pas** (déplacements bornés en foulées), bouton **Réveil /
  Debout** et caméra à la demande.
- **`deambulation_robot.bat`** — dépose le nœud sur le robot et lance son
  service avec le bon environnement ROS, en un double-clic.
- Correctifs : fin du biais gauche à l'évitement, recul sur détection de vide
  désormais borné, bouton « Recentrer » de la tête qui commande réellement le
  robot, et suppression d'une interrogation en boucle qui saturait le pont.

⚠️ **L'interface (`ui/`) est un build patché à la main** pour ajouter ces
onglets et deux correctifs. Un futur rebuild du frontend depuis les sources
écraserait ces modifications : il faudra les réappliquer.


Cette version ajoute plusieurs modules, tous reliés par une **navigation commune**
en haut de chaque page. Point d'entrée : **`/accueil`** (ouvre depuis n'importe
quelle page via le menu « Accueil »).

- **Accueil** (`/accueil`) — un hub avec une tuile par module.
- **Enchaînements** (`/enchainements`) — éditeur « Play Blocks » : on place des
  animations, des groupes (tirage aléatoire), des pauses et des blocs
  « auto-wander » les uns après les autres, puis on lance le cycle (en boucle ou
  arrêt en fin de cycle). Les enchaînements se sauvegardent sur le PC (via le
  helper) avec repli navigateur et export/import JSON.
- **Yeux** (`/yeux`) — contrôleur du regard (direction, dilatation, rotation,
  clignement) et expressions prédéfinies, avec aperçu à l'écran. Voie UDP 8770.
  ⚠ effet sur l'écran du robot non encore éprouvé.
- **Vie & Système** (`/tableau`) — tableau de bord : humeur (valence/éveil/
  satiété/fatigue), **volume audio**, batterie, réseau, charge par moteur (14),
  interactions tactiles, journaux, réinitialisation de la mémoire du dialogue.
- **Déambulation** — deux ajouts : bouton **Réveil / Debout** (réveille et fige
  le robot debout : mode sol + autonome en pause + redressement tenu — utile au
  premier démarrage), et **marche pas-à-pas** (déplacements bornés en foulées).
- **Volume audio** — réglable de 0 à 100 (paramètre `audio_volume` du nœud
  `wmix_audio_player_node`, commande vérifiée sur l'interface officielle).
- Correctifs du nœud de déambulation (v15) : fin du biais gauche à l'évitement,
  recul déclenché par un vide désormais borné, et animation optionnelle jouée à
  l'approche d'un obstacle avant le recul.

## En cas de souci

**« Impossible de joindre le robot »** — vérifie l'IP, et que robot et PC sont
sur le même réseau.

**Le navigateur ne s'ouvre pas** — va sur http://127.0.0.1:8787

**« Python introuvable »** — installe Python en cochant « Add Python to PATH ».

**Il bouge les pattes mais n'avance pas** — deux causes possibles :
il est en mode **Bureau** (bascule sur **Sol** dans Modes & comportement),
ou la vitesse demandée est trop faible. Monte le curseur de vitesse : à
0,24 m/s le robot marche à pleine amplitude.

**Il ne réagit pas du tout** — soit il dort (joue une action pour le réveiller),
soit le **mode autonome** est actif et annule tes commandes (coupe-le dans
Modes & comportement).

**Voir ce qui se passe** — l'API du helper est documentée et testable sur
http://127.0.0.1:8787/docs
