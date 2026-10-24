# Beispiel: eigene Qualitätsprofile (deutsch, klein, x265)

Profile eines Nutzers, auf dessen NAS live per API angelegt und mit echten Interactive Searches
geprüft (2026-10-23, Sonarr 4.0.20, Radarr 6.4.4, Indexer TM und HoU). Die Recyclarr-Fassung hier
ist daraus erzeugt und **noch nicht mit `recyclarr sync` getestet**.

Nutzung: `recyclarr_eigene_config: true` in `/etc/aunserver/config.yml`, dann `recyclarr.yml`
(die API-Schlüssel kommen per `!secret` aus der `secrets.yml`, die das Setup schreibt), `settings.yml`
und `custom-formats/` nach `/srv/appdata/recyclarr/` kopieren
und `docker exec recyclarr recyclarr sync --preview` prüfen.

| Profil | App | Qualitäten | Min-Score | Kern |
|---|---|---|---|---|
| Standard | Sonarr + Radarr | 720p + 1080p (eine Gruppe) | 0 | x265 +5000, kleine Größe bis +3000 |
| Staffelpaket High | Sonarr | wie Standard | 0 | nur Staffelpakete (Release Type) |
| Staffelpaket Low | Sonarr | SD, 720p, 1080p nur x265 | 0 | Staffel bis 6 GB +3000, 6–16 GB +1500, über 20 GB gesperrt |
| Low | Sonarr + Radarr | SD + 720p | 0 | Größe vor Auflösung (alte Serien, DVD-Rips) |
| Fun Release | Sonarr + Radarr | 720p + 1080p | 50000 | nur Release-Gruppe FuN (+50000) |
| Nur Englisch | Sonarr + Radarr | wie Standard | 0 | Englisch Pflicht statt Deutsch |

Gemeinsam: Upgrades aus; ohne deutschen Ton −100000 (außer "Nur Englisch"); Originalton Englisch +1000;
HDR −5000; gesperrt (−100000): AV1, Dolby Vision ohne HDR, Remux, Disc-Images, CAM/TS/Screener, 3D,
Hardsubs, LD/MD, Upscales, Spam (VOSTFR, GreeN.poste). 4K und Remux sind als Qualität nicht erlaubt
(Abspielgeräte Raspberry Pi 4/5 ohne AV1, Emby ohne GPU im Container).
Größen global (MB/min min/bevorzugt/max): SD 2/10/20, 720p 3/15/60, 1080p 4/25/110.

Erkenntnisse aus echten deutschen Release-Namen (4.904 Releases):
- `DL` trifft naiv auch `WEB-DL`; Muster `(?<!web[-. _])(?<!web)\bDL\b`.
- `MULTi` allein ist oft Französisch, zählt nicht als deutsch; die Spracherkennung der Apps
  (German) ist zuverlässig und erkennt auch `GER`, `[DE-EN-TR]`, `Multi-Audio`.
- FuN steht immer als `-FuN` am Ende, teils `-FuN-20230306123335`; Muster `-FuN\b`
  (trifft nicht `FUNXDTV`, `HaVeFuN`).
- Alle erlaubten Qualitäten in **einer** Gruppe, sonst schlägt die Qualitätsreihenfolge die Punkte.
- Mehrere Bedingungen gleicher Art sind ODER, verschiedener Art UND (wichtig für Größe + Release Type).
