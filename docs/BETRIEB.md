# Betrieb

Bedienung des fertig eingerichteten NAS: Zugänge, Updates, Backup, Fehlersuche. Wie das System aufgebaut ist und warum, steht im [Projektplan](PLAN.md).

## Zugänge

Alle Adressen und Passwörter stehen in der Zugangsübersicht, die das Setup am Ende anzeigt:

```bash
sudo cat /etc/aunserver/zugaenge.txt
```

Einmalig nötig, damit die Namen wie `https://home.nas.home.arpa` funktionieren:

1. **Router:** DNS-Server auf die IP des NAS stellen (AdGuard Home beantwortet die Namen und filtert Werbung).
2. **Jedes Gerät:** das Stammzertifikat von `http://nas.home.arpa/ca.crt` installieren. Danach zeigt der Browser keine Zertifikatswarnungen mehr.

Einstieg ist die Startseite `https://home.nas.home.arpa`, dort sind alle Apps verlinkt. **Cockpit** (`https://cockpit.nas.home.arpa`, direkt auch `https://<IP>:9090`) läuft auf dem Host und bleibt erreichbar, auch wenn Docker nicht läuft.

## Alltag

| Aufgabe | Wo |
|---|---|
| Samba-Freigabe anlegen, ändern, Rechte | Cockpit → File Sharing |
| Dateien ansehen, verschieben | Cockpit → Navigator |
| Benutzer und Samba-Passwörter | Cockpit → Identities |
| Platten, Speicherplatz, Systemlogs, Terminal | Cockpit |
| Container starten/stoppen, Logs | Arcane (`arcane.…`), Logs auch in Dozzle (`logs.…`) |
| CPU, RAM, Temperaturen, Alarme | Beszel (`monitor.…`) |
| Festplattengesundheit (SMART) | Scrutiny (`disks.…`) |
| Filme, Serien, Musik suchen | Sonarr, Radarr, Lidarr; Downloads in SABnzbd, Indexer in Prowlarr |
| Untertitel | Bazarr (holt sie automatisch für alles aus Sonarr/Radarr) |
| Abspielen | Emby; Fernseher und Apps über `http://<IP>:8096` |

**Image-Versionen nicht in Arcane aktualisieren.** Die Versionen stehen fest im Repo, und das nächste Setup würde sie zurückdrehen. Neue Versionen kommen über `aunserver-update` (siehe unten).

Ordner auf der Datenplatte (`/srv/data`): `usenet/` (Downloads), `media/tv|movies|music|books` (Bibliotheken), `games/` (PS2 und Eigenes). Die Einstellungen der Apps liegen auf der SSD unter `/srv/appdata`.

## Benachrichtigungen aufs Handy

Die ntfy-App mit dem Server `https://ntfy.nas.home.arpa` verbinden (unterwegs über Tailscale) und diese Themen abonnieren:

| Thema | Meldet |
|---|---|
| `beszel` | CPU oder RAM über 90 %, Platte über 90 % voll, Temperatur über 80 °C, System nicht erreichbar |
| `smart` | Festplatte mit SMART-Fehlern (Scrutiny) |
| `backup` | Nächtliches Backup fehlgeschlagen |
| `updates` | Neuer Stand von aunserver verfügbar |

Auf dem Handy muss dafür das Stammzertifikat installiert sein (siehe Zugänge).

## Fernzugriff (Tailscale)

Einmalig nach dem Setup im Tailscale-Konto:

1. **Machines → nas → Edit route settings:** die angebotene Route (IP des NAS) freigeben. Im selben Menü **Disable key expiry** wählen, sonst meldet Tailscale das NAS nach 180 Tagen ab und der Fernzugriff ist weg.
2. **DNS → Nameservers → Add nameserver → Custom:** die Tailscale-IP des NAS (`sudo tailscale ip -4`) eintragen und **Override local DNS** einschalten. Dann gelten die `….nas.home.arpa`-Namen auch unterwegs.
3. **Handy:** Tailscale-App anmelden, Stammzertifikat installieren, ntfy-App einrichten.

Ist das NAS abgemeldet (z. B. nach einer Neuinstallation), steht das oben in der Zugangsübersicht. Neu anmelden mit `sudo tailscale up`.

## Updates

| Was | Wie |
|---|---|
| Debian, Docker, Cockpit, Tailscale | automatisch jede Nacht (unattended-upgrades); Neustart, falls nötig, um 04:00 |
| aunserver selbst und alle App-Images | täglicher Check, ein neuer Stand kommt als ntfy-Meldung (`updates`) mit der Liste der Änderungen; installieren per Hand |

```bash
sudo aunserver-update            # Änderungen anzeigen, nachfragen, Backup, aktualisieren, Setup ausführen
sudo aunserver-update --check    # nur nachsehen
sudo aunserver-update --rollback # zurück zum Stand vor dem letzten Update
```

Woher neue Versionen kommen: Renovate prüft das Repo und legt für jede neue Image-Version einen Pull Request an. Die CI testet ihn in einer VM, danach wird er gemergt. Alles, was in `main` landet, meldet das NAS als Update.

## Konfiguration ändern

Alle Einstellungen (Hostname, Apps, Backup-Ziel, PS2-Freigabe …) stehen in `/etc/aunserver/config.yml`. Ändern und danach abgleichen:

```bash
sudo nano /etc/aunserver/config.yml
sudo aunserver-setup             # übernimmt die Datei und richtet alles danach ein
```

Das Setup ist jederzeit gefahrlos wiederholbar. Es formatiert nur, wenn man ausdrücklich eine neue Datenplatte auswählt und deren Namen eintippt.

## Backup und Wiederherstellung

**Was gesichert wird:** die Einstellungen, nicht die Mediendateien. Das sind die App-Einstellungen (`/srv/appdata`, ohne Logs, Cover und Caches), die Stacks (`/opt/stacks`), `/etc/aunserver` (Konfiguration, Passwörter, Schlüssel), die Samba-Benutzer und die Freigaben. Die Mediendateien auf der Datenplatte sind **nicht** dabei, dafür wäre das Ziel zu klein; sie lassen sich über Sonarr/Radarr erneut laden.

**Wann:** täglich um 03:30. Die Medien-Apps halten dafür kurz an. Aufbewahrt werden 7 tägliche, 4 wöchentliche und 6 monatliche Stände. Schlägt ein Backup fehl, kommt eine ntfy-Meldung.

**Das Backup-Passwort** steht in der Zugangsübersicht. Ohne es ist das Backup wertlos, deshalb **zusätzlich außerhalb des NAS aufbewahren** (Passwortmanager, Ausdruck).

```bash
sudo aunserver-backup              # jetzt sichern
sudo aunserver-backup snapshots    # Stände auflisten
sudo aunserver-backup restore      # letzten Stand zurückspielen (oder: restore <ID>)
sudo aunserver-setup               # danach einmal abgleichen
```

Das Ziel steht in `config.yml` unter `backup:`. Mögliche Ziele:
- eine USB-Platte: `repository: /mnt/backup/aunserver`, `disk_label: AUNBACKUP`; die Platte mit diesem Label beschriften,
- ein anderer Rechner per SSH: `repository: sftp:user@rechner:/pfad`,
- jedes andere restic-Ziel; Zugangsdaten dafür unter `backup.env`.

### Neuinstallation aus dem Backup

1. Vom USB-Stick installieren (siehe [README](../README.md)).
2. `sudo /opt/aunserver/bin/aunserver-setup --restore` ausführen. Das Setup fragt wie gewohnt alles ab, dazu Backup-Ziel und Backup-Passwort. Nach der Einrichtung spielt es das Backup zurück und gleicht das System damit ab.
3. Tailscale neu anmelden: `sudo tailscale up`.

Ergebnis: dieselben Apps mit denselben Einstellungen, Freigaben, Passwörtern und API-Schlüsseln. In der VM ist das getestet.

## PS2 (Open PS2 Loader)

Die SMB1-Freigabe `PS2SMB` läuft als eigene Samba-Instanz auf **Port 1445**, nur für den Ordner `games/ps2` und das Konto `ps2`. In OPL unter Netzwerkeinstellungen: IP des NAS, Port 1445, Freigabe `PS2SMB`, Benutzer `ps2`. Spiele legt man über die normale Freigabe oder den PS2GameManager in `games/ps2` ab.

SMB1 ist unsicher: kein wichtiges Passwort verwenden. Die Freigabe bleibt auf das Heimnetz beschränkt.

## Fehlersuche

| Problem | Nachsehen |
|---|---|
| Setup bricht ab | Meldung im Terminal, ausführlich in `/var/log/aunserver-setup.log`; Ursache beheben und Setup erneut starten |
| Update kaputt | `sudo aunserver-update --rollback` |
| App startet nicht | Arcane bzw. Dozzle: Log des Containers |
| Namen gehen nicht | Router-DNS zeigt auf das NAS? AdGuard läuft? Direkt per IP: Cockpit `https://<IP>:9090` |
| Datenplatte fehlt | Docker startet bewusst nicht, solange sie fehlt. Der leere Mountpoint `/srv/data` ist schreibgeschützt, damit nichts auf der SSD landet. Platte anschließen und neu starten |
| Backup schlägt fehl | `journalctl -u aunserver-backup`; USB-Platte angeschlossen? |
| Zertifikatswarnung | Stammzertifikat auf dem Gerät installiert? (`http://nas.home.arpa/ca.crt`) |

Dienste auf dem Host: `systemctl status docker smbd cockpit.socket tailscaled`. Container: `docker ps`, Stacks unter `/opt/stacks/<name>/compose.yaml`.
