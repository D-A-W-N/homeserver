# Analyse des Konzepts

Review von [KONZEPT.md](KONZEPT.md). Gesamteindruck: sehr solide. Die Schichtung (Minimal-Image, Repo, Host-Config), die Datenlayout-Regeln (ein Mountpoint für Hardlinks, `nofail` + `RequiresMountsFor`) und die Sicherheitsregeln beim Partitionieren sind gut durchdacht. Die Schwächen liegen weniger in der Technik als in **zwei Widersprüchen zum Kernziel „alles reproduzierbar aus einer Config“** und in einigen unverifizierten Installer-Annahmen.

Legende: 🔴 vor Umsetzung entscheiden · 🟠 sollte geändert werden · 🟡 Verbesserung

## 1. Konzeptionelle Widersprüche

### 🔴 1.1 Samba-Shares: deklarativ oder in Cockpit gepflegt?
Ziel ist „alles Individuelle in einer `config.yml`“ (Abschnitt 1, 6). Gleichzeitig wird `smb.conf` nach dem ersten Lauf **nicht mehr von Ansible verwaltet**, Shares leben in der Samba-Registry und werden per Cockpit-Plugin gepflegt (7.3). Folgen:

- Neuinstallation + `config.yml` stellt Shares nicht wieder her, die Wahrheit liegt in `/var/lib/samba` bzw. `smb.conf`.
- `shares:` in `config.yml` wirkt nur beim allerersten Lauf, danach irreführend.
- Die Abhängigkeit von 45Drives-Plugins (siehe 2.1) trägt die Kernfunktion „Shares verwalten“.

**Empfehlung:** Shares deklarativ per Ansible (`/etc/samba/shares.conf` per `include`, bei jedem Lauf gerendert). Cockpit nur zum Ansehen/Monitoring. Das `cockpit-file-sharing`-Plugin wird optional, nicht tragend. Bei nur einem Benutzer und wenigen Shares ist das einfacher und robuster.

### 🔴 1.2 Dasselbe Problem bei Dockge und den Compose-Dateien
Ansible rendert `/opt/stacks/<name>/compose.yaml`, Dockge soll sie aber editieren (D3). Der nächste Playbook-Lauf überschreibt Änderungen aus Dockge, oder man verbietet Ansible das Überschreiben und hat wieder Drift.

**Empfehlung:** Eine klare Regel festlegen:
- *Ansible ist Wahrheit* (Compose per Template, Änderungen über Variablen/Repo, Dockge nur Start/Stop/Logs/Update) – passt zum Reproduzierbarkeitsziel, **oder**
- *Dockge ist Wahrheit* (Ansible legt Compose nur an, wenn nicht vorhanden, `force: false`).

Ich empfehle die erste Variante; dann ist Dockge ein Komfort-Frontend und die Begründung in D3 („Stacks liegen im Git-Repo“) wird ehrlich: sie liegen im Repo, nicht in `/opt/stacks`.

### 🟠 1.3 Config-Ordner auf der HDD
`configs/` (SQLite-Datenbanken von Sonarr/Radarr/Emby, InfluxDB) liegt auf der rotierenden, einzelnen Platte. Nachteile: langsame Random-I/O (Emby-Bibliothek, Sonarr-UI), HDD kann nie schlafen, und ein Plattenausfall nimmt Daten *und* Einstellungen mit. Der Vorteil „Container schreiben bei fehlender HDD nicht auf die SSD“ lässt sich anders lösen (siehe 3.1).

**Empfehlung (entschieden: HDD bleibt, siehe PLAN E3):** App-Configs auf die SSD (z. B. `/srv/appdata`), nur Medien/Downloads auf die HDD, Configs per restic sichern. Die SSD hat laut Konzept 100 GB, das reicht. Bewusste Entscheidung nötig; falls Configs bei der HDD bleiben, Begründung in D-Liste ergänzen.

## 2. Technische Risiken

### 🟠 2.1 45Drives-Repo
Pakete sind für Ubuntu gebaut, Debian-13-Support ungeklärt, Installation per heruntergeladenem Skript (Supply-Chain, im Konzept selbst erwähnt). Das ist das größte Risiko für M2.
**Maßnahme:** Als erstes Spike (M0.5), bevor andere Arbeit darauf aufbaut. Mit 1.1 entfällt die Abhängigkeit weitgehend. `cockpit-navigator` und `cockpit-identities` sind „nice to have“.

### 🟠 2.2 Preseed: Prioritäten (`priority=critical`)
Benutzername/Passwort sind im Installer Fragen mit Priorität *high*. Bei `priority=critical` werden sie voraussichtlich **nicht angezeigt**, `seen false` erzwingt die Anzeige nur eingeschränkt. Dasselbe gilt für die Bestätigungsfrage vor dem Partitionieren, auf der die zentrale Sicherheitsregel beruht (7.1). Das ist im Konzept als [VERIFY] markiert, hat aber Folgen für das Design:
- Entweder `priority=high` und alle ungewollten Fragen explizit vorbelegen,
- oder Benutzer/Passwort in `late_command`/erstem Boot abfragen, und nur die Platte bestätigen lassen.
**Maßnahme:** Spike in der VM, bevor `build-iso.sh` geschrieben wird.

### 🟠 2.3 Plattenauswahl nur nach `rotational == 0`
Widerspricht dem Ziel „läuft auch auf der Hardware eines Freundes“: Wer eine HDD als Systemplatte hat (oder eine VM mit falsch gemeldeter `rotational`), bekommt nie die automatische Auswahl und im Setup-Skript ebenfalls keinen Single-Disk-Modus. Der Fallback „Installer fragt“ ist akzeptabel, aber:
- Single-Disk-Modus (aktuell M7) ist für Freunde/VMs/Tests praktisch Pflicht → in M4 vorziehen.
- Zusätzlicher Schutz: Kandidaten mit vorhandenem Dateisystem/Partitionstabelle in der Rückfrage anzeigen (Größe, Modell, Seriennummer), nicht nur `sdX`.

### 🟠 2.4 `build-iso.sh`
- Debian-13-ISO enthält zusätzlich `md5sum.txt`; nach dem Ändern von Dateien wird die Medienprüfung fehlschlagen. Neu erzeugen.
- Bootmenü per Voranstellen an `grub.cfg`/`txt.cfg` ist fragil (doppelte `set default`, Themes, Submenüs).
- Alternative ohne ISO-Umbau: Preseed in die `initrd` einbetten oder dauerhaft nur den Dev-Modus (`url=`) nutzen und die URL auf `raw.githubusercontent.com/<repo>/<tag>/...` zeigen lassen. Spart den kompletten ISO-Bau und alle Pfad-Risiken.
- SHA256 des Eingabe-ISOs prüfen (steht in 14, aber nicht im Skript).
**Empfehlung:** Erst Weg „Boot-Parameter + Preseed-URL auf GitHub-Tag“, ISO-Build optional später (M7 mit CI).

### 🟠 2.5 Netz im Installer / Hardcoding im Preseed
Locale, Tastatur, Zeitzone, Hostname, Mirror sind fest auf Deutschland/`nas` verdrahtet, während `config.yml` diese Werte variabel macht. Für andere Nutzer Platzhalter in `preseed.cfg.in` (`@TZ@`, `@KEYMAP@`, `@HOSTNAME@`) und Variablen in `build-iso.sh`.

### 🟡 2.6 Docker: nur `RequiresMountsFor` reicht nicht ganz
Läuft das System ohne Mount, kann trotzdem ein Prozess Dateien in den leeren Mountpoint auf der SSD schreiben (z. B. Samba, manuelle Arbeit). **Maßnahme:** Mountpoint vor dem Mounten `chattr +i` setzen; ein gemountetes Dateisystem ist davon nicht betroffen.

### 🟡 2.7 Unattended-Upgrades
- Kernel-/libc-Updates brauchen Neustart: `Automatic-Reboot` mit Zeitfenster entscheiden oder `needrestart` einplanen.
- Docker-Repo ist standardmäßig nicht in den erlaubten Origins, Docker-Updates passieren manuell. Entscheidung dokumentieren.

### 🟡 2.8 Wiederholbarkeit des Playbooks
`homeserver-setup` führt Ansible aus und erzeugt `config.yml` interaktiv. Besser Trennung: `config.yml` ist die einzige Eingabe, `ansible-playbook` ist jederzeit ohne das Skript lauffähig (steht so im Konzept, in der Abnahme explizit prüfen: `changed=0`).

## 3. Container und Images

### 🟠 3.1 `:latest` überall
Reproduzierbar ist das nicht: Ein Neuaufbau in einem Jahr liefert andere Versionen, Breaking Changes kommen unbemerkt beim „Pull + Redeploy“. **Empfehlung:** Image-Tags festpinnen (Version in `group_vars/all.yml` oder in den Templates), Renovate/Dependabot für Update-PRs im Repo.

### 🟡 3.2 Einzelne Details
- Healthchecks via `curl` setzen voraus, dass `curl` im Image vorhanden ist (hotio: ja, vor Einsatz prüfen). `/ping` existiert in Sonarr/Radarr.
- Scrutiny-Geräteliste aus `ansible_devices` enthält auch USB-Sticks/Wechselmedien; Filter besser über `ansible_devices[x].removable == '0'` **und** Host-Bus-Typ, plus Test mit Stick im System.
- `ps2gamemanager` mit komplettem `${DATA}:/nas` schreibbar: Default besser nur `media/games`, wie im Kommentar selbst angeregt.
- Emby: `latest` kann Major-Updates erzwingen (4.8 → 4.9); pinnen.
- Recommendarr/PS2GameManager-Images liegen unter `ghcr.io/d-a-w-n/...` (eigene Images?) – Verfügbarkeit/öffentliche Sichtbarkeit sicherstellen, sonst scheitert der Stack bei Dritten.

## 4. Sicherheit und Betrieb

### 🟠 4.1 SSH-Härtung ist M7, sollte M1 sein
Billig und wichtig; ein Server mit Passwort-SSH im LAN ist ok, aber Schlüssel-Login gehört in `base`. Mit Variable `ssh_authorized_keys` in der Config (öffentliche Schlüssel sind kein Secret).

### 🟠 4.2 Keine Host-Firewall, Docker umgeht sie
Akzeptiert im Konzept für den Anfang. Mindestens eine nftables-Baseline (SSH, Samba, Cockpit nur aus LAN-Subnetz) und Ports im Compose an die LAN-Adresse binden oder `DOCKER-USER` nutzen. Als eigene Rolle `firewall` planen, Default aus.

### 🟠 4.3 Backup ist Phase 2, aber auch Voraussetzung
Solange keine Backups laufen, ist ein Ausfall der einzigen Platte inkl. Configs endgültig. Mindestens: Config-Export (Sonarr/Radarr-Backups, Emby) auf einen anderen Rechner, bevor das Altsystem abgeschaltet wird. Backup vor die Stacks-Umstellung ziehen (M6 vor M8 steht bereits im Runbook).

### 🟡 4.4 Monitoring/Benachrichtigung fehlt
Scrutiny sammelt SMART, meldet aber nichts. Fehlgeschlagene Backups, unattended-upgrades und Plattenwarnungen landen unbemerkt im Journal. Kleinstlösung: `msmtp`/ntfy-Hook, Scrutiny-Notifications, `OnFailure=`-Unit für den Backup-Timer.

### 🟡 4.5 Samba-Komfort
Ohne NetBIOS taucht der Server nicht in Windows auf. `wsdd2`/`wsdd-server` (WS-Discovery) löst das und ist ein Paket. Optional per Variable.

### 🟡 4.6 Dockge-Socket
Dockge ist root-äquivalent, wie dokumentiert. Zusätzlich an LAN binden und nicht dauerhaft nötig machen, wenn Variante 1.2 (Ansible ist Wahrheit) gewählt wird: Dockge dann optional.

## 5. Tests und Prozess

### 🟠 5.1 CI testet nur Syntax
Das reicht für M0, aber Rollen-Fehler (Handler, Idempotenz, Pfade) fallen erst in der VM auf. **Maßnahme:** Zusätzlicher Job `idempotence`: Debian-13-Container oder `systemd`-Container, Playbook zweimal laufen lassen (ohne Mount-/Docker-Teile), `changed=0` prüfen. Molecule ist hier overkill, ein Shell-Job reicht.
Außerdem Version von `ansible-core` und `ansible-lint` pinnen, sonst bricht CI ohne Codeänderung (Trixie liefert eine andere Version als `pip install ansible`).

### 🟠 5.2 Anhänge A–E duplizieren Code
Skripte, Compose-Vorlagen und CI-Workflow stehen im Konzept **und** werden im Repo liegen. Beide Fassungen laufen auseinander. **Maßnahme:** Beim Umsetzen den Code in die echten Dateien verschieben und im Konzeptdokument durch Verweise ersetzen. `docs/KONZEPT.md` bleibt Entscheidungsdokument.

### 🟡 5.3 Reihenfolge
Die Roadmap baut erst alles und testet den Installer zuletzt (M5), obwohl dort die meisten Unbekannten sitzen. Risikobasiert: Spikes (45Drives auf Trixie, Preseed-Fragenverhalten) früh, Installer parallel zum Kern, nicht danach.

### 🟡 5.4 Öffentliches Repo
- Persönliche Beispielwerte (`admin_user: nils` in 6) durch Neutrales ersetzen.
- Secrets-Check im CI (`gitleaks` oder `detect-secrets`), `.gitignore` mit `config.yml`, `vault.yml`, `*.env`.
- Sprache entscheiden: Docs deutsch, Code-Kommentare/Skriptausgaben englisch oder ebenfalls deutsch. Konsistent halten.

## 6. Kleinigkeiten

- „15 GiB RAM“ in 2: vermutlich 16 GB abzüglich Grafikspeicher, egal, aber D12 (zram) bei 15 GB nur eingeschränkt nötig; Swap-Partition kann entfallen oder winzig sein.
- `data_fs` „vom Setup erkannt“ vs. Default `ext4` in 6: einmal klar benennen (das Setup *wählt*, `all.yml` ist nur Fallback).
- Port-Tabelle: Cockpit 9090 und Recommendarr 3000 stehen in der Tabelle, aber keine automatische Prüfung auf Konflikte. Ein `assert` auf doppelte Hostports im Playbook ist billig.
- Abschnitt 12/M2 setzt Windows als Testclient voraus; für VM-Tests auch `smbclient` und `mount.cifs` vorsehen.
