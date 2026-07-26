# Avant tout commit

Ce dépôt est public. Le projet dont il est extrait ne l'est pas : il contient le
mot de passe root du robot, l'adresse IP de la machine de développement et son
SSID.

**Contrôle à passer avant chaque commit, sans exception :**

```bash
git diff --cached | grep -nE "192\.168\.[0-9]+\.[0-9]+|root@|password|mot de passe"
```

Trois règles.

**Le mot de passe root SSH du Sirius ne doit jamais figurer ici.** Il est très
probablement identique sur toutes les unités sorties d'usine : le publier
donnerait à n'importe qui l'accès root aux robots des autres, sur leur réseau
local. Il se trouve dans l'outil de déploiement OTA officiel du constructeur,
`manual_ota_deploy.py`, et c'est là qu'il doit rester. Changez-le avec `passwd`
en gardant à l'esprit que l'outil OTA officiel s'attend à la valeur d'origine.

**Aucune adresse IP réelle, aucun SSID.** `<IP_DU_ROBOT>` partout, y compris dans
les copies d'écran.

**Aucun code de navigation autonome tant que sa sécurité n'a pas été éprouvée.**
La détection de vide décrite dans la documentation n'a jamais été testée au bord
d'une vraie table. Publier un nœud de déambulation dont la seule protection
contre les chutes n'a pas été confrontée à la réalité ferait tomber le robot de
quelqu'un d'autre.
