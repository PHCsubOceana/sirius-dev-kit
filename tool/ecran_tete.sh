#!/usr/bin/env bash
# ============================================================
#  ecran_tete.sh — comprendre (et rejouer) le swipe de l'écran
#
#  À copier SUR LE ROBOT puis à exécuter en SSH :
#      scp ecran_tete.sh root@<IP>:/root/
#      ssh root@<IP> "bash /root/ecran_tete.sh decouvrir"
#
#  Le but : l'écran de la tête est piloté par le nœud `lvgl_gui_node`
#  (paquet `lvgl_ros2_gui`). Un swipe vertical y bascule un réglage.
#  Ce script identifie PAR QUEL canal ROS ce swipe transite, puis
#  permet de le rejouer à distance.
#
#  Trois sous-commandes :
#      decouvrir  — inventaire des topics / services / messages
#      ecouter    — enregistre ce qui passe pendant que tu swipes
#      rejouer    — republie le message capturé
# ============================================================
# Pas de « set -u » : les setup.bash de ROS référencent des variables non
# définies, ce qui ferait sortir bash immédiatement et en silence.
set -o pipefail

echo "Sirius — inventaire, $(date -Iseconds)"
for env in /opt/ros/humble/setup.bash /root/sirius_ros2/install/setup.bash; do
  if [ -r "$env" ]; then
    # shellcheck disable=SC1090
    . "$env" && echo "  ok  $env" || echo "  ÉCHEC  $env"
  else
    echo "  absent  $env"
  fi
done
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
[ -f /root/cyclonedds.xml ] && export CYCLONEDDS_URI=file:///root/cyclonedds.xml

CAPTURE=/root/swipe_capture.txt
titre() { printf '\n\033[36m── %s\033[0m\n' "$1"; }

decouvrir() {
  titre "Nœuds liés à l'écran"
  ros2 node list 2>/dev/null | grep -iE 'lvgl|gui|screen|display|touch' || echo "(aucun)"

  titre "Topics candidats"
  ros2 topic list -t 2>/dev/null | grep -iE 'lvgl|touch|gui|screen|gesture|swipe|mode|posture' || echo "(aucun)"

  titre "Services candidats"
  ros2 service list -t 2>/dev/null | grep -iE 'lvgl|touch|gui|screen|mode|posture|stand' || echo "(aucun)"

  titre "Types de messages du paquet lvgl_ros2_gui"
  ros2 interface package lvgl_ros2_gui 2>/dev/null || echo "(paquet non exposé)"

  titre "Définition de TouchState (si présent)"
  ros2 interface show lvgl_ros2_gui/msg/TouchState 2>/dev/null || echo "(type absent)"

  titre "Paramètres de lvgl_gui_node"
  ros2 param list /lvgl_gui_node 2>/dev/null || echo "(nœud introuvable sous ce nom)"

  titre "Ce que voit le nœud (publications / abonnements)"
  ros2 node info /lvgl_gui_node 2>/dev/null || echo "(nœud introuvable sous ce nom)"

  titre "Mode robot courant (source de vérité côté moteurs)"
  ros2 param get /sirius_motion_control_node robot_mode 2>/dev/null \
    || ros2 param dump /sirius_motion_control_node 2>/dev/null | grep -iE 'mode|ground|desktop' \
    || echo "(indisponible)"

  cat <<'FIN'

── Lecture des résultats
  • Un topic de type TouchState → le swipe est rejouable (voir « ecouter »).
  • Aucun topic tactile, mais un service de mode → le swipe n'est qu'un
    raccourci vers ce service : on l'appelle directement.
  • Rien des deux → le tactile est traité dans le process LVGL, sans passer
    par ROS. Reste alors la voie WebSocket USER_SET_ROBOT_MODE.
FIN
}

ecouter() {
  local topic="${1-}"
  if [ -z "$topic" ]; then
    topic=$(ros2 topic list 2>/dev/null | grep -iE 'touch|gesture|swipe' | head -1)
  fi
  if [ -z "$topic" ]; then
    echo "Aucun topic tactile trouvé. Lance d'abord : bash $0 decouvrir" >&2
    exit 1
  fi
  echo "Écoute de $topic pendant 20 s."
  echo ">>> FAIS LE SWIPE VERTICAL SUR L'ÉCRAN MAINTENANT <<<"
  timeout 20 ros2 topic echo "$topic" | tee "$CAPTURE"
  echo
  echo "Capture enregistrée dans $CAPTURE"
  echo "$topic" > "${CAPTURE}.topic"
}

rejouer() {
  local topic type
  topic=$(cat "${CAPTURE}.topic" 2>/dev/null || true)
  if [ -z "$topic" ]; then
    echo "Rien à rejouer : lance d'abord « ecouter »." >&2; exit 1
  fi
  type=$(ros2 topic info "$topic" 2>/dev/null | awk -F': ' '/Type/{print $2}')
  echo "Topic : $topic  (type $type)"
  echo "Contenu capturé :"; sed -n '1,20p' "$CAPTURE"
  cat <<FIN

Pour rejouer, adapte le YAML ci-dessus dans cette commande :

  ros2 topic pub --once $topic $type '{ … }'

(le « --once » suffit ; l'écran réagit au message, pas à sa répétition)
FIN
}

case "${1:-decouvrir}" in
  decouvrir) decouvrir ;;
  ecouter)   ecouter "${2-}" ;;
  rejouer)   rejouer ;;
  *) echo "usage: $0 {decouvrir|ecouter [topic]|rejouer}" >&2; exit 2 ;;
esac
