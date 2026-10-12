# Umsetzungsplan

Basis: [KONZEPT.md](KONZEPT.md) mit den Änderungen aus [ANALYSE.md](ANALYSE.md). Der Plan ist risikobasiert: Unbekanntes wird zuerst in der VM geklärt, bevor darauf gebaut wird.

## Offene Entscheidungen (bitte vor M1 treffen)

| # | Frage | Empfehlung |
|---|---|---|
| E1 | Samba-Shares deklarativ (Ansible) oder Cockpit-gepflegt? | Deklarativ, Cockpit-Plugin optional |
| E2 | Compose-Dateien: Ansible oder Dockge als Wahrheit? | Ansible, Dockge für Start/Stop/Logs |
| E3 | App-Configs auf SSD oder HDD? | SSD (`/srv/appdata`), per restic gesichert |
| E4 | Installer: ISO bauen oder Boot-Parameter + Preseed-URL (GitHub-Tag)? | Zuerst Preseed-URL, ISO später |
| E5 | Sprache von Skripten/Ausgaben | Deutsch (konsistent zu Doku), Struktur i18n-fähig halten |

Der Plan unten setzt die Empfehlungen voraus. Ändert sich eine Entscheidung, betrifft das nur die genannten Meilensteine.

## Entwicklungsumgebung

- Entwickelt wird lokal (Manjaro), getestet in einer QEMU/KVM-VM mit Debian 13 (UEFI via OVMF, zwei virtuelle Platten, Befehle in KONZEPT 13.1).
- Lokal: Python-venv mit gepinnten `ansible-core`, `ansible-lint`, `yamllint`, dazu `shellcheck`.
- Ein Branch pro Meilenstein, Merge per Pull Request nach `main`, Tags `v0.x.0`.

## Meilensteine

### M0 – Repo-Grundlage ✅ (Teil davon bereits erledigt)
- [x] Repo `D-A-W-N/homeserver` (öffentlich), Konzept, Analyse, Plan
- [x] `LICENSE` (MIT), `.gitignore`, `README.md`
- [ ] `config.example.yml`, `ansible/group_vars/all.yml`, `.yamllint`, `.ansible-lint`
- [ ] CI `lint.yml` mit gepinnten Versionen, `gitleaks`
- [ ] Dependabot/Renovate für GitHub Actions und (später) Compose-Images

**Abnahme:** CI grün auf leerem Gerüst.

### M0.5 – Spikes (Wegwerfcode in der VM, Ergebnis als Notiz in `docs/spikes.md`)
- [ ] S1: Cockpit + 45Drives-Plugins auf Debian 13 installierbar? Wenn nein: Entscheidung E1 entfällt, Plugin raus.
- [ ] S2: Preseed-Verhalten: Welche Fragen erscheinen bei `priority=critical` vs. `high`? Bleibt die Partitionierungs-Bestätigung manuell? Läuft `select-disk.sh` (busybox, `blkid`, `wget`)?
- [ ] S3: `rotational`-Wert in der QEMU-VM, Verhalten mit `rotation_rate=1`.
- [ ] S4: Hotio-Images: `curl` im Container für Healthchecks vorhanden? Image-Verfügbarkeit von `ghcr.io/d-a-w-n/*`.

**Abnahme:** Jede Annahme mit [VERIFY] im Konzept ist bestätigt oder das Design angepasst.

### M1 – Ansible-Kern
- [ ] `site.yml` (UID/GID, Assert doppelter Ports)
- [ ] `base`: Pakete, Hostname, Zeitzone, zram, unattended-upgrades (+ Reboot-Entscheidung), **SSH-Schlüssel/Härtung**
- [ ] `datastructure`: Mountpoint-`assert`, `chattr +i` auf leerem Mountpoint, Ordner aus `data_dirs`, `appdata` (E3)
- [ ] `docker`: Repo, `daemon.json`, `RequiresMountsFor`, Admin in Gruppe `docker`
- [ ] CI-Job `idempotence` (Container, zweiter Lauf `changed=0`)

**Abnahme:** Zweiter Lauf `changed=0`. Ohne Datenplatte startet Docker nicht, SSH bleibt erreichbar (Testmatrix 7).

### M2 – Cockpit und Samba
- [ ] `cockpit` (+ Plugins, falls S1 positiv)
- [ ] `samba`: deklarative Shares per Include, Benutzer-Passwort, optional `wsdd`
- [ ] Zugriff aus VM-Host (`smbclient`) und Windows

**Abnahme:** Share von Windows beschreibbar, Dateien gehören dem Admin-Benutzer.

### M3 – Stacks
- [ ] Vorlagen mit festgepinnten Image-Tags, Ports ans LAN gebunden (konfigurierbar)
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
- [ ] Boot per Preseed-URL (GitHub-Tag), Dev-Modus für VM
- [ ] Testmatrix 1–5 (UEFI und BIOS)

**Abnahme:** Datenplatte wird in keinem Szenario angefasst.

### M6 – Backup (restic)
- [ ] Rolle `backup`, Fehlerbenachrichtigung (`OnFailure=`)
- [ ] Restore-Test in der VM

**Abnahme:** Configs aus dem Repository zurückgespielt, Stacks laufen mit alten Einstellungen.

### M7 – Optional
- [ ] ISO-Build per GitHub Actions bei Tag (inkl. `md5sum.txt`, SHA256-Prüfung)
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
