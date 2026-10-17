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

## S2 – Preseed und Installer

*noch offen*

## S3 – AdGuard Home auf Port 53, Caddy mit `tls internal`

*noch offen* · Vorbefund: `systemd-resolved` ist auf einem frischen Debian 13 **nicht aktiv**, Port 53 ist frei.

## S4 – Docker-Ports an 127.0.0.1 und nftables

*noch offen*
