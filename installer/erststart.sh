#!/bin/sh
# Läuft im Installer (late_command, in-target) im neuen System: Cockpit mit der aunserver-Seite,
# damit die Ersteinrichtung auch im Browser geht (D24, https://<IP>:9090 → aunserver).
# Cockpit aus den Backports wie später im Setup (D2); die Paketquellen schreibt das Setup ohnehin
# neu (debian.sources), die Zeile hier entfernt es mit der alten sources.list.
#   erststart.sh <admin-benutzer> [<github-name>]   (Werte aus dem Installer, fragen.sh)
set -e
benutzer=${1:-}
github=${2:-}

# SSH-Schlüssel von GitHub für den Admin (aunserver-setup übernimmt authorized_keys)
if [ -n "$github" ] && [ -n "$benutzer" ]; then
  if schluessel=$(curl -fsS --max-time 20 "https://github.com/$github.keys") && [ -n "$schluessel" ]; then
    install -d -m 0700 -o "$benutzer" -g "$benutzer" "/home/$benutzer/.ssh"
    printf '%s\n' "$schluessel" >> "/home/$benutzer/.ssh/authorized_keys"
    chown "$benutzer:$benutzer" "/home/$benutzer/.ssh/authorized_keys"
    chmod 0600 "/home/$benutzer/.ssh/authorized_keys"
  else
    echo "Keine SSH-Schlüssel von github.com/$github.keys" >&2
  fi
fi

# Die Quelle vom Installationsmedium (deb cdrom:) ist danach nicht mehr da, apt-get update
# bräche an ihr ab ("enthält keine Release-Datei", im M10-Test gefunden)
sed -i 's/^deb cdrom:/# deb cdrom:/' /etc/apt/sources.list 2>/dev/null || true
grep -q trixie-backports /etc/apt/sources.list 2>/dev/null \
  || echo "deb http://deb.debian.org/debian trixie-backports main" >> /etc/apt/sources.list
apt-get update -qq
# python3-yaml und python3-ruamel.yaml: aunserver-config läuft schon vor dem ersten Setup
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq -t trixie-backports --no-install-recommends \
  cockpit-ws cockpit-system cockpit-bridge python3-yaml python3-ruamel.yaml >/dev/null
cp -r /opt/aunserver/cockpit/aunserver /usr/share/cockpit/
chmod -R go-w /usr/share/cockpit/aunserver
systemctl enable cockpit.socket >/dev/null 2>&1 || true
rm -f "$0"
