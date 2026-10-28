"""Tests für lib/aunserver_config.py: python3 -m unittest discover -s tests"""

import os
import sys
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
        for name in sorted(os.listdir(FIXTURES)):
            with self.subTest(name):
                res = self.check(load(name))
                self.assertEqual((res.errors, res.warnings), ([], []))

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


if __name__ == "__main__":
    unittest.main()
