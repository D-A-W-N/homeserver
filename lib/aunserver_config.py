"""aunserver-config – Konfiguration prüfen, zusammenführen und Vorlagen erzeugen (D21).

Das Schema (config/schema.yml) beschreibt jede einstellbare Variable. /etc/aunserver/config.yml
braucht nur Abweichungen vom Standard: Vor jedem Ansible-Lauf wird sie geprüft und mit den
Standardwerten zusammengeführt. Blöcke wie apps oder backup werden dabei Schlüssel für
Schlüssel ergänzt; ein bloßes `-e @config.yml` würde sie als Ganzes ersetzen.

Nur Standardbibliothek und PyYAML (kommt mit dem Debian-Paket ansible).
"""

import argparse
import copy
import difflib
import ipaddress
import json
import os
import re
import sys
import tempfile

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(REPO, "config", "schema.yml")
CONFIG = "/etc/aunserver/config.yml"
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
                "einstellungen": self.leaves}


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
    if not res.errors:
        eff = merge(schema, config)
        for path, spec in schema.leaves.items():
            dep = spec.get("braucht")
            if dep and get_path(config, path) is not None and get_path(eff, dep) is False \
                    and get_path(config, path) != spec.get("standard"):
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
        "sudo nano /etc/aunserver/config.yml",
        "sudo aunserver-config validate      # Tippfehler und falsche Werte finden",
        "sudo aunserver-setup                # übernehmen",
        "```",
        "",
        "Stufen: **basis** fragt das Setup ab, **erweitert** nur bei Bedarf, **fest** setzt das Setup",
        "(nicht von Hand ändern). Geheime Werte (Passwörter) zeigt `aunserver-config show` nicht an.",
        "",
    ]
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


# --- Befehle ------------------------------------------------------------------------------------

def cmd_validate(args, schema):
    res = validate(schema, load_config(args.datei))
    report(res, args.datei)
    return 1 if res.errors else 0


def cmd_show(args, schema):
    config = load_config(args.datei)
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
    text = "# Erzeugt von aunserver-config aus " + args.datei + " und den Standardwerten, nicht ändern.\n"
    write_atomic(args.out, text + dump(merge(schema, config)))
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
    s = sub.add_parser("effective", help="zusammengeführte Konfiguration für Ansible schreiben")
    s.add_argument("datei", nargs="?", default=CONFIG)
    s.add_argument("--out", required=True)
    s = sub.add_parser("generate", help="group_vars, config.example.yml und Doku aus dem Schema erzeugen")
    s.add_argument("--check", action="store_true", help="nur prüfen, ob die Dateien aktuell sind")
    sub.add_parser("schema", help="Schema als JSON (für den Editor)")
    args = p.parse_args(argv)
    try:
        schema = Schema()
    except SchemaError as e:
        die(f"Schema fehlerhaft:\n{e}")
    return {"validate": cmd_validate, "show": cmd_show, "effective": cmd_effective,
            "generate": cmd_generate, "schema": cmd_schema}[args.befehl](args, schema)


if __name__ == "__main__":
    sys.exit(main())
