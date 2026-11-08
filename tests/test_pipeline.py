"""Fast tests: no Samsung downloads, device access, or third-party test runner."""
import hashlib
import importlib.util
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


firmware = load("firmware")
prepare = load("prepare_port")
pins = load("pins")
validate = load("validate_artifact")


class PipelineTests(unittest.TestCase):
    def test_all_actions_are_full_sha_pins(self):
        lock = json.loads((ROOT / "config/locks.json").read_text())
        for path in (ROOT / ".github/workflows").glob("*.yml"):
            for action, sha in re.findall(r"uses:\s*([^@\s]+)@([\w]+)", path.read_text()):
                self.assertRegex(sha, r"^[0-9a-f]{40}$")
                self.assertIn(sha, lock["actions"].values())

    def test_dependency_urls_and_commits(self):
        lock = json.loads((ROOT / "config/locks.json").read_text())
        for group in ("sources", "engine_submodules"):
            for entry in lock[group].values():
                pins.valid_url(entry["repository"])
                self.assertRegex(entry["commit"], r"^[0-9a-f]{40}$")

    def test_device_and_version_validation(self):
        firmware.validate_device("SM-A546B", "EUX")
        firmware.validate_device("SM-A528B", "BTU")
        for model, region in (("SM-A546U", "TMB"), ("SM-A528B", "../BTU"), ("SM-A546B", "EUX\n")):
            with self.assertRaises(ValueError):
                firmware.validate_device(model, region)
        self.assertTrue(firmware.VERSION.fullmatch("A528BXXU5FWK4/A528BOXM5FWK6/A528BXXU5FWK4"))
        self.assertIsNone(firmware.VERSION.fullmatch("A528BXXU5FWK4/../../x"))

    def test_samsung_md5_and_corruption(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "AP_test.tar.md5"
            payload = b"firmware" * 1000
            p.write_bytes(payload + (hashlib.md5(payload).hexdigest() + " AP_test.tar\n").encode())
            firmware.verify_odin_md5(p)
            p.write_bytes(b"x" + p.read_bytes()[1:])
            with self.assertRaises(RuntimeError):
                firmware.verify_odin_md5(p)

    def test_zip_traversal_is_not_extracted(self):
        with tempfile.TemporaryDirectory() as d:
            zpath, dest = pathlib.Path(d) / "f.zip", pathlib.Path(d) / "out"
            with zipfile.ZipFile(zpath, "w") as z:
                z.writestr("AP_test.tar.md5", b"ap")
                z.writestr("BL_test.tar.md5", b"bl")
                z.writestr("../escape", b"bad")
                z.writestr("AP_../../escape.tar.md5", b"bad")
            found = firmware.safe_extract_zip(zpath, dest)
            self.assertEqual({x["name"] for x in found}, {"AP_test.tar.md5", "BL_test.tar.md5"})
            self.assertFalse((pathlib.Path(d) / "escape").exists())

    def test_source_profile_has_every_required_variable(self):
        with tempfile.TemporaryDirectory() as d:
            r = pathlib.Path(d)
            for rel in ("system/system/etc", "product/etc", "vendor"):
                (r / rel).mkdir(parents=True)
            (r / "system/system/build.prop").write_text(
                "ro.build.version.sdk=37\nro.product.first_api_level=33\nro.board.api_level=33\n"
                "ro.build.product=qssi\nro.system.build.fingerprint=samsung/a54xnsxx/a54x:17/test\n")
            (r / "system/system/etc/floating_feature.xml").write_text(
                '<SecFloatingFeatureSet><SEC_FLOATING_FEATURE_AUDIO_SUPPORT_DUAL_SPEAKER>TRUE'
                '</SEC_FLOATING_FEATURE_AUDIO_SUPPORT_DUAL_SPEAKER></SecFloatingFeatureSet>')
            text, info = prepare.source_config(r, "SM-A546B", "EUX")
            self.assertEqual(info["ssi"], "qssi")
            self.assertEqual(info["board_api"], 33)
            self.assertIn("SOURCE_AUDIO_SUPPORT_DUAL_SPEAKER=true", text)
            self.assertNotIn("SM-F976", text)
            # Parse generated assignments with Bash, not eval of untrusted text.
            result = subprocess.run(["bash", "-c", 'set -a; source /dev/stdin; printf "%s\\n" "${!SOURCE_@}"'],
                                    input=text, text=True, capture_output=True, check=True)
            got = set(result.stdout.splitlines())
            self.assertIn("SOURCE_FIRMWARE", got)
            self.assertIn("SOURCE_BLUETOOTH_SUPPORT_A2DP_SBM", got)
            self.assertIn("SOURCE_WLAN_SUPPORT_WIFI_TO_CELLULAR", got)
            self.assertGreaterEqual(len(got), 60)

    def test_unaudited_donor_sdk_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            r = pathlib.Path(d)
            (r / "system/system/etc").mkdir(parents=True)
            (r / "system/system/build.prop").write_text("ro.build.version.sdk=36\n")
            (r / "system/system/etc/floating_feature.xml").write_text("<SecFloatingFeatureSet/>")
            with self.assertRaises(RuntimeError):
                prepare.source_config(r, "SM-A546B", "EUX")

    def test_package_validator_rejects_empty_zip(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d) / "empty.zip"
            with zipfile.ZipFile(p, "w"):
                pass
            with self.assertRaises(RuntimeError):
                validate.validate_package(p)


if __name__ == "__main__":
    unittest.main()
