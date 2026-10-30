#!/usr/bin/env bash
# aunserver-erststart.service (persönliches ISO, D24): aunserver-setup --yes mit der Konfiguration
# vom ISO. Datenplatte über die Seriennummer aus erststart.env (Gerätenamen sind beim Booten nicht
# stabil); eine Platte mit Label AUNDATA wird nur eingehängt.
set -euo pipefail
# shellcheck source=/dev/null
. /etc/aunserver/erststart.env   # DATENPLATTE, RESTORE, ADMIN

args=(--yes)
if [ -z "$(blkid -t LABEL=AUNDATA -o device 2>/dev/null || true)" ] && [ -n "${DATENPLATTE:-}" ]; then
  platte=$(lsblk -dn -o NAME,SERIAL | awk -v s="$DATENPLATTE" '$2 == s {print $1}')
  [ -n "$platte" ] || { echo "Keine Platte mit Seriennummer $DATENPLATTE gefunden, nichts formatiert." >&2; exit 1; }
  echo "== Datenplatte: /dev/$platte (Seriennummer $DATENPLATTE)"
  args+=(--data-disk "$platte" --format --confirm-disk "$platte")
fi
[ "${RESTORE:-0}" = 1 ] && args+=(--restore)

SUDO_USER=$ADMIN /opt/aunserver/bin/aunserver-setup "${args[@]}"
rm -f /etc/aunserver/erststart.env
systemctl disable aunserver-erststart.service
