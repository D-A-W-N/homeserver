"""Tests für lib/aunserver_config.py: python3 -m unittest discover -s tests"""

import contextlib
import fcntl
import io
import os
import shutil
import stat
import sys
import tempfile
import unittest

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lib"))

import aunserver_config as ac  # noqa: E402

FIXTURES = os.path.join(REPO, "tests", "konfigurationen")


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return yaml.safe_load(f)


class SchemaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = ac.Schema()

    def test_erzeugte_dateien_aktuell(self):
        self.assertEqual(ac.schema_overlaps(self.schema), [])
        for key, render in (("group_vars", ac.render_group_vars), ("example", ac.render_example),
                            ("docs", ac.render_docs)):
            with open(ac.GENERATED[key], encoding="utf-8") as f:
                self.assertEqual(f.read(), render(self.schema), f"{key}: bin/aunserver-config generate ausführen")

    def test_group_vars_entsprechen_den_standards(self):
        with open(ac.GENERATED["group_vars"], encoding="utf-8") as f:
            self.assertEqual(yaml.safe_load(f), self.schema.defaults())

    def test_beispiel_ist_gueltig(self):
        with open(ac.GENERATED["example"], encoding="utf-8") as f:
            res = ac.validate(self.schema, yaml.safe_load(f))
        self.assertEqual((res.errors, res.warnings), ([], []))


class ValidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = ac.Schema()

    def check(self, config):
        return ac.validate(self.schema, config)

    def test_setup_konfiguration_ohne_befund(self):
        # alte Fassung (1): nur der Hinweis, dass Passwörter nach secrets/ umziehen
        for name in sorted(os.listdir(FIXTURES)):
            with self.subTest(name):
                res = self.check(load(name))
                self.assertEqual(res.errors, [])
                self.assertEqual([w for w in res.warnings if "secrets/" not in w], [])

    def test_vollstaendige_konfiguration_bleibt_unveraendert(self):
        # So wie aunserver-setup sie schreibt: zusammengeführt kommt bei Ansible dasselbe an
        config = load("setup.yml")
        eff = ac.merge(self.schema, config)
        for key, value in config.items():
            self.assertEqual(eff[key], value, key)

    def test_tippfehler_wird_gemeldet(self):
        res = self.check({"caddy_lan_port": True, "apps": {"embi": False}})
        self.assertEqual(res.errors, [])
        self.assertIn("gemeint: caddy_lan_ports?", res.warnings[0])
        self.assertIn("apps.embi", res.warnings[1])
        self.assertIn("gemeint: apps.emby?", res.warnings[1])

    def test_interne_variable_nur_warnung(self):
        res = self.check({"stacks_recyclarr_x265_score": 2000})
        self.assertEqual(res.errors, [])
        self.assertIn("interner Wert", res.warnings[0])

    def test_falsche_typen(self):
        res = self.check({
            "hostname": "Mein NAS", "apps": {"emby": "ja"}, "samba_legacy": {"port": 70000},
            "emby_dlna_renderers": ["192.168.1.300"], "ntfy_default_access": "read-only",
            "backup": "kein", "ssh_authorized_keys": None, "base_auto_reboot_time": "4 Uhr",
        })
        joined = "\n".join(res.errors)
        for path in ("hostname", "apps.emby", "samba_legacy.port", "emby_dlna_renderers[0]",
                     "ntfy_default_access", "backup:", "ssh_authorized_keys", "base_auto_reboot_time"):
            self.assertIn(path, joined)
        self.assertEqual(len(res.errors), 8)

    def test_abhaengigkeit_warnt(self):
        res = self.check({"apps": {"emby": False}, "emby_dlna_renderers": ["192.168.1.110"]})
        self.assertEqual(res.errors, [])
        self.assertIn("wirkt nur mit apps.emby", res.warnings[0])

    def test_keine_einstellungen(self):
        self.assertEqual(self.check({}).errors, [])
        self.assertEqual(self.check(None).errors, [])
        self.assertTrue(self.check(["x"]).errors)


class MergeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = ac.Schema()

    def test_teilweiser_block_behaelt_den_rest(self):
        # Befund: -e @config.yml ersetzt den ganzen Block apps
        eff = ac.merge(self.schema, {"apps": {"emby": False}, "backup": {"repository": "/mnt/backup/x"}})
        self.assertEqual(eff["apps"]["emby"], False)
        self.assertEqual(eff["apps"]["adguard"], True)
        self.assertEqual(eff["backup"]["repository"], "/mnt/backup/x")
        self.assertEqual(eff["backup"]["keep"], {"daily": 7, "weekly": 4, "monthly": 6})

    def test_objekt_schluesselweise_oder_ersetzt(self):
        eff = ac.merge(self.schema, {"stacks_lan_ports": {"sonarr": 9402}, "backup": {"env": {"A": "1"}}})
        self.assertEqual(eff["stacks_lan_ports"]["sonarr"], 9402)
        self.assertEqual(eff["stacks_lan_ports"]["radarr"], 8403)
        self.assertEqual(eff["backup"]["env"], {"A": "1"})
        eff = ac.merge(self.schema, {"stacks_recyclarr_groessen": {"sonarr": []}})
        self.assertEqual(eff["stacks_recyclarr_groessen"]["sonarr"], [])
        self.assertEqual(len(eff["stacks_recyclarr_groessen"]["radarr"]), 8)

    def test_interne_und_unbekannte_werte_durchgereicht(self):
        eff = ac.merge(self.schema, {"stacks_recyclarr_x265_score": 2000, "apps": {"embi": False}})
        self.assertEqual(eff["stacks_recyclarr_x265_score"], 2000)
        self.assertNotIn("embi", eff["apps"])

    def test_geheimes_ohne_standard_nur_wenn_gesetzt(self):
        self.assertNotIn("samba_password", ac.merge(self.schema, {}))
        self.assertEqual(ac.merge(self.schema, {"samba_password": "x"})["samba_password"], "x")

    def test_standards_nicht_veraendert(self):
        eff = ac.merge(self.schema, {})
        eff["apps"]["emby"] = False
        self.assertTrue(self.schema.defaults()["apps"]["emby"])

    def test_geheimes_verdeckt(self):
        masked = ac.mask_secrets(self.schema, load("setup.yml"))
        self.assertEqual(masked["samba_password"], ac.MASK)
        self.assertEqual(masked["samba_legacy_password"], ac.MASK)


class AendernTest(unittest.TestCase):
    """set, unset, import, migrate, diff, history, revert mit Dateien in einem Testordner."""

    def setUp(self):
        self.schema = ac.Schema()
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: getattr(ac, k) for k in ("CONFIG", "SECRETS_DIR", "HISTORY_DIR", "APPLIED", "LOCK")}
        ac.CONFIG = os.path.join(self.tmp, "etc", "config.yml")
        ac.SECRETS_DIR = os.path.join(self.tmp, "etc", "secrets")
        ac.HISTORY_DIR = os.path.join(self.tmp, "etc", "verlauf")
        ac.APPLIED = os.path.join(self.tmp, "state", "config.angewendet.yml")
        ac.LOCK = os.path.join(self.tmp, "lock")
        os.environ.pop("AUNSERVER_LOCK_HELD", None)

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(ac, k, v)
        shutil.rmtree(self.tmp)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = ac.main(list(argv))
            except SystemExit as e:
                rc = e.code
        return rc, out.getvalue(), err.getvalue()

    def write(self, text):
        os.makedirs(os.path.dirname(ac.CONFIG), exist_ok=True)
        with open(ac.CONFIG, "w", encoding="utf-8") as f:
            f.write(text)

    def read(self):
        with open(ac.CONFIG, encoding="utf-8") as f:
            return f.read()

    def test_migration_verschiebt_passwoerter(self):
        shutil.copytree(FIXTURES, os.path.join(self.tmp, "f"))
        os.makedirs(os.path.dirname(ac.CONFIG))
        shutil.copy(os.path.join(FIXTURES, "setup.yml"), ac.CONFIG)
        rc, out, _ = self.run_cli("migrate")
        self.assertEqual(rc, 0)
        self.assertIn("samba_password nach", out)
        text = self.read()
        self.assertNotIn("test-passwort", text)
        self.assertTrue(text.startswith("---\n# So schreibt") or "config_version: 2" in text.splitlines()[1:3])
        data = yaml.safe_load(text)
        self.assertEqual(data["config_version"], 2)
        self.assertEqual(data["apps"], load("setup.yml")["apps"])
        f = os.path.join(ac.SECRETS_DIR, "samba_password")
        self.assertEqual(open(f).read(), "test-passwort\n")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        # Verlauf: alter Stand und Migration, beide ohne Passwörter
        entries = ac.history_entries()
        self.assertEqual(len(entries), 2)
        for e in entries:
            self.assertNotIn("test-passwort", ac.history_read(e)[1])
        self.assertEqual(self.run_cli("migrate")[1], "")   # zweiter Lauf: nichts zu tun
        # Ansible bekommt das Passwort weiter
        out_file = os.path.join(self.tmp, "eff.yml")
        self.assertEqual(self.run_cli("effective", "--out", out_file)[0], 0)
        self.assertEqual(yaml.safe_load(open(out_file))["samba_password"], "test-passwort")

    def test_set_behaelt_kommentare_und_rest(self):
        self.write("---\n# mein Kommentar\nhostname: kleinnas  # bleibt\napps:\n  emby: true\n")
        rc, out, _ = self.run_cli("set", "apps.emby", "false")
        self.assertEqual(rc, 0)
        self.assertIn("apps.emby: true → false", out)
        text = self.read()
        self.assertIn("# mein Kommentar", text)
        self.assertIn("hostname: kleinnas  # bleibt", text)
        self.assertEqual(yaml.safe_load(text)["apps"], {"emby": False})
        self.run_cli("set", "lan_subnets", "[192.168.1.0/24]")
        self.run_cli("set", "base_auto_reboot_time", "05:30")
        data = yaml.safe_load(self.read())
        self.assertEqual(data["lan_subnets"], ["192.168.1.0/24"])
        self.assertEqual(data["base_auto_reboot_time"], "05:30")

    def test_set_lehnt_falsches_ab(self):
        self.write("---\nhostname: kleinnas\n")
        for argv in (("set", "apps.emby", "ja"), ("set", "apps", "{}"), ("set", "caddy_lan_port", "true"),
                     ("set", "emby_dlna_renderers", "[1.2.3]")):
            with self.subTest(argv):
                rc, _, err = self.run_cli(*argv)
                self.assertNotEqual(rc, 0)
        self.assertEqual(self.read(), "---\nhostname: kleinnas\n")
        self.assertIn("gemeint: caddy_lan_ports?", self.run_cli("set", "caddy_lan_port", "true")[2])

    def test_unset_und_leere_bloecke(self):
        self.write("---\napps:\n  emby: false\nhostname: x\n")
        self.assertEqual(self.run_cli("unset", "apps.emby")[0], 0)
        self.assertEqual(yaml.safe_load(self.read()), {"hostname": "x"})
        self.assertIn("schon auf dem Standard", self.run_cli("unset", "apps.emby")[1])

    def test_import_behaelt_uebrige_werte(self):
        self.write("---\nemby_dlna_renderers: [192.168.1.110]\nhostname: alt\n")
        src = os.path.join(self.tmp, "neu.yml")
        with open(src, "w") as f:
            f.write("hostname: neu\nsamba_password: geheim-neu\napps: {emby: false}\n")
        self.assertEqual(self.run_cli("import", src, "--grund", "Setup")[0], 0)
        data = yaml.safe_load(self.read())
        self.assertEqual(data["hostname"], "neu")
        self.assertEqual(data["emby_dlna_renderers"], ["192.168.1.110"])
        self.assertEqual(data["config_version"], 2)
        self.assertNotIn("samba_password", data)
        self.assertEqual(open(os.path.join(ac.SECRETS_DIR, "samba_password")).read(), "geheim-neu\n")
        with open(src, "w") as f:
            f.write("hostnam: tippfehler\n")
        self.assertNotEqual(self.run_cli("import", src)[0], 0)

    def test_neue_datei_per_import(self):
        src = os.path.join(self.tmp, "neu.yml")
        with open(src, "w") as f:
            f.write("hostname: frisch\n")
        self.assertEqual(self.run_cli("import", src)[0], 0)
        self.assertEqual(yaml.safe_load(self.read()), {"config_version": 2, "hostname": "frisch"})
        self.assertEqual(stat.S_IMODE(os.stat(ac.CONFIG).st_mode), 0o600)

    def test_diff_gegen_den_letzten_lauf(self):
        self.write("---\nhostname: a\n")
        self.assertEqual(self.run_cli("mark-applied")[0], 0)
        self.assertEqual(self.run_cli("diff"), (0, "Keine Änderungen.\n", ""))
        self.run_cli("set", "hostname", "b")
        self.run_cli("set", "samba_password", "pw-neu-1234")
        rc, out, _ = self.run_cli("diff")
        self.assertEqual(rc, 3)
        self.assertIn("hostname: a → b", out)
        self.assertNotIn("samba", out)
        self.run_cli("mark-applied")
        self.assertEqual(self.run_cli("diff")[0], 0)
        self.assertNotIn("pw-neu", open(ac.APPLIED).read())

    def test_verlauf_und_zurueck(self):
        self.write("---\nhostname: a\n")
        self.run_cli("set", "hostname", "b")
        self.run_cli("set", "hostname", "c", "--grund", "Test")
        entries = ac.history_entries()
        self.assertEqual(len(entries), 3)   # vorher, b, c
        rc, out, _ = self.run_cli("history")
        self.assertIn("Test", out)
        self.assertIn("[hostname]", out)
        self.assertEqual(self.run_cli("revert", entries[1])[0], 0)
        self.assertEqual(yaml.safe_load(self.read())["hostname"], "b")
        self.assertNotEqual(self.run_cli("revert", "gibtsnicht")[0], 0)

    def test_verlauf_begrenzt(self):
        self.write("---\nhostname: a\n")
        for i in range(ac.HISTORY_KEEP + 3):
            self.run_cli("set", "backup.keep.daily", str(i))
        self.assertEqual(len(ac.history_entries()), ac.HISTORY_KEEP)

    def test_sperre(self):
        self.write("---\nhostname: a\n")
        fd = os.open(ac.LOCK, os.O_RDWR | os.O_CREAT)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            rc, _, err = self.run_cli("set", "hostname", "b")
            self.assertNotEqual(rc, 0)
            self.assertIn("läuft gerade", err)
            os.environ["AUNSERVER_LOCK_HELD"] = "1"   # vom Setup weitergegeben
            self.assertEqual(self.run_cli("set", "hostname", "b")[0], 0)
        finally:
            os.environ.pop("AUNSERVER_LOCK_HELD", None)
            os.close(fd)

    def test_get(self):
        self.write("---\nhostname: a\n")
        self.assertEqual(self.run_cli("get", "hostname")[1], "a\n")
        self.assertEqual(self.run_cli("get", "apps.emby")[1], "true\n")
        self.assertEqual(self.run_cli("get", "lan_subnets")[1], "[]\n")
        self.assertEqual(self.run_cli("get", "tailscale_authkey")[0], 1)
        self.assertNotEqual(self.run_cli("get", "apps")[0], 0)


if __name__ == "__main__":
    unittest.main()
