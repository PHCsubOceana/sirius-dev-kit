# Le journal de version du firmware Sirius

> **Dossier `site_web` — révision `r19` · 29 juillet 2026.**
> Ce qui a changé depuis `r7` est listé dans **`JOURNAL.md`**, à lire en premier.

*Nouveau en r3 — contenu inchangé depuis. Ce document décrit le firmware du
constructeur ; il n'est pas concerné par le renommage de notre outil en r8.*

*Relevé le 26 juillet 2026 dans le Centre de mise à jour du robot, à l'adresse
`http://8.163.38.44:8082/<version>/ota-update`. Cette page n'est accessible
qu'après avoir connecté un robot : c'est pour cela qu'aucun moteur de recherche
ne l'indexe, et que ce journal n'existe nulle part ailleurs sur le web.*

**Version installée sur notre machine : `2.5.0`, canal bêta, 23 juillet 2026,
107,54 Mo.** Le Centre de mise à jour affiche « System is up to date ».

Deux canaux coexistent : **RELEASE** (3 versions stables) et **BETA**
(8 versions de test). Les notes ci-dessous résument celles du constructeur ; le
texte d'origine est en anglais.

---

## Canal bêta

| Version | Date | Taille | Ce que le constructeur annonce |
|---|---|---|---|
| **2.5.0** *(installée)* | 23/07/2026 | 107,54 Mo | Suppression des nœuds de comportement et d'émotion, **fusionnés dans un nœud unique de pilotage par arbre de comportement** |
| 2.4.9 | 22/07/2026 | 105,75 Mo | Confort du **geste de réveil par balayage vers le haut** amélioré ; correction d'une désynchronisation de l'horloge au démarrage |
| 2.4.8 | 16/07/2026 | 105,76 Mo | Capacités d'interaction IA étendues ; **localisation multilingue** des textes ; l'entrée « Réglages » de l'écran remplacée par l'appairage manette |
| 2.4.7 | 02/07/2026 | 110,93 Mo | Charge processeur réduite de 45 % ; **passage à WebRTC** pour le flux vidéo web ; émotions passées en GIF ; **détection de squelette humain** ajoutée à la vision ; **déverrouillage d'écran par balayage vers le haut et mise en veille par balayage vers le bas** ; logique manette revue |
| 2.4.6 | 10/06/2026 | 87,67 Mo | Mise à jour du firmware bas niveau, **protection contre la surcharge de couple** ajoutée ; charge processeur réduite d'environ 20 %. *Extinction automatique après mise à jour, redémarrage manuel nécessaire* |
| 2.4.5 | 03/06/2026 | 85,54 Mo | Correction du tremblement au démarrage ; **protocole d'API mis à jour** ; tous les mouvements réoptimisés ; journal ajouté à la page de gestion des nœuds ; canal d'interaction Bluetooth |
| 2.4.4 | 09/04/2026 | 97,98 Mo | Paquet complet, sans notes |
| 2.4.3 | 07/04/2026 | 97,46 Mo | Paquet complet, sans notes |

## Canal stable

| Version | Date | Taille | Ce que le constructeur annonce |
|---|---|---|---|
| 2.4.8 | 17/07/2026 | 105,76 Mo | Reprise des apports bêta 2.4.6 à 2.4.8 : firmware bas niveau et protection de couple, −45 % de processeur, WebRTC, GIF, squelette, balayages haut/bas, manette, IA, multilingue. *Extinction automatique après mise à jour* |
| 2.4.5 | 09/06/2026 | 85,54 Mo | Identique à la bêta 2.4.5 |
| 2.4.3 | 07/04/2026 | 97,46 Mo | Paquet complet, sans notes |

---

## Ce que ce journal règle, et qui traînait depuis le début

### Le balayage sur l'écran de la tête n'a rien à voir avec le mode Sol / Bureau

C'était la question ouverte la plus ancienne du projet. Réponse du constructeur,
version 2.4.7 : le balayage **vers le haut déverrouille l'écran**, le balayage
**vers le bas met en veille**. Et la 2.4.9 parle explicitement d'un « geste de
réveil par balayage vers le haut ».

Donc **le balayage réveille, il ne change pas `robot_mode`**. L'hypothèse
concurrente — celle que le vocabulaire « Ground » de l'écran poussait à
retenir — est écartée. Les deux fonctions restent proches dans les effets
observés, mais ce sont bien deux choses différentes.

### La refonte de l'architecture est datée et signée

La note de la 2.5.0 dit exactement ce que notre inventaire ROS montrait sans
pouvoir l'expliquer : les nœuds de comportement et d'émotion **ont été
supprimés** et fusionnés dans un nœud unique. C'est pourquoi
`robot_behavior_controller` et `emotion_manager` n'apparaissent plus dans
`ros2 node list` alors que leurs topics répondent, et pourquoi
`behavior_engine_node` existe. Le décalage avec le paquet source 2.3.6 n'est pas
un accident de packaging : c'est une refonte assumée, du 23 juillet 2026.

### La caméra WebRTC est récente

Le passage au WebRTC pour le flux vidéo web date de la **2.4.7, 2 juillet 2026**.
La documentation constructeur qui annonce la transmission d'image « non
disponible actuellement » lui est donc simplement **antérieure**. Elle n'est pas
fausse, elle est périmée — ce qui est une nuance à faire, et plus honnête.

### La détection de squelette aussi

« Détection de squelette humain » ajoutée en 2.4.7. Cela recoupe exactement les
classes que nous observons — `body`, `head`, `face`, plus les squelettes — et
renforce le doute sur le topic de gestes de la main hérité du paquet 2.3.6 : la
vision embarquée a été refaite entre-temps.

### Il existe une protection de couple dans le firmware bas niveau

Ajoutée en 2.4.6. Elle s'ajoute aux écrêtages `joint_clamp_enabled` /
`ws_clamp_enabled` relevés dans les paramètres, et vient sous notre propre
coupe-circuit logiciel à 850 ‰. Trois filets, donc, dont deux hors de notre
contrôle.

### Le protocole a changé en cours de route

« Protocole d'API mis à jour » en 2.4.5, début juin 2026. C'est probablement là
que naît le protocole en MAJUSCULES que nous avons cartographié, et l'écart avec
la documentation officielle qui décrit encore l'autre API.

---

## Une correction à porter partout

Nous avons écrit, le 26 juillet, qu'**aucun journal de version public n'existait**
pour le firmware Sirius. C'était vrai au sens strict — rien n'est indexé sur le
web, aucune page de notes de publication, aucun dépôt — mais **le journal
existe** : il est servi dans le Centre de mise à jour du robot, une page
accessible seulement à qui possède la machine et l'y connecte.

La formulation juste est donc : *le constructeur tient un journal de version
détaillé, mais uniquement à l'intérieur de l'interface de mise à jour de ses
propres robots ; il n'est publié nulle part et aucun moteur de recherche ne le
voit.* C'est même une information utile en soi pour un possesseur : il ne le
trouvera pas en cherchant, il doit aller le lire dans le Centre de mise à jour.

---

## Autres découvertes de la même console

La barre de navigation de l'interface constructeur donne la liste de ses outils,
dont plusieurs ne sont documentés nulle part et que nous n'avons jamais
explorés :

**Material Manager** · **Inner World** (le mode autonome et les émotions) ·
**System Update** (cette page) · **Node Management** (gestion des nœuds ROS,
avec journal depuis la 2.4.5) · **Gait Debug** (le joystick virtuel) ·
**Group Dance** · **Net Debug** · **Behavior Tree** · **Timeline Editor**.

Un **retour arrière** (*Rollback*) et un réglage **redémarrage automatique** sont
disponibles dans le Centre de mise à jour. Le bandeau affiche en permanence la
batterie, la température et la latence de la liaison.

`Behavior Tree` et `Timeline Editor` méritent une exploration à eux seuls : le
premier donne probablement à voir l'arbre de comportement qui a absorbé les
nœuds d'émotion en 2.5.0.
