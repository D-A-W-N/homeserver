"""aunserver-config – Konfiguration prüfen, zusammenführen und Vorlagen erzeugen (D21).

Das Schema (config/schema.yml) beschreibt jede einstellbare Variable. /etc/aunserver/config.yml
braucht nur Abweichungen vom Standard: Vor jedem Ansible-Lauf wird sie geprüft und mit den
Standardwerten zusammengeführt. Blöcke wie apps oder backup werden dabei Schlüssel für
Schlüssel ergänzt; ein bloßes `-e @config.yml` würde sie als Ganzes ersetzen.

Ändern (set, unset, import, revert) schreibt die Datei mit ruamel.yaml, damit eigene Kommentare
erhalten bleiben, legt jede Fassung im Verlauf ab und hält die Sperre, die auch Setup und Update
nehmen. Passwörter und Schlüssel liegen als Dateien in /etc/aunserver/secrets/ (D23).

Nur Standardbibliothek, PyYAML (kommt mit dem Debian-Paket ansible) und zum Schreiben
python3-ruamel.yaml (ohne gehen Kommentare verloren).
"""

import argparse
import contextlib
import copy
import datetime
import difflib
import fcntl
import getpass
import io
import ipaddress
import json
import os
import re
import subprocess
import sys
import tempfile

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "config", "schema.yml")
# Für Tests umlenkbar: AUNSERVER_ETC, AUNSERVER_STATE, AUNSERVER_LOCK
ETC = os.environ.get("AUNSERVER_ETC", "/etc/aunserver")
CONFIG = os.path.join(ETC, "config.yml")
SECRETS_DIR = os.path.join(ETC, "secrets")
HISTORY_DIR = os.path.join(ETC, "verlauf")
APPLIED = os.path.join(os.environ.get("AUNSERVER_STATE", "/var/lib/aunserver"), "config.angewendet.yml")
LOCK = os.environ.get("AUNSERVER_LOCK", "/run/lock/aunserver.lock")
HISTORY_KEEP = 30
CONFIG_VERSION = 2
GROUP_VARS_DIR = os.path.join(REPO, "ansible", "group_vars", "all")
GENERATED = {
    "group_vars": os.path.join(GROUP_VARS_DIR, "einstellungen.yml"),
    "example": os.path.join(REPO, "config.example.yml"),
    "docs": os.path.join(REPO, "docs", "KONFIGURATION.md"),
}
TYPES = {"text", "bool", "zahl", "auswahl", "liste", "objekt"}
ENTRY_TYPES = {"text", "zahl", "ip", "netz", "objekt", "liste"}
FORMATS = {"ip", "netz", "zeit", "hostname", "zeitzone"}
STUFEN = {"basis", "erweitert", "fest"}
MASK = "********"


class SchemaError(Exception):
    pass


# --- Schema ------------------------------------------------------------------------------------

class Schema:
    def __init__(self, path=SCHEMA):
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        self.version = raw["version"]
        self.bereiche = raw["bereiche"]
        self.gruppen = raw.get("gruppen", {})
        self.profile = raw.get("profile", {})
        self.leaves = raw["einstellungen"]  # Pfad mit Punkten -> Beschreibung, in Schema-Reihenfolge
        self.prefixes = set()
        for path in self.leaves:
            parts = path.split(".")
            for i in range(1, len(parts)):
                self.prefixes.add(".".join(parts[:i]))
        self._check()

    def _check(self):
        problems = []
        for path, spec in self.leaves.items():
            if path in self.prefixes:
                problems.append(f"{path}: ist zugleich Einstellung und Gruppe")
            if spec.get("typ") not in TYPES:
                problems.append(f"{path}: unbekannter typ {spec.get('typ')!r}")
            if spec.get("bereich") not in self.bereiche:
                problems.append(f"{path}: unbekannter bereich {spec.get('bereich')!r}")
            if spec.get("stufe") not in STUFEN:
                problems.append(f"{path}: unbekannte stufe {spec.get('stufe')!r}")
            if not spec.get("text"):
                problems.append(f"{path}: text fehlt")
            if "format" in spec and spec["format"] not in FORMATS:
                problems.append(f"{path}: unbekanntes format {spec['format']!r}")
            if spec.get("typ") in ("liste", "objekt") and spec.get("eintrag", "text") not in ENTRY_TYPES:
                problems.append(f"{path}: unbekannter eintrag {spec.get('eintrag')!r}")
            if spec.get("typ") == "auswahl" and not spec.get("werte"):
                problems.append(f"{path}: auswahl ohne werte")
            dep = spec.get("braucht")
            if dep and self.leaves.get(dep, {}).get("typ") != "bool":
                problems.append(f"{path}: braucht {dep!r}, das ist keine bool-Einstellung")
            if "standard" in spec:
                for err in check_value(spec, spec["standard"], path):
                    problems.append(f"Standardwert ungültig: {err}")
        for group in self.gruppen:
            if group not in self.prefixes:
                problems.append(f"gruppen: {group} ist keine Gruppe von Einstellungen")
        for name, profil in self.profile.items():
            for path, value in profil.get("werte", {}).items():
                if path not in self.leaves:
                    problems.append(f"profile.{name}: unbekannte Einstellung {path}")
                else:
                    problems += [f"profile.{name}: {e}" for e in check_value(self.leaves[path], value, path)]
        if problems:
            raise SchemaError("\n".join(problems))

    def roots(self):
        """Oberste Schlüssel in Schema-Reihenfolge."""
        seen = []
        for path in self.leaves:
            root = path.split(".")[0]
            if root not in seen:
                seen.append(root)
        return seen

    def defaults(self):
        tree = {}
        for path, spec in self.leaves.items():
            if "standard" in spec:
                set_path(tree, path, copy.deepcopy(spec["standard"]))
        return tree

    def tree(self):
        """Verschachtelte Ordnung: Gruppe -> {Kind: Untergruppe oder None (Einstellung)}."""
        tree = {}
        for path in self.leaves:
            node = tree
            parts = path.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = None
        return tree

    def as_json(self):
        return {"version": self.version, "bereiche": self.bereiche, "gruppen": self.gruppen,
                "profile": self.profile, "einstellungen": self.leaves}


def set_path(tree, path, value):
    parts = path.split(".")
    for part in parts[:-1]:
        tree = tree.setdefault(part, {})
    tree[parts[-1]] = value


def get_path(tree, path, default=None):
    for part in path.split("."):
        if not isinstance(tree, dict) or part not in tree:
            return default
        tree = tree[part]
    return tree


# --- Werte prüfen ------------------------------------------------------------------------------

HOSTNAME = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
ZEIT = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")


def type_name(value):
    return {bool: "Ja/Nein", int: "Zahl", float: "Kommazahl", str: "Text", list: "Liste",
            dict: "Block", type(None): "leer"}.get(type(value), type(value).__name__)


def check_format(fmt, value, path):
    if fmt == "ip":
        try:
            ipaddress.ip_address(value)
        except ValueError:
            return [f"{path}: {value!r} ist keine IP-Adresse"]
    elif fmt == "netz":
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError:
            return [f"{path}: {value!r} ist kein Netz (z. B. 192.168.1.0/24)"]
    elif fmt == "zeit":
        if not ZEIT.match(value):
            return [f"{path}: {value!r} ist keine Uhrzeit (HH:MM)"]
    elif fmt == "hostname":
        if not HOSTNAME.match(value):
            return [f"{path}: {value!r} ist kein gültiger Name (Kleinbuchstaben, Ziffern, Bindestrich)"]
    elif fmt == "zeitzone":
        zoneinfo = "/usr/share/zoneinfo"
        if os.path.isdir(zoneinfo) and not os.path.isfile(os.path.join(zoneinfo, value)):
            return [f"{path}: unbekannte Zeitzone {value!r}"]
    return []


def check_entry(entry, value, path):
    if entry == "zahl":
        return [] if isinstance(value, int) and not isinstance(value, bool) else [
            f"{path}: erwartet Zahl, gefunden {type_name(value)}"]
    if entry == "objekt":
        return [] if isinstance(value, dict) else [f"{path}: erwartet Block, gefunden {type_name(value)}"]
    if entry == "liste":
        return [] if isinstance(value, list) else [f"{path}: erwartet Liste, gefunden {type_name(value)}"]
    if not isinstance(value, str):
        return [f"{path}: erwartet Text, gefunden {type_name(value)}"]
    if entry in ("ip", "netz"):
        return check_format(entry, value, path)
    return []


def check_value(spec, value, path):
    typ = spec["typ"]
    if value is None:
        return [f"{path}: ist leer (Wert fehlt nach dem Doppelpunkt)"]
    if typ == "bool":
        return [] if isinstance(value, bool) else [f"{path}: erwartet true oder false, gefunden {value!r}"]
    if typ == "zahl":
        if not isinstance(value, int) or isinstance(value, bool):
            return [f"{path}: erwartet Zahl, gefunden {type_name(value)}"]
        if "min" in spec and value < spec["min"]:
            return [f"{path}: {value} ist kleiner als {spec['min']}"]
        if "max" in spec and value > spec["max"]:
            return [f"{path}: {value} ist größer als {spec['max']}"]
        return []
    if typ == "auswahl":
        return [] if value in spec["werte"] else [
            f"{path}: {value!r} ist nicht erlaubt, möglich: {', '.join(map(str, spec['werte']))}"]
    if typ == "text":
        if not isinstance(value, str):
            return [f"{path}: erwartet Text, gefunden {type_name(value)} (Text in Anführungszeichen setzen)"]
        if "format" in spec:
            return check_format(spec["format"], value, path)
        if "muster" in spec and not re.match(spec["muster"], value):
            return [f"{path}: {value!r} hat nicht die erwartete Form"]
        return []
    entry = spec.get("eintrag", "text")
    if typ == "liste":
        if not isinstance(value, list):
            return [f"{path}: erwartet Liste, gefunden {type_name(value)}"]
        return [e for i, v in enumerate(value) for e in check_entry(entry, v, f"{path}[{i}]")]
    if typ == "objekt":
        if not isinstance(value, dict):
            return [f"{path}: erwartet Block, gefunden {type_name(value)}"]
        return [e for k, v in value.items() for e in check_entry(entry, v, f"{path}.{k}")]
    return []


# --- Interne Variablen (group_vars, Rollen-Defaults) ---------------------------------------------

def internal_keys():
    """Oberste Variablen aus den übrigen group_vars und den Rollen-Defaults."""
    files = []
    if os.path.isdir(GROUP_VARS_DIR):
        files += [os.path.join(GROUP_VARS_DIR, f) for f in sorted(os.listdir(GROUP_VARS_DIR))
                  if f.endswith(".yml") and os.path.join(GROUP_VARS_DIR, f) != GENERATED["group_vars"]]
    roles = os.path.join(REPO, "ansible", "roles")
    if os.path.isdir(roles):
        files += [os.path.join(roles, r, "defaults", "main.yml") for r in sorted(os.listdir(roles))]
    keys = {}
    for path in files:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                for key in (yaml.safe_load(f) or {}):
                    keys.setdefault(key, os.path.relpath(path, REPO))
    return keys


# --- Prüfen und zusammenführen ------------------------------------------------------------------

class Result:
    def __init__(self):
        self.errors = []
        self.warnings = []


def suggest(name, candidates):
    match = difflib.get_close_matches(name, candidates, n=1, cutoff=0.75)
    return f" – gemeint: {match[0]}?" if match else ""


def validate(schema, config, internal=None):
    res = Result()
    if internal is None:
        internal = internal_keys()
    if config is None:
        return res
    if not isinstance(config, dict):
        res.errors.append("Die Datei enthält keine Einstellungen (erwartet: schlüssel: wert)")
        return res
    names = list(schema.leaves) + sorted(schema.prefixes) + list(internal)

    def walk(node, prefix):
        for key, value in node.items():
            path = f"{prefix}{key}"
            if path in schema.leaves:
                res.errors += check_value(schema.leaves[path], value, path)
            elif path in schema.prefixes:
                if isinstance(value, dict):
                    walk(value, path + ".")
                else:
                    res.errors.append(f"{path}: erwartet einen Block mit Einstellungen, gefunden {type_name(value)}")
            elif not prefix and key in internal:
                res.warnings.append(f"{key}: interner Wert aus {internal[key]}, wird ungeprüft übernommen")
            else:
                res.warnings.append(f"{path}: unbekannte Einstellung, wird ignoriert{suggest(path, names)}")

    walk(config, "")
    for path, spec in schema.leaves.items():
        if spec.get("geheim") and get_path(config, path) is not None:
            res.warnings.append(f"{path}: steht in der config.yml, das Setup verschiebt es nach {SECRETS_DIR}/ (D23)")
    if not res.errors:
        eff = merge(schema, config)
        for path, spec in schema.leaves.items():
            dep = spec.get("braucht")
            if not dep or get_path(eff, dep) is not False:
                continue
            # Schalter: nur wenn er (auch per Standard) an ist; sonst nur ausdrücklich gesetzte Werte
            if spec["typ"] == "bool":
                ohne_wirkung = get_path(eff, path) is True
            else:
                ohne_wirkung = get_path(config, path) is not None and get_path(config, path) != spec.get("standard")
            if ohne_wirkung:
                res.warnings.append(f"{path}: wirkt nur mit {dep}: true")
    return res


def merge(schema, config):
    """Standardwerte, darüber die eigene Konfiguration (Blöcke Schlüssel für Schlüssel)."""
    result = schema.defaults()

    def walk(target, node, prefix):
        for key, value in node.items():
            path = f"{prefix}{key}"
            spec = schema.leaves.get(path)
            if spec is not None:
                if spec["typ"] == "objekt" and not spec.get("ersetzen") \
                        and isinstance(value, dict) and isinstance(target.get(key), dict):
                    target[key] = {**target[key], **copy.deepcopy(value)}
                else:
                    target[key] = copy.deepcopy(value)
            elif path in schema.prefixes and isinstance(value, dict):
                walk(target.setdefault(key, {}), value, path + ".")
            elif not prefix:
                # unbekannte oder interne Variable: unverändert durchreichen
                target[key] = copy.deepcopy(value)

    walk(result, config or {}, "")
    return result


def mask_secrets(schema, config):
    masked = copy.deepcopy(config)
    for path, spec in schema.leaves.items():
        if spec.get("geheim") and get_path(masked, path) not in (None, ""):
            set_path(masked, path, MASK)
    return masked


# --- Ausgabe ------------------------------------------------------------------------------------

def flow(value):
    """Ein Wert als einzeilige YAML-Flow-Darstellung."""
    if isinstance(value, str) and ":" in value:
        # z. B. "04:00": eindeutig als Text, auch für YAML-1.1-Leser (Sexagesimalzahlen)
        return "'" + value.replace("'", "''") + "'"
    out = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10000, sort_keys=False)
    out = out.strip()
    if out.endswith("\n..."):
        out = out[:-4].strip()
    elif out.endswith("..."):
        out = out[:-3].strip()
    return out


def emit_value(value, indent):
    """Zeilen für `schlüssel: wert` ab der Einrückung; Listen und Blöcke eine Ebene tiefer."""
    pad = "  " * (indent + 1)
    if isinstance(value, list) and value and any(isinstance(v, (dict, list)) for v in value):
        return "", [f"{pad}- {flow(v)}" for v in value]
    if isinstance(value, dict) and value:
        lines = []
        for k, v in value.items():
            first, rest = emit_value(v, indent + 1)
            lines.append(f"{pad}{flow(k)}:{(' ' + first) if first else ''}")
            lines += rest
        return "", lines
    return flow(value), []


def emit_tree(schema, tree, values, prefix, indent, example):
    lines = []
    pad = "  " * indent
    for key, sub in tree.items():
        path = f"{prefix}{key}"
        if sub is None:
            spec = schema.leaves[path]
            if example and spec.get("beispiel") is False:
                continue
            if "standard" not in spec:
                if example:
                    lines.append(f"{pad}# {spec['text']}")
                    lines.append(f"{pad}# {key}: ''")
                continue
            lines.append(f"{pad}# {spec['text']}")
            first, rest = emit_value(get_path(values, path), indent)
            lines.append(f"{pad}{key}:{(' ' + first) if first else ''}")
            lines += rest
        else:
            inner = emit_tree(schema, sub, values, path + ".", indent + 1, example)
            if not inner:
                continue
            if path in schema.gruppen:
                lines.append(f"{pad}# {schema.gruppen[path]}")
            lines.append(f"{pad}{key}:")
            lines += inner
        if indent == 0:
            lines.append("")
    return lines


def render_group_vars(schema):
    head = [
        "---",
        "# ERZEUGT aus config/schema.yml (bin/aunserver-config generate), nicht von Hand ändern.",
        "# Standardwerte aller Einstellungen; /etc/aunserver/config.yml überschreibt sie (docs/KONFIGURATION.md).",
        "",
    ]
    return "\n".join(head + emit_tree(schema, schema.tree(), schema.defaults(), "", 0, False)).rstrip() + "\n"


def render_example(schema):
    head = [
        "---",
        "# Beispiel für /etc/aunserver/config.yml (pro Maschine, nicht einchecken).",
        "# ERZEUGT aus config/schema.yml (bin/aunserver-config generate), nicht von Hand ändern.",
        "# Es reicht, die Werte einzutragen, die vom Standard abweichen; alle Einstellungen mit",
        "# Erklärung stehen in docs/KONFIGURATION.md. Prüfen: sudo aunserver-config validate",
        "",
    ]
    return "\n".join(head + emit_tree(schema, schema.tree(), schema.defaults(), "", 0, True)).rstrip() + "\n"


def md_cell(text):
    return str(text).replace("|", "\\|").replace("<", "&lt;").replace("\n", " ")


def render_docs(schema):
    out = [
        "# Konfiguration",
        "",
        "<!-- ERZEUGT aus config/schema.yml (bin/aunserver-config generate), nicht von Hand ändern. -->",
        "",
        "Alle Einstellungen des NAS stehen in `/etc/aunserver/config.yml`. Dort reicht, was vom Standard",
        "abweicht: Vor jedem Lauf prüft `aunserver-config` die Datei und ergänzt fehlende Werte, auch",
        "innerhalb von Blöcken (`apps: {emby: false}` lässt die übrigen Apps auf ihrem Standard).",
        "Die Beschreibung steht in [config/schema.yml](../config/schema.yml).",
        "",
        "```bash",
        "sudo aunserver-config set apps.emby false     # ändern (prüft den Wert, Kommentare bleiben)",
        "sudo aunserver-config unset apps.emby         # zurück auf den Standard",
        "sudo aunserver-config diff                    # was noch nicht übernommen ist",
        "sudo aunserver-setup                          # übernehmen",
        "sudo aunserver-config history                 # frühere Fassungen; zurück: revert <Fassung>",
        "sudo aunserver-config passwd web              # Passwort ändern (samba, ps2, web)",
        "```",
        "",
        "Wer die Datei lieber selbst bearbeitet (`sudo nano /etc/aunserver/config.yml`), prüft sie mit",
        "`sudo aunserver-config validate`; das Setup prüft sie vor jedem Lauf auch.",
        "",
        "Stufen: **basis** fragt das Setup ab, **erweitert** nur bei Bedarf, **fest** setzt das Setup",
        "(nicht von Hand ändern). **Geheime** Werte (Passwörter, Schlüssel) stehen nicht in der",
        "config.yml, sondern als Dateien in `/etc/aunserver/secrets/` (D23); ältere Dateien stellt",
        "das Setup selbst um (`config_version: 2`).",
        "",
    ]
    if schema.profile:
        out += ["## Profile", "", "Vorauswahl der Apps bei der Ersteinrichtung (Setup und Assistent); danach gelten die einzelnen Werte.", ""]
        out += [f"- **{name}**: {md_cell(p['text'])} ({', '.join(f'`{k}: {flow(v)}`' for k, v in p['werte'].items())})"
                for name, p in schema.profile.items()]
        out.append("")
    for bereich, title in schema.bereiche.items():
        rows = [(p, s) for p, s in schema.leaves.items() if s["bereich"] == bereich]
        if not rows:
            continue
        out += [f"## {title}", "", "| Einstellung | Typ | Standard | Stufe | Bedeutung |", "|---|---|---|---|---|"]
        for path, spec in rows:
            typ = spec["typ"]
            if typ == "auswahl":
                typ = " \\| ".join(f"`{w}`" for w in spec["werte"])
            elif typ in ("liste", "objekt"):
                typ = f"{typ} ({spec.get('eintrag', 'text')})"
            elif "format" in spec:
                typ = f"text ({spec['format']})"
            if spec.get("geheim"):
                default = "geheim"
            elif "standard" not in spec:
                default = "–"
            else:
                default = flow(spec["standard"])
                default = "siehe Schema" if len(default) > 50 else f"`{md_cell(default)}`"
            text = md_cell(spec["text"])
            if spec.get("hinweis"):
                text += ("" if text.endswith((".", ")")) else ".") + " " + md_cell(spec["hinweis"])
            if spec.get("braucht"):
                text += f" (nur mit `{spec['braucht']}`)"
            out.append(f"| `{path}` | {typ} | {default} | {spec['stufe']} | {text} |")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


def schema_overlaps(schema):
    """Einstellungen aus dem Schema, die zusätzlich in group_vars oder Rollen-Defaults stehen."""
    internal = internal_keys()
    return [f"{root}: steht im Schema und in {internal[root]}" for root in schema.roots() if root in internal]


# --- Dateien ------------------------------------------------------------------------------------

def load_config(path):
    try:
        with open(path, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        die(f"{path} fehlt")
    except yaml.YAMLError as e:
        die(f"{path} ist kein gültiges YAML: {e}")


def write_atomic(path, text, mode=0o600):
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".aunserver-config-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def dump(data):
    return "---\n" + yaml.safe_dump(data, allow_unicode=True, sort_keys=False, default_flow_style=False, width=160)


def die(msg):
    print(f"Fehler: {msg}", file=sys.stderr)
    sys.exit(1)


def report(res, path, quiet=False):
    for w in res.warnings:
        print(f"Warnung: {w}", file=sys.stderr)
    for e in res.errors:
        print(f"Fehler: {e}", file=sys.stderr)
    if res.errors:
        print(f"{path}: {len(res.errors)} Fehler, bitte korrigieren.", file=sys.stderr)
    elif not quiet:
        print(f"{path}: in Ordnung" + (f" ({len(res.warnings)} Warnungen)" if res.warnings else ""))



# --- Passwörter und Schlüssel (D23) ---------------------------------------------------------------

def secret_file(path):
    return os.path.join(SECRETS_DIR, path.replace(".", "_"))


def read_secrets(schema):
    found = {}
    for path, spec in schema.leaves.items():
        f = secret_file(path)
        if spec.get("geheim") and os.path.isfile(f):
            with open(f, encoding="utf-8") as fh:
                found[path] = fh.read().rstrip("\n")
    return found


def write_secret(path, value):
    os.makedirs(SECRETS_DIR, mode=0o700, exist_ok=True)
    write_atomic(secret_file(path), f"{value}\n", 0o600)


def remove_secret(path):
    with contextlib.suppress(FileNotFoundError):
        os.unlink(secret_file(path))


def strip_secrets(schema, config):
    stripped = copy.deepcopy(config)
    for path, spec in schema.leaves.items():
        if spec.get("geheim"):
            del_path(stripped, path)
    return stripped


# --- Schreiben, Sperre, Verlauf ---------------------------------------------------------------------

def del_path(tree, path):
    """Wert entfernen, leer gewordene Blöcke darüber auch."""
    parts = path.split(".")
    nodes = [tree]
    for part in parts[:-1]:
        if not isinstance(nodes[-1], dict) or part not in nodes[-1]:
            return False
        nodes.append(nodes[-1][part])
    if not isinstance(nodes[-1], dict) or parts[-1] not in nodes[-1]:
        return False
    del nodes[-1][parts[-1]]
    for i in range(len(parts) - 1, 0, -1):
        if nodes[i] == {}:
            del nodes[i - 1][parts[i - 1]]
    return True


def rt_yaml():
    try:
        from ruamel.yaml import YAML
    except ImportError:
        return None
    y = YAML()
    y.preserve_quotes = True
    y.indent(mapping=2, sequence=4, offset=2)
    y.width = 160
    y.explicit_start = True
    return y


def load_for_edit(path):
    """Konfiguration zum Ändern laden (mit Kommentaren, wenn ruamel.yaml da ist)."""
    if not os.path.exists(path):
        return {}
    y = rt_yaml()
    try:
        with open(path, encoding="utf-8") as f:
            data = y.load(f) if y else yaml.safe_load(f)
    except Exception as e:  # noqa: BLE001 – beide Parser haben eigene Fehlerklassen
        die(f"{path} ist kein gültiges YAML: {e}")
    if data is None:
        return {}
    if not isinstance(data, dict):
        die(f"{path} enthält keine Einstellungen")
    return data


def to_plain(obj):
    """ruamel-Objekte (CommentedMap, ScalarInt …) in einfache Python-Werte."""
    if isinstance(obj, dict):
        return {str(k): to_plain(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_plain(v) for v in obj]
    if isinstance(obj, bool) or obj is None:
        return obj
    for t in (int, float, str):
        if isinstance(obj, t):
            return t(obj)
    return obj


def dump_for_edit(data):
    y = rt_yaml()
    if y is None:
        print("Hinweis: python3-ruamel.yaml fehlt, Kommentare in der config.yml gehen beim Schreiben verloren.",
              file=sys.stderr)
        return dump(to_plain(data))
    buf = io.StringIO()
    y.dump(data, buf)
    return buf.getvalue()


@contextlib.contextmanager
def locked():
    """Dieselbe Sperre wie aunserver-setup und aunserver-update (die sie an uns weitergeben)."""
    if os.environ.get("AUNSERVER_LOCK_HELD") == "1":
        yield
        return
    os.makedirs(os.path.dirname(LOCK), exist_ok=True)
    fd = os.open(LOCK, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            die("Setup, Update oder eine andere Änderung läuft gerade; danach erneut versuchen.")
        yield
    finally:
        os.close(fd)


def history_entries():
    if not os.path.isdir(HISTORY_DIR):
        return []
    return sorted(f[:-4] for f in os.listdir(HISTORY_DIR) if f.endswith(".yml"))


def history_read(entry):
    path = os.path.join(HISTORY_DIR, entry + ".yml")
    if not os.path.isfile(path):
        die(f"Keine Fassung {entry} im Verlauf (aunserver-config history)")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    grund = ""
    first = text.splitlines()[0] if text else ""
    if first.startswith("# Grund: "):
        grund = first[len("# Grund: "):]
    return grund, text, yaml.safe_load(text) or {}


def history_add(schema, text_without_secrets, grund):
    os.makedirs(HISTORY_DIR, mode=0o700, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    name, n = stamp, 1
    while os.path.exists(os.path.join(HISTORY_DIR, name + ".yml")):
        n += 1
        name = f"{stamp}-{n}"
    grund = grund.replace("\n", " ")
    write_atomic(os.path.join(HISTORY_DIR, name + ".yml"), f"# Grund: {grund}\n{text_without_secrets}", 0o600)
    for old in history_entries()[:-HISTORY_KEEP]:
        os.unlink(os.path.join(HISTORY_DIR, old + ".yml"))
    return name


def save_config(schema, data, grund, secrets=None, path=None):
    """Prüfen, Passwörter nach secrets/, Fassung in den Verlauf, Datei ersetzen."""
    path = path or CONFIG
    secrets = dict(secrets or {})
    for p, spec in schema.leaves.items():
        if spec.get("geheim"):
            value = get_path(data, p)
            if value is not None:
                secrets[p] = value
                del_path(data, p)
    res = validate(schema, to_plain(data))
    for w in res.warnings:
        print(f"Warnung: {w}", file=sys.stderr)
    if res.errors:
        for e in res.errors:
            print(f"Fehler: {e}", file=sys.stderr)
        die("nichts geändert")
    for p, value in secrets.items():
        if value in (None, ""):
            remove_secret(p)
        else:
            write_secret(p, value)
    # die bisherige Fassung kommt beim ersten Mal mit in den Verlauf, ohne Passwörter
    if not history_entries() and os.path.exists(path):
        history_add(schema, dump(strip_secrets(schema, load_config(path))), "Stand vor der ersten Änderung")
    text = dump_for_edit(data)
    os.makedirs(os.path.dirname(os.path.abspath(path)), mode=0o700, exist_ok=True)
    write_atomic(path, text, 0o600)
    return history_add(schema, text, grund)


def flatten(schema, config):
    """Pfad -> Wert für alle Einstellungen des Schemas, dazu unbekannte oberste Schlüssel."""
    flat = {p: get_path(config, p) for p in schema.leaves
            if p != "config_version" and get_path(config, p) is not None}
    for key, value in (config or {}).items():
        if key not in schema.leaves and key not in schema.prefixes:
            flat[key] = value
    return flat


def changes(schema, old, new):
    a, b = flatten(schema, old), flatten(schema, new)
    out = []
    for p in list(dict.fromkeys(list(a) + list(b))):
        if a.get(p) != b.get(p):
            geheim = schema.leaves.get(p, {}).get("geheim")
            show = (lambda v: MASK if v is not None else None) if geheim else (lambda v: v)
            out.append((p, show(a.get(p)), show(b.get(p))))
    return out


def fmt_change(path, old, new):
    def f(v):
        return "(Standard)" if v is None else flow(v)
    return f"  {path}: {f(old)} → {f(new)}"


def parse_value(spec, raw):
    if spec["typ"] == "text":
        return raw
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as e:
        die(f"{raw!r} ist kein gültiger Wert: {e}")


def migrate(schema, data):
    """Alte Fassungen auf CONFIG_VERSION bringen. Gibt die Änderungen als Text zurück."""
    done = []
    version = data.get("config_version", 1)
    # D23 (ab Fassung 2): Passwörter und Schlüssel gehören nach secrets/, save_config verschiebt sie
    for p, spec in schema.leaves.items():
        if spec.get("geheim") and get_path(data, p) is not None:
            done.append(f"{p} nach secrets/ verschoben")
    if version < CONFIG_VERSION:
        if hasattr(data, "insert"):
            data.insert(0, "config_version", CONFIG_VERSION)
        else:
            data["config_version"] = CONFIG_VERSION
        done.append(f"config_version {version} → {CONFIG_VERSION}")
    return done

# --- Befehle ------------------------------------------------------------------------------------

def cmd_validate(args, schema):
    res = validate(schema, load_config(args.datei))
    report(res, args.datei)
    return 1 if res.errors else 0


def cmd_show(args, schema):
    config = load_config(args.datei) if os.path.exists(args.datei) or not args.json else {}
    if args.json:
        # für den Editor: eigene Werte, wirksame Werte, gesetzte Geheimnisse, Befunde
        res = validate(schema, config)
        eff = merge(schema, config) if not res.errors else {}
        json.dump({
            "eigene": to_plain(strip_secrets(schema, config)),
            "wirksam": strip_secrets(schema, eff),
            "geheim_gesetzt": sorted(set(read_secrets(schema)) | {
                p for p, spec in schema.leaves.items() if spec.get("geheim") and get_path(config, p) is not None}),
            "fehler": res.errors, "warnungen": res.warnings,
        }, sys.stdout, ensure_ascii=False)
        print()
        return 0
    if args.effective:
        res = validate(schema, config)
        report(res, args.datei, quiet=True)
        if res.errors:
            return 1
        config = merge(schema, config)
    print(dump(mask_secrets(schema, config)), end="")
    return 0


def cmd_effective(args, schema):
    config = load_config(args.datei)
    res = validate(schema, config)
    report(res, args.datei, quiet=True)
    if res.errors:
        return 1
    eff = merge(schema, config)
    for path, value in read_secrets(schema).items():
        if get_path(eff, path) is None:
            set_path(eff, path, value)
    text = "# Erzeugt von aunserver-config aus " + args.datei + ", secrets/ und den Standardwerten, nicht ändern.\n"
    write_atomic(args.out, text + dump(eff))
    return 0


def cmd_generate(args, schema):
    overlaps = schema_overlaps(schema)
    if overlaps:
        die("\n".join(overlaps))
    files = {
        GENERATED["group_vars"]: render_group_vars(schema),
        GENERATED["example"]: render_example(schema),
        GENERATED["docs"]: render_docs(schema),
    }
    stale = []
    for path, text in files.items():
        current = open(path, encoding="utf-8").read() if os.path.exists(path) else None
        if current == text:
            continue
        if args.check:
            stale.append(os.path.relpath(path, REPO))
        else:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            write_atomic(path, text, 0o644)
            print(f"geschrieben: {os.path.relpath(path, REPO)}")
    if stale:
        die("nicht aktuell (bin/aunserver-config generate ausführen): " + ", ".join(stale))
    return 0


def leaf_or_die(schema, key):
    if key in schema.leaves:
        return schema.leaves[key]
    if key in schema.prefixes:
        kids = [p for p in schema.leaves if p.startswith(key + ".")]
        die(f"{key} ist ein Block, bitte einzeln setzen, z. B. {kids[0]}")
    die(f"unbekannte Einstellung {key}{suggest(key, list(schema.leaves))} (docs/KONFIGURATION.md)")


def cmd_get(args, schema):
    spec = leaf_or_die(schema, args.schluessel)
    if spec.get("geheim"):
        die(f"{args.schluessel} ist geheim und wird nicht angezeigt (steht in {secret_file(args.schluessel)})")
    value = get_path(merge(schema, load_config(args.datei) if os.path.exists(args.datei) else {}), args.schluessel)
    if value is None:
        return 1
    print(value if isinstance(value, str) else flow(value))
    return 0


def cmd_set(args, schema):
    spec = leaf_or_die(schema, args.schluessel)
    value = parse_value(spec, args.wert)
    with locked():
        data = load_for_edit(args.datei)
        before = to_plain(data)
        set_path(data, args.schluessel, value)
        entry = save_config(schema, data, args.grund or f"set {args.schluessel}", path=args.datei)
    if spec.get("geheim"):
        print(f"{args.schluessel} gespeichert ({secret_file(args.schluessel)}).")
    else:
        for c in changes(schema, before, load_config(args.datei)):
            print(fmt_change(*c))
    print(f"Fassung {entry}. Übernehmen: sudo aunserver-setup")
    return 0


def cmd_unset(args, schema):
    spec = leaf_or_die(schema, args.schluessel)
    with locked():
        data = load_for_edit(args.datei)
        if spec.get("geheim"):
            remove_secret(args.schluessel)
            del_path(data, args.schluessel)
            save_config(schema, data, args.grund or f"unset {args.schluessel}", path=args.datei)
            print(f"{args.schluessel} entfernt.")
            return 0
        if not del_path(data, args.schluessel):
            print(f"{args.schluessel} steht schon auf dem Standard.")
            return 0
        entry = save_config(schema, data, args.grund or f"unset {args.schluessel}", path=args.datei)
    print(f"{args.schluessel} wieder auf dem Standard ({flow(schema.leaves[args.schluessel].get('standard'))}). "
          f"Fassung {entry}. Übernehmen: sudo aunserver-setup")
    return 0


def cmd_import(args, schema):
    """Werte aus einer Datei (- = stdin, YAML oder JSON) übernehmen, alles andere bleibt (Setup, Assistent)."""
    if args.quelle == "-":
        try:
            incoming = yaml.safe_load(sys.stdin) or {}
        except yaml.YAMLError as e:
            die(f"stdin ist kein gültiges YAML/JSON: {e}")
    else:
        incoming = load_config(args.quelle)
    res = validate(schema, incoming)
    unknown = [w for w in res.warnings if "unbekannte Einstellung" in w or "interner Wert" in w]
    if res.errors or unknown:
        report(res, args.quelle, quiet=True)
        die(f"{args.quelle}: nur bekannte Einstellungen können übernommen werden")
    with locked():
        data = load_for_edit(args.datei)
        migrate(schema, data)
        for path in flatten(schema, incoming):
            set_path(data, path, copy.deepcopy(get_path(incoming, path)))
        entry = save_config(schema, data, args.grund or f"import {os.path.basename(args.quelle)}", path=args.datei)
    print(f"Konfiguration geschrieben: {args.datei} (Fassung {entry})")
    return 0


def cmd_migrate(args, schema):
    if not os.path.exists(args.datei):
        return 0
    with locked():
        data = load_for_edit(args.datei)
        done = migrate(schema, data)
        if not done:
            return 0
        save_config(schema, data, "Migration: " + "; ".join(done), path=args.datei)
    for d in done:
        print(f"== Konfiguration: {d}")
    return 0


def cmd_diff(args, schema):
    current = merge(schema, load_config(args.datei))
    if args.standard:
        base, title = schema.defaults(), "Abweichungen vom Standard"
    elif os.path.exists(APPLIED):
        base, title = load_config(APPLIED), "Noch nicht übernommen (seit dem letzten Setup)"
    else:
        base, title = schema.defaults(), "Noch nie übernommen, Abweichungen vom Standard"
    found = changes(schema, strip_secrets(schema, base), strip_secrets(schema, current))
    if args.json:
        json.dump({"titel": title, "angewendet": os.path.exists(APPLIED),
                   "aenderungen": [{"pfad": p, "alt": a, "neu": n} for p, a, n in found]},
                  sys.stdout, ensure_ascii=False, default=str)
        print()
        return 0
    if not found:
        print("Keine Änderungen." if not args.standard else "Alles auf dem Standard.")
        return 0
    print(f"{title}:")
    for c in found:
        print(fmt_change(*c))
    return 3 if not args.standard else 0


def cmd_history(args, schema):
    entries = history_entries()
    if args.json:
        out, prev = [], {}
        for entry in entries:
            grund, _, data = history_read(entry)
            out.append({"fassung": entry, "grund": grund,
                         "aenderungen": [{"pfad": p, "alt": a, "neu": n} for p, a, n in changes(schema, prev, data)]
                         if out else []})
            prev = data
        json.dump(list(reversed(out)), sys.stdout, ensure_ascii=False, default=str)
        print()
        return 0
    if not entries:
        print("Noch keine Fassungen im Verlauf.")
        return 0
    prev = {}
    lines = []
    for entry in entries:
        grund, _, data = history_read(entry)
        diff = changes(schema, prev, data)
        prev = data
        detail = ", ".join(p for p, _, _ in diff[:4]) + (" …" if len(diff) > 4 else "")
        lines.append(f"{entry}  {grund}" + (f"  [{detail}]" if detail and len(lines) else ""))
    print("\n".join(reversed(lines)))
    print("\nZurückholen: sudo aunserver-config revert <Fassung>")
    return 0


def cmd_revert(args, schema):
    grund, text, data = history_read(args.fassung)
    with locked():
        before = load_config(args.datei) if os.path.exists(args.datei) else {}
        y = rt_yaml()
        target = y.load(text) if y else data
        entry = save_config(schema, target or {}, f"Zurück auf {args.fassung} ({grund})", path=args.datei)
    for c in changes(schema, strip_secrets(schema, before), data):
        print(fmt_change(*c))
    print(f"Fassung {args.fassung} wiederhergestellt (neu: {entry}). Übernehmen: sudo aunserver-setup")
    return 0


def cmd_edit(args, schema):
    """Mehrere Änderungen auf einmal als JSON von stdin (Editor): {"set": {}, "unset": [], "grund": ""}"""
    try:
        req = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        die(f"kein gültiges JSON: {e}")
    sets, unsets = req.get("set", {}), req.get("unset", [])
    for key in list(sets) + list(unsets):
        spec = leaf_or_die(schema, key)
        if spec["stufe"] == "fest":
            die(f"{key} setzt das Setup, nicht der Editor")
        if spec.get("geheim"):
            die(f"{key} ist geheim: aunserver-config passwd bzw. set")
    if not sets and not unsets:
        die("keine Änderungen")
    with locked():
        data = load_for_edit(args.datei)
        before = to_plain(data)
        migrate(schema, data)
        for key, value in sets.items():
            set_path(data, key, value)
        for key in unsets:
            del_path(data, key)
        entry = save_config(schema, data, req.get("grund") or "Editor", path=args.datei)
    found = changes(schema, strip_secrets(schema, before), load_config(args.datei))
    json.dump({"fassung": entry, "aenderungen": [{"pfad": p, "alt": a, "neu": n} for p, a, n in found]},
              sys.stdout, ensure_ascii=False, default=str)
    print()
    return 0


def cmd_mark_applied(args, schema):
    eff = strip_secrets(schema, merge(schema, load_config(args.datei)))
    os.makedirs(os.path.dirname(APPLIED), exist_ok=True)
    write_atomic(APPLIED, "# Zuletzt erfolgreich übernommen (aunserver-setup), ohne Passwörter\n" + dump(eff), 0o600)
    return 0


# Erlaubt sind druckbare Zeichen ohne Leerzeichen, Anführungszeichen, Backslash und $ (das Web-Passwort
# steht auch in einer Compose-Datei, dort würde $ als Variable gelesen)
PASSWORT = re.compile(r"^[!#%&()*+,\-./0-9:;<=>?@A-Z\[\]^_a-z{|}~]{8,128}$")
SAMBA_LEGACY_CONF = "/etc/samba-legacy/smb.conf"


def read_password(args, what):
    if args.stdin:
        pw = sys.stdin.readline().rstrip("\n")
    else:
        if not sys.stdin.isatty():
            die("Ohne Terminal das Passwort mit --stdin übergeben")
        pw = getpass.getpass(f"Neues Passwort für {what}: ")
        if getpass.getpass("Wiederholen: ") != pw:
            die("Die Passwörter stimmen nicht überein, nichts geändert.")
    if not PASSWORT.match(pw):
        die("Mindestens 8 Zeichen; erlaubt sind Buchstaben, Ziffern und Sonderzeichen außer "
            "Leerzeichen, Anführungszeichen, \\ und $. Nichts geändert.")
    return pw


def smbpasswd(argv, pw):
    try:
        subprocess.run(argv, input=f"{pw}\n{pw}\n", text=True, check=True, capture_output=True)
    except FileNotFoundError:
        die("smbpasswd fehlt (läuft das auf dem NAS?)")
    except subprocess.CalledProcessError as e:
        die(f"smbpasswd fehlgeschlagen: {(e.stderr or e.stdout).strip()}")


def cmd_passwd(args, schema):
    with locked():
        cfg = merge(schema, load_config(args.datei) if os.path.exists(args.datei) else {})
        if args.wofuer == "samba":
            pw = read_password(args, f"Samba ({cfg['admin_user']})")
            smbpasswd(["smbpasswd", "-s", "-a", cfg["admin_user"]], pw)
            write_secret("samba_password", pw)
            print("Samba-Passwort geändert, gilt sofort.")
        elif args.wofuer == "ps2":
            if not get_path(cfg, "samba_legacy.enabled"):
                die("Die PS2-Freigabe ist aus (samba_legacy.enabled).")
            pw = read_password(args, "die PS2-Freigabe (Konto ps2)")
            smbpasswd(["smbpasswd", "-c", SAMBA_LEGACY_CONF, "-s", "-a", "ps2"], pw)
            write_secret("samba_legacy_password", pw)
            print("Passwort für ps2 geändert, gilt sofort.")
        else:
            current = os.path.join(SECRETS_DIR, "web_password")
            if not os.path.isfile(current):
                die("Noch kein Web-Passwort (erst nach dem ersten Setup).")
            pw = read_password(args, f"die Web-Apps ({cfg['admin_user']})")
            alt = current + ".alt"
            # bei einem abgebrochenen Wechsel bleibt das ursprüngliche alte Passwort stehen
            if not os.path.exists(alt):
                with open(current, encoding="utf-8") as f:
                    write_atomic(alt, f.read(), 0o600)
            write_atomic(current, pw + "\n", 0o600)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(current + ".bcrypt")
            print("Web-Passwort gespeichert. Wirksam (Caddy, AdGuard, Beszel, Servarr-Apps, Zugangsübersicht) "
                  "nach: sudo aunserver-setup")
    return 0


def cmd_profile(args, schema):
    """Profile für aunserver-setup: je Zeile Name, Text und die damit eingeschalteten Apps
    (Tabulator getrennt); Apps, die das Profil nicht nennt, stehen auf ihrem Standard."""
    apps = [p for p, s in schema.leaves.items() if p.startswith("apps.") and s["stufe"] == "basis"]
    for name, profil in schema.profile.items():
        an = [p[5:] for p in apps if profil["werte"].get(p, schema.leaves[p]["standard"]) is True]
        print(f"{name}\t{profil['text']}\t{','.join(an) or ','}")
    return 0


def cmd_schema(args, schema):
    json.dump(schema.as_json(), sys.stdout, ensure_ascii=False, indent=1)
    print()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="aunserver-config", description="Konfiguration des NAS prüfen und zusammenführen (D21).")
    sub = p.add_subparsers(dest="befehl", required=True)
    s = sub.add_parser("validate", help="Konfiguration prüfen (Rückgabe 1 bei Fehlern)")
    s.add_argument("datei", nargs="?", default=CONFIG)
    s = sub.add_parser("show", help="Konfiguration anzeigen, Passwörter verdeckt")
    s.add_argument("datei", nargs="?", default=CONFIG)
    s.add_argument("--effective", action="store_true", help="mit allen Standardwerten, so wie Ansible sie bekommt")
    s.add_argument("--json", action="store_true", help="für den Editor: eigene und wirksame Werte, Befunde")
    s = sub.add_parser("effective", help="zusammengeführte Konfiguration für Ansible schreiben")
    s.add_argument("datei", nargs="?", default=CONFIG)
    s.add_argument("--out", required=True)
    s = sub.add_parser("generate", help="group_vars, config.example.yml und Doku aus dem Schema erzeugen")
    s.add_argument("--check", action="store_true", help="nur prüfen, ob die Dateien aktuell sind")
    sub.add_parser("schema", help="Schema als JSON (für den Editor)")
    sub.add_parser("profile", help="Profile (Vorauswahl der Apps) für das Setup")
    s = sub.add_parser("get", help="einen Wert anzeigen (mit Standard), Rückgabe 1 wenn keiner gesetzt ist")
    s.add_argument("schluessel")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("set", help="einen Wert setzen, z. B. set apps.emby false oder set lan_subnets '[192.168.1.0/24]'")
    s.add_argument("schluessel")
    s.add_argument("wert")
    s.add_argument("--grund", help="Text für den Verlauf")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("unset", help="einen Wert entfernen, dann gilt der Standard")
    s.add_argument("schluessel")
    s.add_argument("--grund")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("import", help="Werte aus einer Datei übernehmen, alle übrigen bleiben")
    s.add_argument("quelle")
    s.add_argument("--grund")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("migrate", help="ältere config.yml auf den aktuellen Stand bringen (macht das Setup selbst)")
    s.add_argument("datei", nargs="?", default=CONFIG)
    s = sub.add_parser("diff", help="was seit dem letzten Setup geändert und noch nicht übernommen ist (Rückgabe 3)")
    s.add_argument("datei", nargs="?", default=CONFIG)
    s.add_argument("--standard", action="store_true", help="stattdessen alle Abweichungen vom Standard")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("history", help="frühere Fassungen der config.yml")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("edit", help="mehrere Änderungen als JSON von stdin (für den Editor)")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("revert", help="eine frühere Fassung zurückholen")
    s.add_argument("fassung")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("passwd", help="Passwort ändern: samba und ps2 sofort, web mit dem nächsten Setup")
    s.add_argument("wofuer", choices=["samba", "ps2", "web"])
    s.add_argument("--stdin", action="store_true", help="Passwort als eine Zeile von der Standardeingabe")
    s.add_argument("--datei", default=CONFIG)
    s = sub.add_parser("mark-applied", help="Stand als übernommen merken (macht das Setup nach einem erfolgreichen Lauf)")
    s.add_argument("datei", nargs="?", default=CONFIG)
    args = p.parse_args(argv)
    try:
        schema = Schema()
    except SchemaError as e:
        die(f"Schema fehlerhaft:\n{e}")
    return {"validate": cmd_validate, "show": cmd_show, "effective": cmd_effective,
            "generate": cmd_generate, "schema": cmd_schema, "get": cmd_get, "set": cmd_set,
            "unset": cmd_unset, "import": cmd_import, "migrate": cmd_migrate, "diff": cmd_diff,
            "history": cmd_history, "revert": cmd_revert, "passwd": cmd_passwd, "edit": cmd_edit,
            "profile": cmd_profile,
            "mark-applied": cmd_mark_applied}[args.befehl](args, schema)


if __name__ == "__main__":
    sys.exit(main())
