#!/bin/sh
# Läuft im Installer (late_command, in-target) im neuen System: Cockpit mit der aunserver-Seite,
# damit die Ersteinrichtung auch im Browser geht (D24, https://<IP>:9090 → aunserver).
# Cockpit aus den Backports wie später im Setup (D2); die Paketquellen schreibt das Setup ohnehin
# neu (debian.sources), die Zeile hier entfernt es mit der alten sources.list.
set -e
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
