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

- [x] Weboberfläche: Cockpit mit den Plugins funktioniert (Rückmeldung 2026-10-17).
- [ ] Eine per Klick angelegte Freigabe ist in `net conf listshares` noch nicht aufgetaucht. Prüfen, ob sie angelegt wurde und wo das Plugin sie speichert.

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

Auf der VM läuft `cupsd` (Druckdienst). Der Preseed muss die Paketauswahl so eng fassen, dass kein Druck- oder Desktop-Zubehör mitkommt. → Mit `tasksel ssh-server` ohne `standard` erledigt (S2).

## S2 – Preseed und Installer

**Datum:** 2026-10-17 · **Ergebnis:** ✅ (BIOS-Boot noch offen)

**Aufbau:** Kernel und Initrd aus dem Debian-13.7-netinst-ISO per `qemu -kernel/-initrd` mit `auto=true priority=critical url=http://10.0.2.2:8000/preseed.cfg` gestartet, ISO als CD-Laufwerk, UEFI (OVMF). Bedient per QEMU-Monitor (`screendump`, `sendkey`). Die Fassungen von [`installer/preseed.cfg.in`](../installer/preseed.cfg.in) und [`installer/select-disk.sh`](../installer/select-disk.sh) im Repo entsprechen dem getesteten Stand.

### ISO-Aufbau (für `build-iso.sh`)

`/install.amd/vmlinuz`, `/install.amd/initrd.gz` (Text), `/install.amd/gtk/initrd.gz` (grafisch), `/boot/grub/grub.cfg` (UEFI, mit Theme und Untermenü „Advanced options“), `/isolinux/txt.cfg` (BIOS, 4 Zeilen), `/md5sum.txt` (933 Einträge).

### Welche Fragen erscheinen (`priority=critical`)

| Frage | Preseed | Ergebnis |
|---|---|---|
| Sprache, Tastatur, Zeitzone, Netz, Mirror | vorbelegt | nicht gefragt ✅ |
| Hostname | `get_hostname` + `seen false` | **nicht gefragt, und der Wert wird ignoriert** (System heißt `debian`) |
| Benutzername | Default + `seen false` | gefragt, Vorschlag aus dem Preseed ✅ |
| Passwort (zweimal) | nur `seen false` | gefragt ✅ |
| Systemplatte bestätigen (eigene Frage aus `select-disk.sh`) | – | gefragt, Vorauswahl „Ja“ ✅ |
| Partitionierungsmethode + Platte | – | **nur** wenn `select-disk.sh` keine Platte setzt; zeigt Größe und Modell ✅ |
| Änderungen auf die Festplatten schreiben? | `partman/confirm` nicht gesetzt | gefragt, **Vorauswahl „Nein“** ✅ |
| Danach | – | keine Fragen mehr, `debian-installer/exit/poweroff` schaltet ab |

### Plattenauswahl

| Lauf | Belegung | Ergebnis |
|---|---|---|
| 1 | SSD 20 GB an Port 0, HDD 50 GB an Port 1 | SSD gewählt, installiert, HDD danach **0 Byte belegt** ✅ |
| 2 | HDD an Port 0, SSD an Port 1 | SSD gewählt ✅ (im Installer trotzdem `sda`) |
| 3 | zwei SSDs | Skript legt sich nicht fest, Installer **fragt** ✅ |
| A | zwei SSDs, Skript erzwingt `sdb` (Testvariante) | Installer partitioniert `sdb` ✅, folgt also der Wahl des Skripts |

### Befunde

1. **`admin` ist in Debian ein reservierter Benutzername**, der Installer lehnt ihn ab. → Default `admin_user: nasadmin`.
2. **Hostname lässt sich bei `priority=critical` nicht abfragen**, der Preseed-Wert wird ignoriert. → Der Installer fragt ihn nicht, `aunserver-setup` setzt ihn.
3. **Gerätenamen sind nicht stabil:** In Lauf 1 war die SSD im Installer `sda` und im installierten System `sdb`. In Lauf 2 war die SSD am zweiten Port im Installer `sda`. Bestätigt die Regel „Platten nur nach Merkmalen“.
4. `blkid` ist im Installer vorhanden (`/sbin/blkid`), `rotational` wird mit QEMU-`rotation_rate` korrekt gemeldet.
5. Der Bestätigungsdialog des Installers nennt die Platte nur als `SCSI3 (0,0,0) (sda)`, ohne Größe und Modell. → `select-disk.sh` stellt vorher eine **eigene Rückfrage** mit Modell, Größe und Seriennummer (debconf-Template, funktioniert aus `early_command`). Bei „Nein“ fragt der Installer selbst.
6. SATA-Platten haben kein `device/serial`, die Seriennummer steht als letztes Wort in `device/wwid`. Auf NVMe gibt es `device/serial` (auf dem Entwicklungsrechner geprüft).
7. Ergebnis der Installation: Debian 13.7, Kernel 6.12.113, **272 Pakete**, nur `sshd` lauscht, kein cups/Desktop/Exim. Benutzer in `sudo`, root gesperrt, `de_DE.UTF-8`, Tastatur `de`, Quellen `main non-free-firmware` + security + updates (klassische `sources.list` mit `deb-src`; Ansible stellt auf deb822 um). Partitionen: ESP 966 MB, ext4, Swap 1 GB.
8. `debconf-get` in der Konsole zeigte den gesetzten Wert nicht an; als Nachweis dient Lauf A.

### Offen

- [ ] BIOS-Boot (Testmatrix 2), insbesondere GRUB auf der gewählten Platte (`grub-installer/bootdev`)
- [ ] Verhalten mit Platte, die bereits `AUNDATA` trägt (Testmatrix 8), und mit USB-Stick als Installationsmedium (Ausschluss per `*usb*`)
- [ ] Bootmenü-Eintrag im eigenen ISO (M7)

## S3 – AdGuard Home auf Port 53, Caddy mit `tls internal`

**Datum:** 2026-10-17 · **Ergebnis:** ✅

### Versionen

| Komponente | Version |
|---|---|
| Docker CE (download.docker.com, Suite `trixie`) | 29.9.1, Compose 5.6.0, Firewall-Backend iptables über nf_tables |
| Docker-Repo-Schlüssel | Fingerabdruck `9DC8 5822 9FC7 DD38 854A E2D8 8D81 803C 0EBF CD88` |
| AdGuard Home | `adguard/adguardhome:v0.107.79` |
| Caddy | `caddy:2.11.7` |

### Aufbau

- **AdGuard und Caddy laufen mit `network_mode: host`.** Alle anderen Container veröffentlichen Ports nur an `127.0.0.1`, Caddy erreicht sie dort. Damit öffnet Docker selbst keinen Port ins LAN, und die Host-Firewall gilt für alles, was erreichbar ist (siehe S4). AdGuard sieht außerdem die echten Client-IPs.
- `systemd-resolved` ist auf Debian 13 nicht aktiv, Port 53 ist frei.

### Befunde

1. **AdGuard lässt sich komplett per API einrichten** (gut für Ansible):
   - `POST /control/install/configure` mit `web`, `dns`, `username`, `password`
   - `POST /control/rewrite/add` mit `{"domain":"*.nas.home.arpa","answer":"<NAS-IP>"}`
2. **Fallstrick:** Der Assistent lauscht selbst auf `*:3000`. Die Weboberfläche auf `127.0.0.1:3000` zu legen scheitert mit `address already in use`. → Die Weboberfläche kommt auf **`127.0.0.1:8083`**.
3. DNS funktioniert: Wildcard-Rewrite → NAS-IP, externe Namen werden aufgelöst, `doubleclick.net` → `0.0.0.0`, sobald die Filterliste geladen ist (AdGuard DNS filter, rund 186.000 Regeln, beim ersten Start einige Sekunden).
4. Caddy mit globalem `local_certs`: Jede Site bekommt ein Zertifikat der eigenen CA. `curl --cacert root.crt` → HTTP 200, `http://` → 308 auf HTTPS. Root-Zertifikat: `/data/caddy/pki/authorities/local/root.crt` im Caddy-Volume.
5. **Fallstrick:** Wird die Caddyfile als *einzelne Datei* gemountet, sieht der Container nach `sed -i` oder Ansible-`template` (neue Inode) weiter die alte Version, auch nach `caddy reload`. → Den **Ordner** `/etc/caddy` mounten.
6. Caddys Admin-API lauscht auf `127.0.0.1:2019`, also nur lokal.

## S4 – Docker-Ports an 127.0.0.1 und nftables

**Datum:** 2026-10-17 · **Ergebnis:** ✅

Gemessen vom Entwicklungsrechner über QEMU-Portweiterleitungen (in der VM kommen die Pakete wie aus dem LAN an, Quelle `10.0.2.2`). Ein Testcontainer `leak` war absichtlich auf `0.0.0.0:8099` veröffentlicht.

| Dienst | ohne Firewall | nur input-Kette (drop) | + forward-Regel |
|---|---|---|---|
| `leak` 0.0.0.0:8099 | offen | **offen** (Docker umgeht input) | **zu** ✅ |
| whoami / AdGuard-UI / Caddy-Admin an 127.0.0.1 | zu | zu | zu |
| Caddy :80/:443, Cockpit :9090, SSH, Samba :445 | offen | offen | offen |
| Samba-Legacy :1445, `ps2_clients` passt nicht | offen | – | **zu** ✅ |
| DNS UDP :53 | – | – | offen ✅ |

Container erreichen mit der forward-Regel weiterhin das Internet und sich gegenseitig.

### Getestetes Regelwerk

```nft
table inet aunserver
delete table inet aunserver
table inet aunserver {
	set lan4 { type ipv4_addr; flags interval; elements = { 10.0.2.0/24 } }
	set ps2_clients { type ipv4_addr; flags interval; elements = { 10.0.2.99 } }

	chain input {
		type filter hook input priority filter; policy drop;
		iif lo accept
		ct state established,related accept
		ct state invalid drop
		meta l4proto { icmp, ipv6-icmp } accept
		iifname "docker0" accept
		iifname "br-*" accept
		ip saddr @lan4 tcp dport { 22, 53, 80, 443, 445, 5357, 9090 } accept
		ip saddr @lan4 udp dport { 53, 443, 3702 } accept
		ip saddr @ps2_clients tcp dport 1445 accept
		iifname "tailscale0" tcp dport { 22, 53, 80, 443, 445, 9090 } accept
		iifname "tailscale0" udp dport { 53, 443 } accept
	}

	# Sicherheitsnetz: versehentlich auf 0.0.0.0 veröffentlichte Container-Ports
	# sind aus LAN/VPN nicht erreichbar (Docker leitet sie an input vorbei).
	chain forward {
		type filter hook forward priority filter - 10; policy accept;
		ct state new ct status dnat iifname != { "docker0", "lo" } iifname != "br-*" drop
	}
}
```

### Befunde

1. **Eigene Tabelle `inet aunserver`, niemals `flush ruleset`.** Debians Standard-`/etc/nftables.conf` beginnt mit `flush ruleset`. Wird `nftables.service` damit aktiviert, löscht jeder Neustart des Dienstes die Regeln von Docker. → Die Rolle ersetzt `/etc/nftables.conf` durch eine Datei, die nur `include "/etc/nftables.d/*.nft"` enthält. `table …` + `delete table …` am Anfang macht das Laden idempotent.
2. Die forward-Regel blockt nur **neue, per DNAT umgeleitete** Verbindungen, die nicht aus einem Docker-Netz kommen. Ports an `127.0.0.1` laufen über `docker-proxy` auf `lo` und sind nicht betroffen.
3. Container dürfen den Host erreichen (`docker0`, `br-*`), z. B. für den Beszel-Agent oder AdGuard als DNS.
4. Gegen Aussperren beim Testen: `systemd-run --on-active=300 nft delete table inet aunserver` vor dem Laden.

### Offen

- [ ] IPv6: Regeln für das LAN-Präfix (`lan6`) und Link-Local ergänzen, sobald bekannt ist, ob das Heimnetz IPv6 verteilt.
- [ ] Tailscale-Regeln mit echtem `tailscale0` testen (M8).
