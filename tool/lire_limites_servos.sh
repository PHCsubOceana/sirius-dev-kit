#!/bin/bash
# ============================================================================
# lire_limites_servos.sh — Relève les butées articulaires des 14 servos Sirius
# ============================================================================
# LECTURE PURE : ce script n'écrit aucun registre et ne fait rien bouger.
#
# À exécuter DEPUIS TON PC. Il se connecte au robot en SSH et interroge le
# service ROS 2 /scs_config/read_register (sirius_msg/srv/ReadScsRegister).
#
#   bash lire_limites_servos.sh <IP_DU_ROBOT>
#   bash lire_limites_servos.sh 192.168.1.42 # autre IP
#
# Mot de passe root : voir l'outil OTA officiel du constructeur (manual_ota_deploy.py).
#                     Il n'est pas reproduit ici.
# ============================================================================

IP="${1:?usage : bash lire_limites_servos.sh <IP_DU_ROBOT>}"
echo "Lecture des butées servo sur $IP (aucune écriture, aucun mouvement)…"

ssh -o StrictHostKeyChecking=no root@"$IP" 'bash -s' <<'REMOTE'
source /opt/ros/humble/setup.bash 2>/dev/null
source /root/sirius_ros2/install/setup.bash 2>/dev/null

python3 - <<'PYEOF'
import rclpy
from rclpy.node import Node
from sirius_msg.srv import ReadScsRegister

# Cartographie mémoire des servos SCS/STS (Feetech)
ADDR_MIN_ANGLE = 9    # 9-10 : butée basse   (2 octets)
ADDR_MAX_ANGLE = 11   # 11-12 : butée haute  (2 octets)
ADDR_POSITION  = 56   # 56-57 : position actuelle (2 octets)
N_MOTORS = 14

def u16(vals, i=0, little=True):
    if len(vals) < i + 2:
        return None
    a, b = vals[i], vals[i+1]
    return (a | (b << 8)) if little else ((a << 8) | b)

class Reader(Node):
    def __init__(self):
        super().__init__('lecture_limites_servos')
        self.cli = self.create_client(ReadScsRegister, '/scs_config/read_register')
        if not self.cli.wait_for_service(timeout_sec=10.0):
            raise SystemExit("✗ Service /scs_config/read_register introuvable. "
                             "Les nœuds ROS 2 tournent-ils ? (systemctl status ros2_launch.service)")

    def read(self, motor_id, addr, length):
        req = ReadScsRegister.Request()
        req.motor_id = motor_id
        req.register_address = addr
        req.length = length
        fut = self.cli.call_async(req)
        rclpy.spin_until_future_complete(self, fut, timeout_sec=5.0)
        r = fut.result()
        if r is None or not r.success:
            return None
        return list(r.values)

rclpy.init()
try:
    n = Reader()
    print()
    print("  ID | butée basse | butée haute |  amplitude | position | état")
    print("  ---+-------------+-------------+------------+----------+---------------")
    lignes = []
    for m in range(N_MOTORS):
        lo = n.read(m, ADDR_MIN_ANGLE, 2)
        hi = n.read(m, ADDR_MAX_ANGLE, 2)
        po = n.read(m, ADDR_POSITION, 2)
        vlo, vhi, vpo = u16(lo or []), u16(hi or []), u16(po or [])
        if vlo is None or vhi is None:
            print(f"  {m:2d} |      —      |      —      |     —      |    —     | lecture échouée")
            continue
        span = vhi - vlo
        # 0-4095 sur un tour complet pour les STS ; 0-1023 pour les SCS classiques
        ech = 4095 if max(vlo, vhi) > 1023 else 1023
        deg = span * 360.0 / (ech + 1)
        etat = ""
        if vpo is not None:
            marge = min(vpo - vlo, vhi - vpo)
            if marge < 0:
                etat = "⚠ HORS BUTÉES"
            elif span > 0 and marge < span * 0.05:
                etat = "⚠ proche butée"
            else:
                etat = "ok"
        print(f"  {m:2d} | {vlo:11d} | {vhi:11d} | {span:5d} ({deg:5.1f}°) | "
              f"{(vpo if vpo is not None else -1):8d} | {etat}")
        lignes.append((m, vlo, vhi, vpo))
    print()
    print("  Échelle : 0-4095 = 360° (servos STS) ou 0-1023 = 300° (SCS classiques).")
    print("  Ces butées sont les limites MATÉRIELLES : toute consigne au-delà fait")
    print("  forcer le servo. À reporter dans Sirius Studio avant d'activer l'envoi")
    print("  de poses en UDP (Play_Keyframe).")
    print()
finally:
    try:
        rclpy.shutdown()
    except Exception:
        pass
PYEOF
REMOTE
