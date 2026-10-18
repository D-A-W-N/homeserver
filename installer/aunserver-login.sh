# shellcheck shell=sh
# /etc/profile.d/aunserver.sh – Hinweis beim Login, solange das NAS nicht eingerichtet ist.
# Vom Installer abgelegt (installer/build-iso.sh).
if [ ! -f /etc/aunserver/config.yml ] && [ -x /opt/aunserver/bin/aunserver-setup ]; then
  printf '\n  aunserver ist installiert, aber noch nicht eingerichtet.\n'
  printf '  Einrichten mit:  sudo /opt/aunserver/bin/aunserver-setup\n\n'
fi
