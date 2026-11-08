#!/usr/bin/env python3
"""Resolve, download and inventory Samsung firmware without logging identifiers.

Uses the pinned ananjaser1211/samloader for FUS authentication/download. The
version-only endpoint needs no IMEI. A public model TAC is used by default;
samloader generates a synthetic identifier. No real device identifier is needed.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
VERSION = re.compile(r"[A-Z0-9]+/[A-Z0-9]+/[A-Z0-9]+(?:/[A-Z0-9]+)?\Z")
MODEL = re.compile(r"SM-A(?:546[BE]|528[BN])\Z")
REGION = re.compile(r"[A-Z]{3}\Z")


def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def validate_device(model, region):
    if not MODEL.fullmatch(model) or not REGION.fullmatch(region):
        raise ValueError("Unsupported model/region. Use an international A54/A52s model and a three-letter CSC.")


def latest(model, region):
    validate_device(model, region)
    url = f"https://fota-cloud-dn.ospserver.net/firmware/{region}/{model}/version.xml"
    req = urllib.request.Request(url, headers={"User-Agent": "SAMSUNG-Android"})
    with urllib.request.urlopen(req, timeout=45) as response:
        root = ET.fromstring(response.read())
    nodes = [n for n in root.iter() if n.tag.rsplit("}", 1)[-1] == "latest"]
    if not nodes or not nodes[0].text:
        raise RuntimeError(f"No latest firmware returned for {model}/{region}")
    value = nodes[0].text.strip()
    if not VERSION.fullmatch(value):
        raise RuntimeError("Malformed FUS version response")
    parts = value.split("/")
    if len(parts) == 3:
        parts.append(parts[0])
    if not parts[0].startswith(model.removeprefix("SM-")):
        raise RuntimeError("FUS returned firmware for a different model")
    return "/".join(parts)


def resolve(config, output):
    donor, target = config["donor"], config["target"]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        djob = pool.submit(latest, donor["model"], donor["region"])
        tjob = pool.submit(latest, target["model"], target["region"])
        donor_version, target_latest = djob.result(), tjob.result()
    result = {
        "schema": 1,
        "donor": {k: donor[k] for k in ("model", "region", "codename")},
        "donor_version": donor_version,
        "target": {k: target[k] for k in ("model", "region", "codename")},
        "target_version": target["firmware"],
        "target_latest_observed": target_latest,
        "target_base_is_intentionally_pinned": True,
        "hardware_validated": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def safe_extract_zip(path, dest):
    """Extract only the four Odin members; reject traversal and encrypted entries."""
    dest.mkdir(parents=True, exist_ok=True)
    found = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            name = info.filename
            if "/" in name or "\\" in name or not re.fullmatch(r"(?:AP|BL|CP|CSC)_[A-Za-z0-9_.-]+\.tar\.md5", name):
                continue
            if info.flag_bits & 1:
                raise RuntimeError("Encrypted firmware member")
            target = dest / name
            with z.open(info) as src, open(target, "wb") as out:
                while block := src.read(4 * 1024 * 1024):
                    out.write(block)
            found.append({"name": name, "size": target.stat().st_size, "sha256": digest(target)})
    if not any(x["name"].startswith("AP_") for x in found) or not any(x["name"].startswith("BL_") for x in found):
        raise RuntimeError("Firmware ZIP lacks AP/BL Odin packages")
    return found


def verify_odin_md5(path):
    """Samsung's trailer authenticates transport integrity, NOT trust/authenticity."""
    size = path.stat().st_size
    with open(path, "rb") as f:
        f.seek(max(0, size - 4096))
        tail = f.read()
    match = re.search(rb"([0-9a-fA-F]{32})\s+\S+\s*$", tail)
    if not match:
        raise RuntimeError(f"Missing Samsung MD5 trailer: {path.name}")
    length = len(tail) - match.start()
    h = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as f:
        remaining = size - length
        while remaining:
            block = f.read(min(4 * 1024 * 1024, remaining))
            if not block:
                raise RuntimeError("Truncated Odin package")
            remaining -= len(block)
            h.update(block)
    if h.hexdigest().lower() != match.group(1).decode().lower():
        raise RuntimeError(f"Odin MD5 mismatch: {path.name}")


def download_one(args, device, version, tac):
    model, region = device["model"], device["region"]
    validate_device(model, region)
    if not VERSION.fullmatch(version):
        raise ValueError("Invalid firmware version")
    if not re.fullmatch(r"[0-9]{8}", tac):
        raise ValueError("Use an eight-digit public TAC, not a full IMEI")
    dest = args.work / "engine/out/odin" / f"{model}_{region}"
    dest.mkdir(parents=True, exist_ok=True)
    marker = dest / ".downloaded"
    if marker.exists() and marker.read_text().strip() == version and list(dest.glob("AP_*.tar.md5")):
        print(f"Reusing verified {model}/{region} {version}")
    else:
        samloader = args.work / "engine/out/tools/venv/bin/samloader"
        if not samloader.exists():
            raise RuntimeError("Build pinned dependencies before downloading firmware")
        # This fork logs identifiers/auth headers by default. Disable before ANY FUS call.
        log_py = args.work / "samloader/samloader/logging.py"
        text = log_py.read_text().replace("logging_enabled = True", "logging_enabled = False").replace("FUS = True", "FUS = False")
        log_py.write_text(text)
        env = dict(os.environ, PYTHONPATH=str(args.work / "samloader"), PYTHONDONTWRITEBYTECODE="1")
        command = [str(samloader), "-m", model, "-r", region, "-i", tac,
                   "download", "-v", version, "-O", str(dest)]
        # Never tee raw samloader output: it can print a generated identifier.
        result = subprocess.run(command, env=env, cwd=dest, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if result.returncode:
            safe = re.sub(r"\b\d{15}\b", "[redacted-identifier]", result.stdout)
            print(safe[-6000:], file=sys.stderr)
            raise RuntimeError(f"FUS download failed for {model}/{region}; inspect error above")
        zips = list(dest.glob("*.zip"))
        if len(zips) != 1:
            raise RuntimeError(f"Expected exactly one firmware ZIP, found {len(zips)}")
        archive = zips[0]
        inventory = safe_extract_zip(archive, dest)
        for item in inventory:
            verify_odin_md5(dest / item["name"])
        (dest / "odin-members.json").write_text(json.dumps(inventory, indent=2) + "\n")
        archive.unlink()
        marker.write_text(version + "\n")
    for path in dest.glob("*.tar.md5"):
        verify_odin_md5(path)
    return {"model": model, "region": region, "version": version,
            "odin_packages": [{"name": p.name, "size": p.stat().st_size, "sha256": digest(p)}
                              for p in sorted(dest.glob("*.tar.md5"))]}


def download(args, config, plan):
    if plan["donor_version"].split("/")[0].startswith("A546") is False:
        raise RuntimeError("Plan does not describe an A54 donor")
    results = []
    for role, version_key in (("donor", "donor_version"), ("target", "target_version")):
        device = config[role]
        if plan[role]["model"] != device["model"] or plan[role]["region"] != device["region"]:
            raise RuntimeError("Plan/model mismatch; regenerate the firmware plan")
        tac = os.environ.get(f"FISHERGLOBE_{role.upper()}_TAC", device["fus_tac"])
        results.append(download_one(args, device, plan[version_key], tac))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"schema": 1, "plan": plan, "packages": results}, indent=2) + "\n")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["resolve", "latest", "download", "verify-odin", "safe-extract"])
    ap.add_argument("--config", type=pathlib.Path, default=ROOT / "config/port.json")
    ap.add_argument("--work", type=pathlib.Path, default=ROOT / ".work")
    ap.add_argument("--output", type=pathlib.Path, default=ROOT / "reports/firmware-plan.json")
    ap.add_argument("--plan", type=pathlib.Path, default=ROOT / "reports/firmware-plan.json")
    ap.add_argument("--model")
    ap.add_argument("--region")
    ap.add_argument("--file", type=pathlib.Path)
    ap.add_argument("--dest", type=pathlib.Path)
    a = ap.parse_args()
    if a.command == "latest":
        print(latest(a.model, a.region))
    elif a.command == "verify-odin":
        verify_odin_md5(a.file)
        print(f"Transport MD5 OK: {a.file.name}")
    elif a.command == "safe-extract":
        print(json.dumps(safe_extract_zip(a.file, a.dest), indent=2))
    else:
        config = json.loads(a.config.read_text())
        if a.command == "resolve":
            resolve(config, a.output)
        else:
            download(a, config, json.loads(a.plan.read_text()))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"firmware: {exc}", file=sys.stderr)
        sys.exit(1)
