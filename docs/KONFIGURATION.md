# Konfiguration

<!-- ERZEUGT aus config/schema.yml (bin/aunserver-config generate), nicht von Hand ändern. -->

Alle Einstellungen des NAS stehen in `/etc/aunserver/config.yml`. Dort reicht, was vom Standard
abweicht: Vor jedem Lauf prüft `aunserver-config` die Datei und ergänzt fehlende Werte, auch
innerhalb von Blöcken (`apps: {emby: false}` lässt die übrigen Apps auf ihrem Standard).
Die Beschreibung steht in [config/schema.yml](../config/schema.yml).

```bash
sudo nano /etc/aunserver/config.yml
sudo aunserver-config validate      # Tippfehler und falsche Werte finden
sudo aunserver-setup                # übernehmen
```

Stufen: **basis** fragt das Setup ab, **erweitert** nur bei Bedarf, **fest** setzt das Setup
(nicht von Hand ändern). Geheime Werte (Passwörter) zeigt `aunserver-config show` nicht an.

## System

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `hostname` | text (hostname) | `nas` | basis | Name des NAS im Netz |
| `admin_user` | text (hostname) | `nasadmin` | fest | Admin-Benutzer, legt der Installer an ("admin" ist in Debian reserviert) |
| `timezone` | text (zeitzone) | `Europe/Berlin` | basis | Zeitzone |
| `ssh_authorized_keys` | liste (text) | `[]` | basis | Öffentliche SSH-Schlüssel des Admins; mit Schlüssel ist der Passwort-Login per SSH aus |
| `kernel_backports` | bool | `false` | erweitert | Kernel aus den Backports (für neue Hardware) |
| `base_auto_reboot` | bool | `true` | erweitert | Nach Sicherheitsupdates automatisch neu starten, wenn nötig |
| `base_auto_reboot_time` | text (zeit) | `'04:00'` | erweitert | Uhrzeit für den automatischen Neustart (nur mit `base_auto_reboot`) |

## Netz und Zugriff

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `domain` | text | `nas.home.arpa` | basis | Voller Name des NAS im Heimnetz, die Apps liegen darunter (https://&lt;app>.&lt;domain>) |
| `lan_subnets` | liste (netz) | `[]` | erweitert | IPv4-Netze, die auf die NAS-Dienste zugreifen dürfen; leer = Netz der Standard-Schnittstelle |
| `lan6_subnets` | liste (netz) | `[]` | erweitert | IPv6-Netze mit Zugriff, z. B. fd00::/64; Link-Local ist immer erlaubt |
| `caddy_lan_ports` | bool | `false` | erweitert | Web-Apps zusätzlich unter https://&lt;LAN-IP>:&lt;Port>, nur aus dem LAN. Für Geräte, die die Namen nicht auflösen (z. B. Handy mit Mullvad-App). Ports siehe stacks_lan_ports |
| `stacks_lan_ports` | objekt (zahl) | siehe Schema | erweitert | Ports für caddy_lan_ports; die Firewall öffnet genau diese (nur LAN). Die Startseite fehlt (Links nur auf Namen) (nur mit `caddy_lan_ports`) |
| `network_tailscale_routes` | liste (netz) | `[]` | erweitert | Route ins LAN, die das NAS im Tailnet anbietet; leer = nur die eigene Adresse (/32), ganzes LAN z. B. 192.168.1.0/24. Mit /32 erreichen Geräte im VPN die NAS-Dienste unter ihren normalen Namen (AdGuard antwortet mit der LAN-Adresse), aber nicht den Rest des Heimnetzes. (nur mit `apps.tailscale`) |
| `network_tailscale_exit_node` | bool | `false` | erweitert | NAS als Tailscale-Exit-Node anbieten (danach in der Admin-Konsole freigeben) Freigeben unter Machines → &lt;hostname> → Edit route settings → Use as exit node. Wer das NAS als Exit-Node nutzt, erreicht darüber auch das übrige Heimnetz, solange die Tailscale-ACL das nicht einschränkt. (nur mit `apps.tailscale`) |
| `tailscale_authkey` | text | geheim | erweitert | Auth-Key für Tailscale statt Anmeldelink (nur für die erste Anmeldung) (nur mit `apps.tailscale`) |

## Apps

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `apps.adguard` | bool | `true` | basis | AdGuard Home: DNS und Werbeblocker fürs Heimnetz |
| `apps.tailscale` | bool | `true` | basis | Tailscale: Fernzugriff ohne Portfreigabe |
| `apps.wireguard` | bool | `false` | fest | WireGuard (nicht umgesetzt, D12) |
| `apps.uptime_kuma` | bool | `false` | basis | Uptime Kuma: Erreichbarkeit der Dienste |
| `apps.emby` | bool | `true` | basis | Emby: Media-Server |
| `apps.recommendarr` | bool | `true` | basis | Recommendarr (eigene App) |
| `apps.ps2gamemanager` | bool | `true` | basis | PS2GameManager (eigene App) |

## Medien

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `emby_dlna_renderers` | liste (ip) | `[]` | erweitert | DLNA-Abspielgeräte (z. B. Sonos) für Emby „Wiedergabe auf“, feste IPs (nur mit `apps.emby`) |
| `recyclarr_eigene_config` | bool | `false` | erweitert | Eigene recyclarr.yml im appdata-Ordner statt der TRaSH-Vorlage. Ansible schreibt die Vorlage dann nicht mehr darüber (docs/BETRIEB.md, Indexer) |
| `stacks_recyclarr_upgrade_until_score` | zahl | `13500` | erweitert | Upgrades nur, bis ein Release diese Custom-Format-Punktzahl erreicht (13500 = gutes German DL) DL 11000 + 1080p 700 + WEB-Stufe ab 1800. Die TRaSH-Vorlage ersetzte sonst vorhandene WEB-Releases durch viel größere Bluray-Encodes (doppelter Download). |
| `stacks_recyclarr_groessen` | objekt (liste) | siehe Schema | erweitert | Größengrenzen in MB pro Minute Laufzeit, je App eine Liste (60 MB/min = 3,6 GB pro Stunde) Die TRaSH-Vorlage hat kein Maximum (Bluray-Encodes mit ~150 MB/min) und lehnte kleine x265-Encodes als zu klein ab. Eine App hier angeben ersetzt nur deren Liste. |

## Benachrichtigungen

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `ntfy_default_access` | `read-write` \| `write-only` | `read-write` | erweitert | ntfy ohne Anmeldung: read-write = jeder im Netz liest und sendet; write-only = lesen nur mit ntfy-Benutzer |
| `ntfy_ios_push` | bool | `true` | erweitert | Weckruf über ntfy.sh (nur für die iPhone-App nötig; ohne Inhalt, aber mit Zeitpunkt) |

## Backup

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `backup.repository` | text | `''` | basis | restic-Ziel, z. B. /mnt/backup/aunserver, sftp:user@rechner:/pfad, s3:…, b2:…; leer = kein Backup |
| `backup.disk_label` | text | `''` | basis | Label einer USB-Platte, die unter /mnt/backup eingehängt wird (z. B. AUNBACKUP) |
| `backup.env` | objekt (text) | `{}` | erweitert | Zusätzliche Umgebungsvariablen für restic (z. B. B2_ACCOUNT_ID) |
| `backup.schedule` | text | `'*-*-* 03:30'` | erweitert | Zeitpunkt als systemd-OnCalendar |
| `backup.keep.daily` | zahl | `7` | erweitert | Tägliche Sicherungen |
| `backup.keep.weekly` | zahl | `4` | erweitert | Wöchentliche Sicherungen |
| `backup.keep.monthly` | zahl | `6` | erweitert | Monatliche Sicherungen |

## Freigaben

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `samba_password` | text | geheim | basis | Samba-Passwort des Admins (wirkt bisher nur beim ersten Lauf, D23) |
| `samba_legacy.enabled` | bool | `false` | basis | SMB1-Freigabe für die PS2 (Open PS2 Loader) |
| `samba_legacy.port` | zahl | `1445` | erweitert | Port der SMB1-Instanz (nur mit `samba_legacy.enabled`) |
| `samba_legacy.allowed_clients` | liste (ip) | `[]` | erweitert | Nur diese IPs (z. B. die PS2); sie erreichen die Freigabe dann auch über Port 445 (nur mit `samba_legacy.enabled`) |
| `samba_legacy.shares` | liste (objekt) | `[{name: PS2SMB, path: games/ps2}]` | erweitert | Freigaben der SMB1-Instanz (name, path relativ zur Datenplatte) (nur mit `samba_legacy.enabled`) |
| `samba_legacy_password` | text | geheim | basis | Passwort des Kontos ps2 (SMB1 überträgt es schwach geschützt, kein wichtiges Passwort) (nur mit `samba_legacy.enabled`) |

## Speicher

| Einstellung | Typ | Standard | Stufe | Bedeutung |
|---|---|---|---|---|
| `single_disk` | bool | `false` | fest | Keine eigene Datenplatte, die Daten liegen auf der Systemplatte (setzt das Setup) |
