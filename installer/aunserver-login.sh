# shellcheck shell=sh
# /etc/profile.d/aunserver.sh – Hinweis beim Login, solange das NAS nicht eingerichtet ist.
# Vom Installer abgelegt (installer/build-iso.sh).
# /etc/aunserver ist nur für root lesbar: am Zustand der Unit erkennen (sie schaltet sich nach Erfolg ab)
if systemctl is-enabled --quiet aunserver-erststart.service 2>/dev/null; then
  printf '\n  aunserver richtet sich gerade selbst ein (persönliches ISO, 10–20 Minuten).\n'
  printf '  Fortschritt:  journalctl -fu aunserver-erststart   (oder im Browser: Cockpit → aunserver)\n\n'
elif [ ! -f /etc/aunserver/config.yml ] && [ -x /opt/aunserver/bin/aunserver-setup ]; then
  printf '\n  aunserver ist installiert, aber noch nicht eingerichtet.\n'
  ip=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="src") print $(i+1)}')
  printf '  Einrichten im Browser:  https://%s:9090  → anmelden → aunserver\n' "${ip:-<IP>}"
  printf '  oder hier mit:          sudo /opt/aunserver/bin/aunserver-setup\n\n'
  unset ip
fi
