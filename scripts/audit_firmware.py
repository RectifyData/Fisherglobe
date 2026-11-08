#!/usr/bin/env python3
"""Inventory the extracted inputs and reject obvious cross-SoC contamination."""
import argparse
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def propfile(path):
    result = {}
    if path.is_file():
        for line in path.read_text(errors="replace").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                result[k] = v
    return result


def audit(engine, config):
    fw = engine / "out/fw"
    roles = {}
    for role in ("donor", "target"):
        c = config[role]
        path = fw / f"{c['model']}_{c['region']}"
        if not (path / ".extracted").is_file():
            raise RuntimeError(f"{role} firmware has not been extracted")
        system = propfile(path / "system/system/build.prop")
        vendor = propfile(path / "vendor/build.prop")
        if not system or not vendor:
            raise RuntimeError(f"Missing {role} system/vendor properties")
        record = {"model": c["model"], "region": c["region"],
                  "extracted_version": (path / ".extracted").read_text().strip(),
                  "system_sdk": system.get("ro.build.version.sdk"),
                  "system_fingerprint": system.get("ro.system.build.fingerprint"),
                  "vendor_device": vendor.get("ro.product.vendor.device"),
                  "vendor_fingerprint": vendor.get("ro.vendor.build.fingerprint"),
                  "security_patch": system.get("ro.build.version.security_patch"),
                  "kernel": {p.name: {"size": p.stat().st_size, "sha256": sha(p)}
                             for p in sorted((path / "kernel").glob("*.img"))}}
        roles[role] = record
    if roles["donor"]["system_sdk"] != "37":
        raise RuntimeError("The latest donor is no longer SDK 37; re-audit patches before building")
    if roles["target"]["vendor_device"] != "a52sxq" or roles["target"]["system_sdk"] != "34":
        raise RuntimeError("The target must retain its A52s Android 14 hardware stack")
    if not roles["target"]["kernel"].get("boot.img") or not roles["target"]["kernel"].get("dtbo.img"):
        raise RuntimeError("Missing target boot/dtbo images")
    return {"schema": 1, "inputs": roles, "boot_tested": False}


def audit_workdir(engine):
    """Called after assembly; these files must come from the A52s, not A54."""
    work = engine / "out/target/a52sxq/work_dir"
    vendor = propfile(work / "vendor/build.prop")
    if vendor.get("ro.product.vendor.device") != "a52sxq":
        raise RuntimeError("Assembled vendor is not A52s")
    # Reject Exynos kernel modules in the assembled Qualcomm vendor.
    modules = list((work / "vendor/lib/modules").rglob("*.ko"))
    bad = []
    for path in modules:
        data = path.read_bytes()
        if re.search(rb"vermagic=[^\x00]*(?:s5e1380|exynos1380)", data, re.I):
            bad.append(str(path.relative_to(work)))
    if bad:
        raise RuntimeError("A54 Exynos modules found in A52s vendor: " + ", ".join(bad))
    return {"vendor_device": vendor.get("ro.product.vendor.device"),
            "vendor_sdk": vendor.get("ro.build.version.sdk"),
            "kernel_module_count": len(modules), "exynos_module_count": 0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=pathlib.Path, required=True)
    ap.add_argument("--config", type=pathlib.Path, default=ROOT / "config/port.json")
    ap.add_argument("--reports", type=pathlib.Path, default=ROOT / "reports")
    ap.add_argument("--workdir", action="store_true")
    a = ap.parse_args()
    result = audit_workdir(a.engine) if a.workdir else audit(a.engine, json.loads(a.config.read_text()))
    a.reports.mkdir(parents=True, exist_ok=True)
    name = "assembled-vendor.json" if a.workdir else "firmware-audit.json"
    (a.reports / name).write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
