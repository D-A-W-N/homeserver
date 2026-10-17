# Spikes (M1)

Ergebnisse der Vorab-Tests aus [PLAN.md](PLAN.md), Meilenstein M1. Getestet in der QEMU-VM (`dev/vm-test.sh install 1`).

## S1 – Cockpit-Plugins und Samba-Registry auf Debian 13

**Datum:** 2026-10-17 · **System:** Debian 13.7, Kernel 6.12.113 · **Ergebnis:** ✅ machbar, mit Auflagen

### Versionen

| Paket | Quelle | Version |
|---|---|---|
| cockpit, cockpit-storaged, cockpit-packagekit | `trixie-backports` | 368-1~bpo13+1 (trixie selbst: 337) |
| samba | trixie | 4.22.11 |
| wsdd2 | trixie | 1.8.7 |
| cockpit-file-sharing | GitHub-Release, **Trixie-Paket** | 4.6.3-1trixie |
| cockpit-identities | GitHub-Release, **Trixie-Paket** | 0.1.14-1trixie |
| cockpit-navigator | GitHub-Release, nur **Bookworm-Paket** (`_all`) | 0.6.1-1bookworm |

### Befunde

1. **Das 45Drives-Apt-Repo kennt kein Trixie** (nur bionic, bullseye, focal). Die GitHub-Releases liefern dagegen Trixie-Pakete. → Die Plugins werden als `.deb` von GitHub installiert, mit **Version und SHA256 gepinnt** (GitHub liefert den Digest in der Release-API). Kein Fremd-Repo, kein `curl | sh`.
2. Navigator 0.6.1 gibt es nur für Bookworm. Es ist ein reines Web-Paket, installiert sich auf Trixie ohne Fehler, und Cockpit erkennt es.
3. Alle drei Plugins erscheinen in `cockpit-bridge --packages`.
4. **`cockpit-file-sharing` zieht `nfs-kernel-server` mit, und der Dienst läuft sofort.** Dazu lauscht `rpcbind` auf Port 111. → Die Rolle muss `nfs-server`, `rpcbind` und `rpcbind.socket` maskieren.
5. Ebenfalls mitinstalliert: `python3-botocore` (für die S3-Funktion des Plugins). Das ist harmlos, aber unnötig.
6. Samba im Registry-Modus (`include = registry`) funktioniert:
   - Freigabe per `net conf addshare` (so arbeitet auch das Plugin) ist sofort aktiv.
   - Der Benutzer kann schreiben, und die Dateien gehören ihm.
   - Gastzugriff → `NT_STATUS_ACCESS_DENIED` ✅
   - SMB2 → `NT_STATUS_NOT_SUPPORTED` ✅ (`server min protocol = SMB3`)
7. `smbd` lauscht auch mit `disable netbios = yes` auf **Port 139**. → `smb ports = 445` setzen.
8. Neue Dateien bekommen `-rwxr--r--` (DOS-Archivbit wird als x-Bit abgebildet). → `map archive = no`, `create mask = 0664`, `directory mask = 0775`.

### Offen

- [ ] **Prüfung in der Weboberfläche:** In Cockpit (`https://localhost:9090`, Login `testuser`) unter *File Sharing* erscheint die Freigabe `spike`. Eine neue Freigabe per Klick anlegen und per `smbclient` erreichen.

### Folgen für die Umsetzung (Rollen `cockpit`, `samba`)

Die folgende Konfiguration ist in der VM getestet: `sudo testparm -s` fehlerfrei (ohne root scheitert `testparm` am Registry-Zugriff), neue Dateien `-rw-rw-r--`, nach Maskieren von `rpcbind` lauscht nur noch Port 445.

```ini
# /etc/samba/smb.conf – von Ansible verwaltet, Freigaben stehen in der Registry
[global]
   server role = standalone server
   server min protocol = SMB3
   server signing = mandatory
   map to guest = never
   disable netbios = yes
   smb ports = 445
   map archive = no
   create mask = 0664
   directory mask = 0775
   include = registry
```

- Die globale Konfiguration bleibt in der Datei und damit unter Kontrolle von Ansible. Nur die **Freigaben** liegen in der Registry (Cockpit führend, D6).
- Start-Freigaben legt Ansible nur an, wenn sie in `net conf listshares` fehlen.
- Backup: `net conf list > /etc/aunserver/samba-registry.conf` vor jedem restic-Lauf, Wiederherstellen mit `net conf import`.

## S5 – SMB1-Freigabe für PS2/OPL neben SMB3

**Datum:** 2026-10-17 · **Ergebnis:** ✅ machbar als zweite Samba-Instanz; Test mit echter PS2 steht aus

**Problem:** Open PS2 Loader (OPL) kann nur SMB1 mit NTLMv1. `server min protocol` gilt in Samba global, eine SMB1-Freigabe in der Hauptinstanz würde SMB1 für alle Freigaben öffnen.

**Lösung:** zweite `smbd`-Instanz `smbd-legacy` mit eigener Konfiguration, eigenen State-/Lock-/Private-Verzeichnissen (also eigener Benutzerdatenbank) und eigenem Port.

Getestet (smbclient in der VM):

| Test | Ergebnis |
|---|---|
| PS2-Freigabe per SMB1, Benutzer `ps2` | ✅ lesen, schreiben, Ordner anlegen |
| PS2-Instanz per SMB2/3 | ✅ abgelehnt |
| Hauptinstanz per SMB1 | ✅ abgelehnt |
| Benutzer `ps2` an der Hauptinstanz | ✅ `LOGON_FAILURE` (getrennte Benutzerdatenbanken) |
| Hauptinstanz per SMB3 | ✅ unverändert |

**Fallstrick:** Mit `force user = <admin>` scheitert jedes Schreiben (`check_parent_access_fsp … ACCESS_DENIED`), weil Samba die Ordnerrechte mit dem Token von `ps2` prüft. `force group` allein hilft nicht. Was funktioniert: **ohne `force user`**, `ps2` ist Mitglied einer Gruppe, die den Ordner besitzt (setgid, `0775`), plus `force group`. Dateien gehören dann `ps2:<gruppe>`, `0664`, und der Admin (ebenfalls in der Gruppe) kann sie bearbeiten. Im Spike war die Gruppe die des Admins; die Rolle nutzt eine eigene Gruppe `ps2share`.

Getestete Konfiguration (Pfad in der Rolle: `/srv/data/games/ps2`):

```ini
# /etc/samba-legacy/smb.conf
[global]
   server role = standalone server
   smb ports = 1445
   server min protocol = NT1
   server max protocol = NT1
   ntlm auth = ntlmv1-permitted
   lanman auth = no
   disable netbios = yes
   map to guest = never
   load printers = no
   map archive = no
   pid directory = /run/samba-legacy
   lock directory = /var/lib/samba-legacy/lock
   state directory = /var/lib/samba-legacy
   cache directory = /var/cache/samba-legacy
   private dir = /var/lib/samba-legacy/private
   ncalrpc dir = /run/samba-legacy/ncalrpc
   log file = /var/log/samba/legacy.log

[PS2SMB]
   path = /srv/spike-ps2
   read only = no
   valid users = ps2
   force group = testuser
   create mask = 0664
   directory mask = 0775
```

```ini
# /etc/systemd/system/smbd-legacy.service
[Unit]
Description=Samba SMB1 nur für PS2/OPL
After=network.target
[Service]
Type=notify
RuntimeDirectory=samba-legacy
ExecStart=/usr/sbin/smbd --foreground --no-process-group -s /etc/samba-legacy/smb.conf
ExecReload=/bin/kill -HUP $MAINPID
[Install]
WantedBy=multi-user.target
```

Benutzer: `useradd -r -M -s /usr/sbin/nologin ps2`, Passwort mit `smbpasswd -c /etc/samba-legacy/smb.conf -a ps2`.

### Offen

- [ ] **Test mit echter PS2 und OPL:** In OPL unter Netzwerk-Einstellungen den SMB-Port auf `1445` stellen, Freigabe `PS2SMB`, Benutzer `ps2`. smbclient hat sich per NTLMv2 angemeldet. Ob OPLs NTLMv1 durchgeht, zeigt erst die Konsole.
- [ ] Falls OPL nur Port 445 kann: der Host bekommt eine **zweite IP-Adresse**. Die Hauptinstanz bindet an die erste (`interfaces`, `bind interfaces only = yes`), die PS2-Instanz an die zweite, beide auf Port 445.

### Nebenbefund für S2

Auf der VM läuft `cupsd` (Druckdienst). Der Preseed muss die Paketauswahl so eng fassen, dass kein Druck- oder Desktop-Zubehör mitkommt.

## S2 – Preseed und Installer

*noch offen*

## S3 – AdGuard Home auf Port 53, Caddy mit `tls internal`

*noch offen* · Vorbefund: `systemd-resolved` ist auf einem frischen Debian 13 **nicht aktiv**, Port 53 ist frei.

## S4 – Docker-Ports an 127.0.0.1 und nftables

*noch offen*
