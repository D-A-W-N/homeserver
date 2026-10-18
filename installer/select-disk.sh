#!/bin/sh
# Wählt im Debian-Installer die Systemplatte (läuft als partman/early_command, busybox sh).
#
# Kandidaten: keine USB-/Wechselmedien, keine Platte mit Label AUNDATA.
# Genau eine SSD/NVMe -> Rückfrage mit Modell, Größe und Seriennummer, bei "Ja" wird sie gesetzt.
# Mehrere oder keine SSD, oder "Nein" -> der Installer fragt selbst (zeigt Größe und Modell).
# Die Bestätigung vor dem Schreiben der Partitionstabelle bleibt in jedem Fall manuell.
#
# Getestet in Spike S2 (docs/spikes.md). Gerätenamen sind im Installer nicht stabil,
# deshalb werden Platten nur über Merkmale erkannt.

LOG=/var/log/select-disk.log
log() { echo "select-disk: $*" >>"$LOG"; }

# "Modell, Größe, Seriennummer" einer Platte
info() {
  m=$(sed 's/ *$//' "/sys/block/$1/device/model" 2>/dev/null)
  s=$(cat "/sys/block/$1/device/serial" 2>/dev/null)
  # SATA-Platten haben kein serial-Attribut, die Seriennummer ist das letzte Wort der wwid
  [ -n "$s" ] || s=$(sed 's/ *$//; s/.* //' "/sys/block/$1/device/wwid" 2>/dev/null)
  echo "/dev/$1: ${m:-unbekannt}, $(( $(cat "/sys/block/$1/size") / 2097152 )) GB, Seriennummer ${s:-unbekannt}"
}

ssd="" hdd=""
for d in /sys/block/*; do
  n=${d##*/}
  case "$n" in loop*|ram*|sr*|zram*|md*|dm-*|fd*|nbd*) continue ;; esac
  [ "$(cat "$d/removable" 2>/dev/null)" = 1 ] && { log "$n: Wechselmedium"; continue; }
  case "$(readlink -f "$d")" in *usb*) log "$n: USB"; continue ;; esac
  if command -v blkid >/dev/null 2>&1 && blkid 2>/dev/null | grep "^/dev/$n" | grep -q 'LABEL="AUNDATA"'; then
    log "$n: Datenplatte (AUNDATA)"; continue
  fi
  if [ "$(cat "$d/queue/rotational" 2>/dev/null)" = 0 ]; then ssd="$ssd $n"; else hdd="$hdd $n"; fi
  log "$n: rotational=$(cat "$d/queue/rotational" 2>/dev/null) $(info "$n")"
done

# shellcheck disable=SC2086  # Wortzerlegung gewollt
set -- $ssd
if [ "$#" -ne 1 ]; then
  log "keine eindeutige SSD (ssd:$ssd hdd:$hdd), Installer fragt"
  exit 0
fi
pick=$1

# AUN_YES=1 (nur dev/vm-test.sh autoinstall): ohne Rückfrage übernehmen
if [ "${AUN_YES:-}" = 1 ]; then
  log "gewählt (AUN_YES): /dev/$pick"
  debconf-set partman-auto/disk "/dev/$pick"
  debconf-set grub-installer/bootdev "/dev/$pick"
  exit 0
fi

# shellcheck disable=SC1091  # nur im Installer vorhanden
. /usr/share/debconf/confmodule
cat >/tmp/aunserver.templates <<'TPL'
Template: aunserver/confirm-disk
Type: boolean
Default: true
Description: Systemplatte bestätigen
 Debian wird auf dieser Platte installiert. Alle Daten darauf werden gelöscht:
 .
 ${DISK}
 .
 Andere Platten werden nicht verändert. Bei "Nein" können Sie die Platte selbst wählen.
TPL
debconf-loadtemplate aunserver /tmp/aunserver.templates
db_subst aunserver/confirm-disk DISK "$(info "$pick")"
db_fset aunserver/confirm-disk seen false
db_input critical aunserver/confirm-disk || true
db_go || true
db_get aunserver/confirm-disk
if [ "$RET" = true ]; then
  log "gewählt und bestätigt: /dev/$pick"
  db_set partman-auto/disk "/dev/$pick"
  db_set grub-installer/bootdev "/dev/$pick"
else
  log "Benutzer hat /dev/$pick abgelehnt, Installer fragt"
fi
