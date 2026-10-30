#!/bin/sh
# Eigene Fragen des Installers (preseed/early_command, busybox sh), vor der Netzkonfiguration (D24).
# Mit priority=critical zeigt der Installer seine eigenen Fragen zu Hostname und fester Adresse
# nicht an; deshalb fragen wir selbst (critical) und belegen netcfg damit vor:
#   aunserver/hostname    Name des NAS (netcfg/hostname, gilt auch, wenn DHCP einen Namen liefert)
#   aunserver/netz        DHCP oder feste Adresse; fest: aunserver/ip (mit /Präfix), gateway, dns
#   aunserver/ssh-github  GitHub-Benutzer, dessen öffentliche Schlüssel (github.com/<name>.keys)
#                         installer/erststart.sh als SSH-Schlüssel einträgt
# AUN_YES=1 (nur dev/vm-test.sh): nichts fragen, Name nas, DHCP, kein Schlüssel.

LOG=/var/log/aunserver-fragen.log
log() { echo "fragen: $*" >>"$LOG"; }

if [ "${AUN_YES:-}" = 1 ]; then
  log "AUN_YES: nas, DHCP, kein Schlüssel"
  exit 0
fi

# shellcheck disable=SC1091  # nur im Installer vorhanden
. /usr/share/debconf/confmodule
cat >/tmp/aunserver-fragen.templates <<'TPL'
Template: aunserver/hostname
Type: string
Default: nas
Description: Name des NAS
 Unter diesem Namen erscheint das NAS im Netz; die Apps liegen später unter
 <app>.<name>.home.arpa. Kleinbuchstaben, Ziffern und Bindestrich.

Template: aunserver/netz
Type: select
Choices: DHCP (empfohlen), Feste Adresse
Default: DHCP (empfohlen)
Description: Netzwerk des NAS
 Mit DHCP bekommt das NAS seine Adresse vom Router. Dort sollte sie fest
 zugewiesen werden (DHCP-Reservierung), denn die Namen der Apps zeigen auf sie.

Template: aunserver/ip
Type: string
Default:
Description: Feste IP-Adresse mit Präfix
 Zum Beispiel 192.168.1.20/24 (/24 = Netzmaske 255.255.255.0). Die Adresse
 darf nicht im DHCP-Bereich des Routers liegen.

Template: aunserver/gateway
Type: string
Default:
Description: Gateway (Router)
 Zum Beispiel 192.168.1.1.

Template: aunserver/dns
Type: string
Default:
Description: DNS-Server
 Meist der Router, z. B. 192.168.1.1; mehrere durch Leerzeichen getrennt.

Template: aunserver/ssh-github
Type: string
Default:
Description: SSH-Schlüssel von GitHub (optional)
 GitHub-Benutzername, dessen öffentliche SSH-Schlüssel (github.com/<name>.keys)
 der Admin-Benutzer bekommt. Mit Schlüssel schaltet die Einrichtung den
 Passwort-Login per SSH ab. Leer lassen geht auch, Schlüssel lassen sich bei der
 Einrichtung eintragen.
TPL
debconf-loadtemplate aunserver /tmp/aunserver-fragen.templates

frage() { # frage NAME: stellen und Antwort in $RET
  db_fset "aunserver/$1" seen false
  db_input critical "aunserver/$1" || true
  db_go || true
  db_get "aunserver/$1"
}

ip_ok() { # IPv4-Adresse ohne Präfix
  case "$1" in *[!0-9.]* | *..* | .* | *. | "") return 1 ;; esac
  # shellcheck disable=SC2086  # Zerlegen an den Punkten gewollt
  (IFS=.; set -- $1; [ $# -eq 4 ] || exit 1; for o; do [ "$o" -le 255 ] 2>/dev/null || exit 1; done)
}

maske() { # Präfix -> Netzmaske, z. B. 24 -> 255.255.255.0
  p=$1 m=""
  for _ in 1 2 3 4; do
    if [ "$p" -ge 8 ]; then o=255; p=$((p - 8)); else o=$((256 - (1 << (8 - p)))); p=0; fi
    m="$m${m:+.}$o"
  done
  echo "$m"
}

while :; do
  frage hostname
  case "$RET" in
    [a-z]*) case "$RET" in *[!a-z0-9-]*) ;; *) break ;; esac ;;
  esac
  db_set aunserver/hostname nas
done
db_set netcfg/hostname "$RET"
db_set netcfg/get_hostname "$RET"
db_fset netcfg/get_hostname seen true
log "Name: $RET"

frage netz
if [ "$RET" = "Feste Adresse" ]; then
  while :; do
    frage ip
    adresse=${RET%/*} praefix=${RET#*/}
    [ "$adresse" != "$RET" ] && ip_ok "$adresse" && [ "$praefix" -ge 1 ] 2>/dev/null && [ "$praefix" -le 30 ] && break
  done
  while :; do frage gateway; ip_ok "$RET" && break; done
  gateway=$RET
  while :; do
    frage dns
    ok=1
    for d in $RET; do ip_ok "$d" || ok=0; done
    [ -n "$RET" ] && [ "$ok" = 1 ] && break
  done
  db_set netcfg/disable_autoconfig true
  db_set netcfg/get_ipaddress "$adresse"
  db_set netcfg/get_netmask "$(maske "$praefix")"
  db_set netcfg/get_gateway "$gateway"
  db_set netcfg/get_nameservers "$RET"
  db_set netcfg/confirm_static true
  for q in get_ipaddress get_netmask get_gateway get_nameservers confirm_static; do db_fset "netcfg/$q" seen true; done
  log "Netz: fest $adresse/$praefix, Gateway $gateway, DNS $RET"
else
  log "Netz: DHCP"
fi

while :; do
  frage ssh-github
  case "$RET" in
    "") break ;;
    *[!A-Za-z0-9-]*) db_set aunserver/ssh-github "" ;;
    *) log "SSH-Schlüssel von GitHub: $RET"; break ;;
  esac
done
