# CLAUDE.md – Regeln für Claude-Sessions in diesem Repo

An diesem Repo arbeiten **mehrere Claude-Sessions parallel**. Diese Regeln gelten für jede Session.

## Gitflow (Pflicht)

1. **Nie direkt auf `main` committen oder pushen.** Ein Ruleset auf GitHub erzwingt das: Änderungen nur per PR, `lint`, `secrets` und `vm-test` grün, Branch auf dem Stand von `main`, nur Merge-Commits, kein Force-Push.
2. **Vor dem Start:** `git fetch`, offene PRs und Branches ansehen (`gh pr list`, `git branch -r`), damit zwei Sessions nicht dasselbe bauen. Überschneidet sich etwas, erst den Nutzer fragen.
3. **Ein Thema = ein Branch**, immer vom aktuellen `origin/main`: `git switch -c <name> origin/main`.
   Namen kurz, deutsch, kebab-case, ohne Präfix (wie bisher: `arcane-rechte`, `emby-tailscale`).
4. **Nur auf dem eigenen Branch arbeiten.** Fremde Branches nicht ändern, nie `--force` auf fremde Branches; auf dem eigenen nur `--force-with-lease`.
5. **Pull Request** mit `gh pr create` gegen `main`. Ist `main` inzwischen weiter, `origin/main` in den Branch mergen und Konflikte sauber lösen.
6. **Merge nach grüner CI** (alle Prüfungen, auch der VM-Test, und ohne neue Warnungen im Log) als Merge-Commit (`gh pr merge --merge --delete-branch`); dafür ist kein extra OK des Nutzers nötig. Renovate merged Patch/Minor selbst, Major-Updates entscheidet der Nutzer.

**Warum so streng:** `aunserver-update` auf dem echten NAS holt direkt den Stand von `main` (D20 in [docs/PLAN.md](docs/PLAN.md)). Alles, was auf `main` landet, kann auf dem Server ankommen.

## Commits und PRs

- Sprache: **Deutsch**. Betreff kurz, Form `Bereich: was sich ändert` (z. B. `Arcane: darf in /opt/stacks schreiben, keine Telemetrie`).
- Text: warum, Befund, Grenzen; Bezug auf Entscheidungen (`D20`) oder Meilensteine, wo passend.
- PR-Beschreibung: Stichpunkte, was und warum, wie geprüft.
- Doku mitziehen: [README.md](README.md), [docs/BETRIEB.md](docs/BETRIEB.md), [docs/PLAN.md](docs/PLAN.md) (Befunde, Repo-Struktur in Abschnitt 8).

## Prüfen vor dem PR

```bash
. .venv/bin/activate   # einmalig: python3.13 -m venv .venv && pip install -r requirements-dev.txt
yamllint . && (cd ansible && ansible-lint)
shellcheck bin/* dev/*.sh installer/*.sh
```

Die CI ([.github/workflows/](.github/workflows/)) prüft dasselbe plus gitleaks; bei Änderungen an `ansible/`, `stacks/`, `bin/`, `installer/`, `dev/` läuft zusätzlich der VM-Test (UEFI und BIOS, zweiter Setup-Lauf muss `changed=0` melden); der Pflicht-Check `vm-test` fasst das zusammen und ist sonst sofort grün. Idempotenz also immer mitdenken.

## Nie einchecken

Echte `config.yml`, Passwörter, Schlüssel, `.env`-Dateien (siehe [.gitignore](.gitignore)).

## Überblick

Debian-13-NAS vom USB-Stick: [installer/](installer/) baut das ISO, [bin/aunserver-setup](bin/aunserver-setup) richtet per Ansible ([ansible/](ansible/), lokal, idempotent) ein, App-Vorlagen in [stacks/](stacks/), gepinnte Images in `ansible/roles/stacks/defaults/main.yml` (Renovate). Ziele, Entscheidungen und Architektur: [docs/PLAN.md](docs/PLAN.md); Bedienung: [docs/BETRIEB.md](docs/BETRIEB.md).

## Mit dem Nutzer

Auf Deutsch, verständlich erklären, Optionen vor Entscheidungen. Nichts am echten Server oder System ändern ohne Rückfrage mit genauem Befehl.
