# shellcheck shell=sh
# /etc/profile.d/aunserver.sh – Hinweis beim Login, solange das NAS nicht eingerichtet ist.
# Vom Installer abgelegt (installer/build-iso.sh).
if [ ! -f /etc/aunserver/config.yml ] && [ -x /opt/aunserver/bin/aunserver-setup ]; then
  printf '\n  aunserver ist installiert, aber noch nicht eingerichtet.\n'
  ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}')
  printf '  Einrichten im Browser:  https://%s:9090  → anmelden → aunserver\n' "${ip:-<IP>}"
  printf '  oder hier mit:          sudo /opt/aunserver/bin/aunserver-setup\n\n'
  unset ip
fi
