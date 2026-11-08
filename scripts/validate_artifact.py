#!/usr/bin/env python3
"""Validate a recovery package without pretending to validate bootability."""
import argparse
import hashlib
import json
import pathlib
import re
import zipfile


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def parse_info(text):
    result = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            result[k] = v
    return result


def validate_package(path):
    if path.stat().st_size > 12 * 1024**3:
        raise RuntimeError("Package exceeds conservative 12 GiB artifact limit")
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise RuntimeError(f"ZIP CRC failure: {bad}")
        names = set(z.namelist())
        required = {"META-INF/com/google/android/update-binary",
                    "META-INF/com/google/android/updater-script",
                    "META-INF/com/android/metadata", "build_info.txt",
                    "dynamic_partitions_op_list", "system.new.dat.br",
                    "system.transfer.list", "vendor.new.dat.br", "vendor.transfer.list"}
        missing = required - names
        if missing:
            raise RuntimeError(f"Missing recovery payload members: {sorted(missing)}")
        info = parse_info(z.read("build_info.txt").decode())
        script = z.read("META-INF/com/google/android/updater-script").decode()
        metadata = z.read("META-INF/com/android/metadata").decode()
        ops = z.read("dynamic_partitions_op_list").decode()
        if info.get("device") != "a52sxq" or info.get("model") != "SM-A528B":
            raise RuntimeError("Package is not explicitly guarded for SM-A528B/a52sxq")
        if 'getprop("ro.boot.em.model") == "SM-A528B"' not in script:
            raise RuntimeError("Missing recovery model assertion")
        if "A528BXXU5FWK4" not in script:
            raise RuntimeError("Missing required Android 14 bootloader/base assertion")
        if "pre-device=a52sxq" not in metadata:
            raise RuntimeError("Recovery metadata targets the wrong device")
        if not re.search(r"samsung/a54x", info.get("source_fingerprint", ""), re.I):
            raise RuntimeError("Build manifest does not identify an A54 system donor")
        sizes = [int(x) for x in re.findall(r"^resize \S+ (\d+)$", ops, re.M)]
        if not sizes or sum(sizes) > 10638852096:
            raise RuntimeError("Logical partitions exceed the A52s dynamic group limit")
        if re.search(r"package_extract_file\([^\n]*(?:A546|a54x)", script):
            raise RuntimeError("Donor-named hardware image found in installer")
        return {"package": path.name, "bytes": path.stat().st_size, "sha256": sha(path),
                "build_info": info, "logical_partition_bytes": sum(sizes),
                "model_assertion": True, "base_assertion": True,
                "zip_crc": True, "hardware_boot_tested": False}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=pathlib.Path)
    ap.add_argument("--reports", type=pathlib.Path)
    ap.add_argument("--output", type=pathlib.Path)
    ap.add_argument("--package", type=pathlib.Path)
    a = ap.parse_args()
    if a.package:
        result = validate_package(a.package)
    else:
        candidates = sorted((a.engine / "out").glob("UN1CA_*a52sxq*.zip"))
        candidates = [p for p in candidates if "target_files" not in p.name]
        if len(candidates) != 1:
            raise RuntimeError(f"Expected one flashable ZIP, found {candidates}")
        result = validate_package(candidates[0])
        a.output.mkdir(parents=True, exist_ok=True)
        dest = a.output / candidates[0].name.replace("UN1CA_", "Fisherglobe_EXPERIMENTAL_")
        # Same filesystem: rename avoids a second multi-GB copy.
        candidates[0].rename(dest)
        result["package"] = dest.name
        result["sha256"] = sha(dest)
    if a.reports:
        a.reports.mkdir(parents=True, exist_ok=True)
        (a.reports / "artifact-validation.json").write_text(json.dumps(result, indent=2) + "\n")
        (a.reports / "SHA256SUMS").write_text(result["sha256"] + "  " + result["package"] + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
