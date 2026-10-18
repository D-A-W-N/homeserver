# aunserver

Ein USB-Stick, der jederzeit ein fertiges NAS installiert: Debian 13, Docker mit Verwaltung und Überwachung, Samba-Freigaben per Weboberfläche, Servarr-Medienstack (Usenet) mit Emby sowie Netzwerk-Apps (Caddy, AdGuard Home, Tailscale, Homepage).

> **Status:** M0 (Grundgerüst). Noch nichts lauffähig.

## Dokumentation

- [Projektplan](docs/PLAN.md): Ziele, Entscheidungen, Architektur, Meilensteine

## Entwicklung

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
yamllint . && (cd ansible && ansible-lint)
shellcheck dev/*.sh
```

VM-Tests mit QEMU (Testmatrix aus dem Plan, Abschnitt 10): `dev/vm-test.sh --help`.

```bash
dev/vm-test.sh fetch                 # aktuelles Debian-netinst-ISO laden und prüfen
dev/vm-test.sh autoinstall 1         # Szenario 1 (UEFI, SSD + HDD) vollautomatisch installieren
dev/vm-test.sh boot 1 &              # installiertes System starten (SSH: localhost:2222)
cp config.example.yml /tmp/test.yml  # anpassen, z. B. eigenen SSH-Schlüssel eintragen
dev/vm-ansible.sh /tmp/test.yml      # Repo in die VM kopieren und das Playbook dort ausführen
```

`autoinstall` nutzt den echten Preseed aus `installer/` plus `dev/preseed-dev.cfg` (Benutzer `nasadmin`, Passwort `aunserver`, eigener SSH-Schlüssel, keine Rückfragen). Für manuelle Installationen gibt es weiterhin `install`.

Die CI fährt denselben Ablauf in einer KVM-VM (`.github/workflows/vm-test.yml`): installieren, Playbook zweimal ausführen, der zweite Lauf muss `changed=0` melden.

Image- und Action-Updates kommen per [Renovate](https://docs.renovatebot.com/) als Pull Request (GitHub-App muss einmal für das Repo aktiviert werden).

## Lizenz

[MIT](LICENSE)
