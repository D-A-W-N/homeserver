#!/usr/bin/env bash
# Kopiert das Repo in eine Test-VM nach /opt/aunserver und führt das Playbook dort lokal aus,
# so wie es später aunserver-setup auf dem NAS tut.
#
# Verwendung: dev/vm-ansible.sh <config.yml> [weitere ansible-playbook-Optionen]
#             SYNC_ONLY=1 dev/vm-ansible.sh   nur das Repo kopieren (z. B. um bin/aunserver-setup zu testen)
# Umgebung:   SSH_PORT (2222), VM_USER (nasadmin), VM_PASSWORD (aunserver, das Passwort aus
#             dev/preseed-dev.cfg; wird für sudo gebraucht)
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$SCRIPT_DIR/..
if [ "${SYNC_ONLY:-0}" = 1 ]; then
  CONFIG=""
else
  CONFIG=${1:?Pfad zur config.yml fehlt (Vorlage: config.example.yml)}
  shift
fi
PORT=${SSH_PORT:-2222}
TARGET=${VM_USER:-nasadmin}@localhost
PW=${VM_PASSWORD:-aunserver}
SSH_OPTS=(-p "$PORT" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR)

# shellcheck disable=SC2029  # Argumente werden bewusst lokal zusammengesetzt
vm() { ssh "${SSH_OPTS[@]}" "$TARGET" "$@"; }
# sudo mit Passwort über stdin, ohne Terminal; Argumente gequotet, weil ssh sie neu zerlegt
vm_sudo() { printf '%s\n' "$PW" | vm "sudo -S -p '' $(printf '%q ' "$@")"; }

[ -z "$CONFIG" ] || [ -f "$CONFIG" ] || { echo "Fehler: $CONFIG fehlt" >&2; exit 1; }

echo "== Voraussetzungen (ansible, rsync)"
vm_sudo sh -c 'command -v ansible-playbook >/dev/null && command -v rsync >/dev/null || DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ansible rsync >/dev/null'

echo "== Repo nach /opt/aunserver"
# erst als Benutzer kopieren (rsync braucht stdin für sein Protokoll), dann mit sudo umziehen
rsync -a --delete --exclude .git --exclude .venv --exclude .vm \
  -e "ssh ${SSH_OPTS[*]}" "$REPO/" "$TARGET:aunserver-repo/"
vm_sudo install -d -m 0755 /opt/aunserver /etc/aunserver
vm_sudo rsync -a --delete --chown=root:root "/home/${VM_USER:-nasadmin}/aunserver-repo/" /opt/aunserver/

[ "${SYNC_ONLY:-0}" = 1 ] && { echo "== nur kopiert (SYNC_ONLY)"; exit 0; }

echo "== Konfiguration nach /etc/aunserver/config.yml"
# stdin von vm_sudo ist schon durch das Passwort belegt, deshalb erst als Benutzer hochladen
vm "cat > aunserver-config.yml" < "$CONFIG"
vm_sudo install -m 0600 -o root -g root "/home/${VM_USER:-nasadmin}/aunserver-config.yml" /etc/aunserver/config.yml
vm rm -f aunserver-config.yml

echo "== Playbook"
vm_sudo sh -c "cd /opt/aunserver/ansible && ANSIBLE_FORCE_COLOR=1 ansible-playbook -i localhost, -c local site.yml -e @/etc/aunserver/config.yml $*"
