# Umsetzungsplan

Basis: [KONZEPT.md](KONZEPT.md) mit den Änderungen aus [ANALYSE.md](ANALYSE.md). Der Plan ist risikobasiert: Unbekanntes wird zuerst in der VM geklärt, bevor darauf gebaut wird.

## Entscheidungen

| # | Frage | Entscheidung | Folge |
|---|---|---|---|
| E1 | Samba-Shares | Ansible (deklarativ, `include`-Datei bei jedem Lauf gerendert) | Cockpit-Plugin `file-sharing` nur optional, `shares` in `config.yml` bleibt dauerhaft Wahrheit |
| E2 | Compose-Dateien | Ansible ist Wahrheit | Dockge nur für Start/Stop/Logs/Update, Änderungen per Variablen/Repo; Dockge optional |
| E3 | App-Configs | HDD (`/srv/data/configs`, wie im Konzept) | Gegen die Empfehlung (SSD) entschieden; Risiken siehe unten |
| E4 | Installer | Eigenes ISO | `build-iso.sh` mit Fixes aus ANALYSE 2.4 (`md5sum.txt`, SHA256, Parameter), Preseed-URL bleibt Dev-Modus |
| E5 | Sprache | Deutsch | Skriptausgaben, Doku, Kommentare deutsch |

**Zu E3 (Risiken bewusst akzeptiert):** Langsamere Random-I/O für SQLite-Datenbanken, HDD kann nicht schlafen, Plattenausfall nimmt Daten und Configs mit. Gegenmaßnahmen: restic-Backup der Configs auf ein anderes Medium (M6) wird vor die Umstellung gezogen und ist Abnahmebedingung für M8; `chattr +i` auf dem leeren Mountpoint plus `RequiresMountsFor` verhindert Schreiben auf die SSD bei fehlender HDD.

## Entwicklungsumgebung

- Entwickelt wird lokal (Manjaro), getestet in einer QEMU/KVM-VM mit Debian 13 (UEFI via OVMF, zwei virtuelle Platten, Befehle in KONZEPT 13.1).
- Lokal: Python-venv mit gepinnten `ansible-core`, `ansible-lint`, `yamllint`, dazu `shellcheck`.
- Ein Branch pro Meilenstein, Merge per Pull Request nach `main`, Tags `v0.x.0`.

## Meilensteine

### M0 – Repo-Grundlage ✅ (Teil davon bereits erledigt)
- [x] Repo `D-A-W-N/homeserver` (öffentlich), Konzept, Analyse, Plan
- [x] `LICENSE` (MIT), `.gitignore`, `README.md`
- [x] `config.example.yml`, `ansible/group_vars/all.yml`, `.yamllint`, `.ansible-lint`
- [x] CI `lint.yml` mit gepinnten Versionen, `gitleaks`
- [x] Dependabot für GitHub Actions (Compose-Images später)

**Abnahme:** CI grün auf leerem Gerüst.

### M0.5 – Spikes (Wegwerfcode in der VM, Ergebnis als Notiz in `docs/spikes.md`)
- [ ] S1: Cockpit + 45Drives-Plugins auf Debian 13 installierbar? Wenn nein: Entscheidung E1 entfällt, Plugin raus.
- [ ] S2: Preseed- und ISO-Verhalten (inkl. Bootmenü-Pfade im Debian-13-ISO): Welche Fragen erscheinen bei `priority=critical` vs. `high`? Bleibt die Partitionierungs-Bestätigung manuell? Läuft `select-disk.sh` (busybox, `blkid`, `wget`)?
- [ ] S3: `rotational`-Wert in der QEMU-VM, Verhalten mit `rotation_rate=1`.
- [ ] S4: Hotio-Images: `curl` im Container für Healthchecks vorhanden? Image-Verfügbarkeit von `ghcr.io/d-a-w-n/*`.

**Abnahme:** Jede Annahme mit [VERIFY] im Konzept ist bestätigt oder das Design angepasst.

### M1 – Ansible-Kern
- [ ] `site.yml` (UID/GID, Assert doppelter Ports)
- [ ] `base`: Pakete, Hostname, Zeitzone, zram, unattended-upgrades (+ Reboot-Entscheidung), **SSH-Schlüssel/Härtung**
- [ ] `datastructure`: Mountpoint-`assert`, `chattr +i` auf leerem Mountpoint, Ordner aus `data_dirs`, `configs/` auf der HDD (E3)
- [ ] `docker`: Repo, `daemon.json`, `RequiresMountsFor`, Admin in Gruppe `docker`
- [ ] CI-Job `idempotence` (Container, zweiter Lauf `changed=0`)

**Abnahme:** Zweiter Lauf `changed=0`. Ohne Datenplatte startet Docker nicht, SSH bleibt erreichbar (Testmatrix 7).

### M2 – Cockpit und Samba
- [ ] `cockpit` (Plugins nur optional, falls S1 positiv; `file-sharing` ist nicht tragend)
- [ ] `samba`: Shares aus `config.yml` per Include-Datei (E1), Benutzer-Passwort, optional `wsdd`
- [ ] Zugriff aus VM-Host (`smbclient`) und Windows

**Abnahme:** Share von Windows beschreibbar, Dateien gehören dem Admin-Benutzer.

### M3 – Stacks
- [ ] Vorlagen (Ansible ist Wahrheit, E2) mit festgepinnten Image-Tags, Ports ans LAN gebunden (konfigurierbar)
- [ ] Rolle `stacks` inkl. Scrutiny-Geräteliste (Test mit USB-Stick im System)
- [ ] Hardlink-Test (KONZEPT 8)

**Abnahme:** Alle Dienste erreichbar, Hardlink-Test liefert `2`, Scrutiny zeigt beide Platten.

### M4 – `homeserver-setup` (inkl. Single-Disk-Modus)
- [ ] Skript nach KONZEPT 7.2, `shellcheck`-sauber, `--dry-run`
- [ ] Single-Disk-Modus (aus M7 vorgezogen)
- [ ] Testmatrix 1, 3, 6, 8

**Abnahme:** wie im Konzept; Formatieren nie ohne Eintippen des Gerätenamens.

### M5 – Installer
- [ ] `select-disk.sh`, `preseed.cfg.in` (parametrisiert: Locale, Keymap, Zeitzone, Hostname)
- [ ] `build-iso.sh` (E4): SHA256-Prüfung des Eingabe-ISOs, `md5sum.txt` neu erzeugen, Bootmenü UEFI und BIOS; Dev-Modus per Preseed-URL für schnelle VM-Tests
- [ ] Testmatrix 1–5 (UEFI und BIOS)

**Abnahme:** Datenplatte wird in keinem Szenario angefasst.

### M6 – Backup (restic), wegen E3 vorrangig
- [ ] Rolle `backup`, Fehlerbenachrichtigung (`OnFailure=`)
- [ ] Restore-Test in der VM

**Abnahme:** Configs aus dem Repository zurückgespielt, Stacks laufen mit alten Einstellungen.

### M7 – Optional
- [ ] ISO-Build per GitHub Actions bei Tag, ISO als Release-Asset
- [ ] Rollen `firewall`, `desktop`, Monitoring/ntfy
- [ ] Renovate-PRs für Image-Updates

### M8 – Umstellung auf dem echten Server
Runbook KONZEPT 15, erst nach M6. Vorher Config-Backups des Altsystems (Sonarr/Radarr/Emby) extern sichern.

## Reihenfolge und Abhängigkeiten

```
M0 → M0.5 ─┬→ M1 → M2 → M3 → M4 ─┐
           └→ M5 (parallel ab S2) ─┴→ M6 → M8
```

## Erster nächster Schritt

M0 abschließen (Gerüst + CI), dann M0.5 S1/S2 in der VM. Danach lohnt es, die Issues aus diesem Plan anzulegen.
