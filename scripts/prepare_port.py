#!/usr/bin/env python3
"""Adapt the pinned A52s engine to an inspected A54 donor, fail-closed.

This deliberately does not rename an Exynos vendor to Snapdragon or apply
Fold-only binary patches to a different firmware. Source feature values come
from the downloaded A54 image, rather than guessing that another donor matches.
"""
import argparse
import json
import pathlib
import re
import shlex
import shutil
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
PREFIX = "SEC_FLOATING_FEATURE_"
# These patches contain offsets/prebuilt APEXes/framework assumptions tied to
# the Fold8 donor. Generic A52s/kernel-5.4 compatibility patches stay enabled.
DONOR_SPECIFIC = {
    "a52s_hw_features", "bt_a2dp_offload", "devicestate",
    "fold_flex_mode_settings", "qs_phone_layout", "wallpaper",
    "audio_policy_legacy_keys", "zygote_next_kernel54", "zygote_next_fix",
}
# Optional rooted kernel is not required to produce an A54 system port. Keep
# the target's own kernel, vendor_boot and dtbo by default.
OPTIONAL_DISABLED = {"kernel_bone_machine", "degoogle"}


def properties(path):
    result = {}
    if not path.is_file():
        return result
    for line in path.read_text(errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def read_props(root, partition):
    paths = {
        "system": ["system/system/build.prop"],
        "product": ["product/etc/build.prop"],
        "vendor": ["vendor/default.prop", "vendor/build.prop"],
        "odm": ["odm/etc/build.prop"],
        "system_ext": ["system_ext/etc/build.prop", "system/system/system_ext/etc/build.prop"],
    }
    result = {}
    for rel in paths[partition]:
        result.update(properties(root / rel))
    return result


def floating(root):
    path = root / "system/system/etc/floating_feature.xml"
    if not path.is_file():
        raise RuntimeError(f"Missing donor floating_feature.xml: {path}")
    tree = ET.parse(path)
    return {n.tag: (n.text or "").strip() for n in tree.iter() if n.tag.startswith(PREFIX)}


def feature_bool(value):
    return "true" if value.upper() in {"TRUE", "1", "SUPPORT", "YES", "ON"} else "false"


def source_config(donor_root, model, region, identifier="public-tac"):
    sysprops = read_props(donor_root, "system")
    product = read_props(donor_root, "product")
    vendor = read_props(donor_root, "vendor")
    ff = floating(donor_root)
    allprops = {**vendor, **product, **sysprops}
    sdk = int(allprops["ro.build.version.sdk"])
    if not 37 <= sdk <= 37:
        raise RuntimeError(f"Donor SDK {sdk} has not been audited; this pipeline currently requires SDK 37")
    ssi = allprops.get("ro.build.product", "")
    if ssi not in {"qssi", "essi"}:
        raise RuntimeError(f"Unexpected donor single-system image: {ssi!r}")
    board = int(allprops.get("ro.board.api_level", allprops["ro.product.first_api_level"]))
    # Fail rather than silently retaining Fold8 donor values.
    values = {
        "SOURCE_FIRMWARE": f"{model}/{region}/{identifier}",
        "SOURCE_EXTRA_FIRMWARES": (),
        "SOURCE_PLATFORM_SDK_VERSION": sdk,
        "SOURCE_PRODUCT_SHIPPING_API_LEVEL": int(allprops["ro.product.first_api_level"]),
        "SOURCE_BOARD_API_LEVEL": board,
        "SOURCE_OS_SINGLE_SYSTEM_IMAGE": ssi,
        "SOURCE_SUPER_GROUP_NAME": "qti_dynamic_partitions" if ssi == "qssi" else "group_basic",
        "SOURCE_FRAMEWORK_SUPPORT_FOLDABLE_TYPE_FOLD": "false",
        "SOURCE_FRAMEWORK_SUPPORT_HALF_FOLDED_MODE": "false",
        "SOURCE_LCD_CONFIG_SUB_HFR_MODE": "none",
        "SOURCE_LCD_CONFIG_SUB_HFR_SUPPORTED_REFRESH_RATE": "none",
        "SOURCE_CAMERA_APP_FLAVOR": "hal3-release",
        "SOURCE_AUDIO_CONFIG_RECORDALIVE_LIB_VERSION": "none",
        "SOURCE_DVFSAPP_CONFIG_DVFS_POLICY_FILENAME": "dvfs_policy_default",
        "SOURCE_FINGERPRINT_CONFIG_SENSOR": "google_touch_display_optical,settings=3",
        "SOURCE_RIL_FEATURES": "onebinary",
        "SOURCE_SECURITY_CONFIG_ESE_CHIP_VENDOR": "none",
        "SOURCE_SECURITY_CONFIG_ESE_COS_NAME": "none",
    }
    # These switches have a documented floating_feature.xml counterpart.
    mappings = {
        "AUDIO_SUPPORT_DUAL_SPEAKER": "AUDIO_SUPPORT_DUAL_SPEAKER",
        "COMMON_CONFIG_MDNIE_MODE": "COMMON_CONFIG_MDNIE_MODE",
        "COMMON_SUPPORT_DYN_RESOLUTION_CONTROL": "COMMON_CONFIG_DYN_RESOLUTION_CONTROL",
        "COMMON_SUPPORT_EMBEDDED_SIM": "COMMON_CONFIG_EMBEDDED_SIM_SLOTSWITCH",
        "COMMON_SUPPORT_HDR_EFFECT": "COMMON_SUPPORT_HDR_EFFECT",
        "DVFSAPP_CONFIG_SSRM_POLICY_FILENAME": "SYSTEM_CONFIG_SIOP_POLICY_FILENAME",
        "LCD_CONFIG_COLOR_WEAKNESS_SOLUTION": "LCD_CONFIG_COLOR_WEAKNESS_SOLUTION",
        "LCD_CONFIG_CONTROL_AUTO_BRIGHTNESS": "LCD_CONFIG_CONTROL_AUTO_BRIGHTNESS",
        "LCD_CONFIG_HFR_DEFAULT_REFRESH_RATE": "LCD_CONFIG_HFR_DEFAULT_REFRESH_RATE",
        "LCD_CONFIG_HFR_MODE": "LCD_CONFIG_HFR_MODE",
        "LCD_CONFIG_HFR_SUPPORTED_REFRESH_RATE": "LCD_CONFIG_HFR_SUPPORTED_REFRESH_RATE",
        "LCD_CONFIG_SEAMLESS_BRT": "LCD_CONFIG_SEAMLESS_BRT",
        "LCD_CONFIG_SEAMLESS_LUX": "LCD_CONFIG_SEAMLESS_LUX",
        "LCD_SUPPORT_MDNIE_HW": "LCD_SUPPORT_MDNIE_HW",
        "RIL_SIM_CONFIG_MULTISIM_TRAYCOUNT": "RIL_SIM_CONFIG_MULTISIM_TRAYCOUNT",
        "RIL_SUPPORT_WATERPROOF_SIM_TRAY_MSG": "RIL_SUPPORT_WATERPROOF_SIM_TRAY_MSG",
    }
    for suffix in sorted(set(re.findall(r"SOURCE_(WLAN_\w+)", (ROOT / "config/source-variables.txt").read_text()))):
        mappings[suffix] = suffix
    numeric = {"COMMON_CONFIG_MDNIE_MODE", "LCD_CONFIG_COLOR_WEAKNESS_SOLUTION",
               "LCD_CONFIG_CONTROL_AUTO_BRIGHTNESS", "LCD_CONFIG_HFR_DEFAULT_REFRESH_RATE",
               "LCD_CONFIG_HFR_MODE", "RIL_SIM_CONFIG_MULTISIM_TRAYCOUNT"}
    strings = {"DVFSAPP_CONFIG_SSRM_POLICY_FILENAME", "LCD_CONFIG_HFR_SUPPORTED_REFRESH_RATE",
               "LCD_CONFIG_SEAMLESS_BRT", "LCD_CONFIG_SEAMLESS_LUX"}
    for suffix, feature in mappings.items():
        raw = ff.get(PREFIX + feature, "")
        if suffix in numeric:
            value = int(raw) if raw.isdigit() else 0
        elif suffix in strings:
            value = raw or "none"
        elif suffix == "COMMON_SUPPORT_DYN_RESOLUTION_CONTROL":
            value = "true" if raw else "false"
        else:
            value = feature_bool(raw)
        values["SOURCE_" + suffix] = value
    # Inspectable, conservative feature overrides for non-fold A54 hardware.
    values.update({
        "SOURCE_AUDIO_SUPPORT_ACH_RINGTONE": "true" if list((donor_root / "system/system/media/audio/ui").glob("ACH_*")) else "false",
        "SOURCE_AUDIO_SUPPORT_VIRTUAL_VIBRATION_SOUND": "false",
        "SOURCE_BLUETOOTH_SUPPORT_A2DPSINK_PROFILE": "false",
        "SOURCE_BLUETOOTH_SUPPORT_A2DP_SBM": "false",
        "SOURCE_LCD_CONFIG_HFR_SUPPORTED_REFRESH_RATE_NS": "none",
        "SOURCE_BLUETOOTH_SUPPORT_HEAD_SAR_BACKOFF": "false",
        "SOURCE_BLUETOOTH_SUPPORT_XLNA_CONTROL": "false",
        "SOURCE_CAMERA_SUPPORT_CAMERAX_EXTENSION": feature_bool(allprops.get("ro.camerax.extensions.enabled", "false")),
        "SOURCE_CAMERA_SUPPORT_CUTOUT_PROTECTION": "false",
        "SOURCE_CAMERA_SUPPORT_MASS_APP_FLAVOR": "false",
        "SOURCE_CAMERA_SUPPORT_SDK_SERVICE": "false",
    })
    rec = sorted((donor_root / "vendor/lib64").glob("lib_SamsungRec_*.so"))
    if rec:
        match = re.search(r"lib_SamsungRec_(\d+)\.so\Z", rec[0].name)
        if match:
            values["SOURCE_AUDIO_CONFIG_RECORDALIVE_LIB_VERSION"] = match.group(1)
    lines = ["# Generated from the inspected A54 firmware. Do not copy Fold8 feature flags.",
             "SOURCE_EXTRA_FIRMWARES=()"]
    for key, value in values.items():
        if key == "SOURCE_EXTRA_FIRMWARES":
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        lines.append(f"{key}={shlex.quote(str(value))}")
    return "\n".join(lines) + "\n", {"sdk": sdk, "board_api": board, "ssi": ssi,
                                          "fingerprint": sysprops.get("ro.system.build.fingerprint"),
                                          "security_patch": sysprops.get("ro.build.version.security_patch")}


def prepare(engine, donor_root, target_root, config, report_dir):
    dp, tp = config["donor"], config["target"]
    donor_props = read_props(donor_root, "system")
    target_vendor = read_props(target_root, "vendor")
    if not donor_props.get("ro.system.build.fingerprint"):
        raise RuntimeError("Donor system properties were not extracted")
    if target_vendor.get("ro.product.vendor.device") != "a52sxq":
        raise RuntimeError("Target vendor is not a52sxq; refusing to mix device hardware stacks")
    if int(target_vendor["ro.build.version.sdk"]) != tp["platform_sdk"]:
        raise RuntimeError("Target base is not the pinned Android 14 stack")
    generated, info = source_config(donor_root, dp["model"], dp["region"])
    # The target remains qssi, so gen_config_file.sh reads qssi.sh even when
    # the donor SSI is essi. Keep the inspected source SSI in that profile.
    (engine / "unica/configs/qssi.sh").write_text(generated)
    (engine / "unica/configs/essi.sh").write_text(generated)
    # Use a Fisherglobe identity, public test keys, and no implicit official OTA identity.
    version = engine / "unica/configs/version.sh"
    version.write_text('VERSION_MAJOR=0\nVERSION_MINOR=1\nVERSION_PATCH=0\nROM_VERSION="0.1.0-fisherglobe"\n')
    target_config = engine / "target/a52sxq/config.sh"
    text = target_config.read_text()
    text += '\nTARGET_ASSERT_MODEL=("SM-A528B")\nTARGET_OS_FILE_SYSTEM_TYPE="erofs"\n'
    target_config.write_text(text)
    disabled = []
    for name in sorted(DONOR_SPECIFIC | OPTIONAL_DISABLED):
        module = engine / "target/a52sxq/patches" / name
        if not module.is_dir():
            raise RuntimeError(f"Pinned engine changed: missing module {name}")
        (module / "disable").write_text("Disabled by Fisherglobe: see docs/PORTING.md\n")
        disabled.append(name)
    # Avoid debug/unsolicited feature mods in the first bring-up artifact.
    for name in ("debug", "keybox", "pif", "prophide"):
        module = engine / "unica/mods" / name
        if module.is_dir():
            (module / "disable").write_text("Disabled for experimental bring-up\n")
            disabled.append("unica/mods/" + name)
    # Upstream substitutes a Korean A528N DTBO when its optional kernel is
    # disabled. That is unsafe for this SM-A528B-only profile.
    installer = engine / "target/a52sxq/installer/customize.sh"
    text = installer.read_text()
    text, count = re.subn(
        r'# The bundled bone-machine kernel.*?\nfi\n',
        '# Fisherglobe: retain the extracted SM-A528B DTBO; never substitute A528N.\n'
        'LOG "- Keeping the target SM-A528B dtbo.img"\n', text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Pinned installer DTBO override changed; refusing cross-variant substitution")
    installer.write_text(text)
    shutil.copytree(ROOT / "overlays/a54", engine / "target/a52sxq/patches/zz_fisherglobe_a54", dirs_exist_ok=True)
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {"donor": info, "target": {"device": "a52sxq", "sdk": 34, "board_api": 30},
              "disabled_donor_specific_or_optional_modules": disabled,
              "source_config": generated, "boot_tested": False,
              "status": "experimental-build-only"}
    (report_dir / "port-profile.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "source_config"}, indent=2))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=pathlib.Path, required=True)
    ap.add_argument("--config", type=pathlib.Path, default=ROOT / "config/port.json")
    ap.add_argument("--reports", type=pathlib.Path, default=ROOT / "reports")
    a = ap.parse_args()
    c = json.loads(a.config.read_text())
    fw = a.engine / "out/fw"
    donor = fw / f"{c['donor']['model']}_{c['donor']['region']}"
    target = fw / f"{c['target']['model']}_{c['target']['region']}"
    prepare(a.engine, donor, target, c, a.reports)


if __name__ == "__main__":
    main()
