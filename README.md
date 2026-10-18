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
Ablauf: `dev/vm-test.sh fetch`, dann `dev/vm-test.sh install 1` (Szenario 1: UEFI, SSD + HDD).

Image- und Action-Updates kommen per [Renovate](https://docs.renovatebot.com/) als Pull Request (GitHub-App muss einmal für das Repo aktiviert werden).

## Lizenz

[MIT](LICENSE)
