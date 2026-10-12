# homeserver

Schlankes, reproduzierbares Heimserver-System auf Debian 13: Docker-Container, Samba-Freigaben und Cockpit als Verwaltung, komplett per Ansible aufgesetzt. Gedacht als schlanker Ersatz für OpenMediaVault.

> **Status:** Planungsphase, noch nichts lauffähig.

## Dokumentation

- [Konzept](docs/KONZEPT.md): Ziele, Architektur, Entscheidungen
- [Analyse](docs/ANALYSE.md): Schwächen und Verbesserungsvorschläge zum Konzept
- [Umsetzungsplan](docs/PLAN.md): Meilensteine und offene Entscheidungen

## Lizenz

[MIT](LICENSE)

## Entwicklung und Tests

VM-Tests mit QEMU (Testmatrix aus dem Konzept): `dev/vm-test.sh --help`.
Ablauf: `dev/vm-test.sh fetch`, dann `dev/vm-test.sh install 1` (Szenario 1: UEFI, SSD + HDD).
