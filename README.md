# aunserver

Ein USB-Stick, der jederzeit ein fertiges NAS installiert: Debian 13, Docker mit Verwaltung und Überwachung, Samba-Freigaben per Weboberfläche, Servarr-Medienstack (Usenet) mit Emby, Netzwerk-Apps (Caddy, AdGuard Home, Tailscale, Homepage), tägliches Backup der Einstellungen (restic) und Updates per Befehl.

> **Status:** Läuft auf dem echten NAS (seit 2026-10-19, `v0.9.0` + Updates). Alle Meilensteine M0–M9 umgesetzt, in VMs und CI getestet; offen ist nur der Test mit der PS2 (OPL).

## USB-Stick erstellen

Fertige ISOs hängen an jedem [Release](../../releases) (mit SHA256-Prüfsumme). Selbst bauen:

```bash
dev/vm-test.sh fetch          # aktuelles Debian-13-netinst-ISO laden und prüfen
installer/build-iso.sh        # erzeugt aunserver-<version>.iso (ohne xorriso: automatisch per Docker)
sudo dd if=aunserver-<version>.iso of=/dev/sdX bs=4M status=progress conv=fsync
```

Unter Windows mit Rufus im **DD-Modus** schreiben; Ventoy ist nicht getestet. Vom Stick booten (UEFI oder BIOS) und „aunserver installieren“ wählen. Gefragt werden nur Benutzername und Passwort; die Systemplatte wird erkannt und mit Modell, Größe und Seriennummer zur Bestätigung angezeigt, vor dem Partitionieren kommt immer noch eine Rückfrage. Platten mit Label `AUNDATA` und USB-Geräte werden nie angeboten.

## Einrichtung nach der Installation

Nach der Installation vom USB-Stick per SSH (oder am Gerät) anmelden und ausführen:

```bash
sudo /opt/aunserver/bin/aunserver-setup
```

Nach einer Neuinstallation mit vorhandenem Backup: `sudo /opt/aunserver/bin/aunserver-setup --restore` (fragt zusätzlich Backup-Ziel und -Passwort).

Das Skript fragt Datenplatte, Hostname, SSH-Schlüssel, Apps und Passwörter ab, formatiert die Datenplatte erst nach Eintippen ihres Gerätenamens und einer letzten Zusammenfassung und richtet dann alles ein (beim ersten Mal 10–20 Minuten). Am Ende zeigt es alle Zugänge (später: `sudo cat /etc/aunserver/zugaenge.txt`).

Es ist jederzeit erneut ausführbar: Eine vorhandene Konfiguration (`/etc/aunserver/config.yml`) und Datenplatte (Label `AUNDATA`) werden weiterverwendet. Änderungen also in der `config.yml` vornehmen und das Skript erneut starten (nach der ersten Einrichtung kurz `sudo aunserver-setup`). Alle Einstellungen mit Standardwert stehen in [docs/KONFIGURATION.md](docs/KONFIGURATION.md) (erzeugt aus `config/schema.yml`), prüfen mit `sudo aunserver-config validate`. Alle Antworten gehen auch als Parameter (`--help`).

Updates: Debian und Docker aktualisieren sich selbst; neue Stände von aunserver und den Apps meldet das NAS per ntfy, installiert wird mit `sudo aunserver-update`.

## Dokumentation

- [Betrieb](docs/BETRIEB.md): Zugänge, DNS ohne Router-Einstellung, Apps verbinden, Updates, Backup und Wiederherstellung, Fehlersuche
- [Projektplan](docs/PLAN.md): Ziele, Entscheidungen, Architektur, Meilensteine mit Abnahme und Befunden
- [Spikes](docs/spikes.md): Ergebnisse der Vorab-Tests (M1)

## Entwicklung

```bash
uv venv --python 3.13 .venv && . .venv/bin/activate   # uv lädt Python 3.13, falls es fehlt
uv pip install -r requirements-dev.txt                 # auch nach Änderungen an requirements-dev.txt
yamllint . && (cd ansible && ansible-lint)
shellcheck bin/* dev/*.sh installer/*.sh
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

Die CI fährt denselben Ablauf in einer KVM-VM (`.github/workflows/vm-test.yml`, UEFI und BIOS): Dev-ISO bauen, davon installieren, Setup zweimal ausführen (der zweite Lauf muss `changed=0` melden), Backup und Wiederherstellung prüfen. Die VM startet nur, wenn ein PR `ansible/`, `installer/`, `dev/`, `stacks/`, `bin/`, `lib/` oder `config/` ändert; der Job `vm-test` fasst das Ergebnis zusammen und ist Pflicht-Check im Ruleset von `main`.

Image- und Action-Updates kommen per [Renovate](https://docs.renovatebot.com/) als Pull Request.

## Lizenz

[MIT](LICENSE)
