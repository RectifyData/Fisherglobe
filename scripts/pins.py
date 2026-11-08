#!/usr/bin/env python3
"""Fetch only GitHub sources at the exact revisions in config/locks.json."""
import argparse
import json
import pathlib
import re
import subprocess
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parents[1]
SHA = re.compile(r"[0-9a-f]{40}\Z")
# pa2qxxx alone is 1.4 GB and is not referenced by the a52sxq build.
SPARSE = [
    "/*", "!/target/*/", "!/platform/*/", "!/prebuilts/samsung/*/",
    "/target/a52sxq/", "/platform/sm7325/",
    *[f"/prebuilts/samsung/{x}/" for x in (
        "a17xxx", "a34xxx", "a53xtfn", "a54xnsxx", "a73xqxx", "b0qxxx",
        "b0sxxx", "b4qxxx", "dm1qxxx", "gta9pxxx", "gts11xx", "r9qxxx", "r9sxxx")],
]


def git(*args, cwd=None):
    subprocess.run(["git", *args], cwd=cwd, check=True)


def valid_url(url):
    p = urllib.parse.urlparse(url)
    if p.scheme != "https" or p.hostname != "github.com" or p.query or p.fragment or p.username:
        raise ValueError(f"Only dependency-free HTTPS GitHub URLs are allowed: {url}")
    if not re.fullmatch(r"/[\w.-]+/[\w.-]+\.git", p.path):
        raise ValueError(f"Invalid GitHub source URL: {url}")


def checkout(work, name, entry, sparse=False):
    url, commit = entry["repository"], entry["commit"]
    valid_url(url)
    if not SHA.fullmatch(commit):
        raise ValueError("Dependency revisions must be full commit hashes")
    dest = work / name
    if not (dest / ".git").exists():
        git("init", "-q", str(dest))
        git("remote", "add", "origin", url, cwd=dest)
    else:
        git("remote", "set-url", "origin", url, cwd=dest)
    if sparse:
        git("config", "extensions.partialClone", "origin", cwd=dest)
        git("sparse-checkout", "init", "--no-cone", cwd=dest)
        (dest / ".git/info/sparse-checkout").write_text("\n".join(SPARSE) + "\n")
    git("-c", "protocol.version=2", "fetch", "--depth=1", "--filter=blob:none", "origin", commit, cwd=dest)
    git("-c", "advice.detachedHead=false", "checkout", "--detach", commit, cwd=dest)
    actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=dest, text=True).strip()
    if actual != commit:
        raise RuntimeError(f"Revision mismatch for {name}")


def main():
    lock = json.loads((ROOT / "config/locks.json").read_text())
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["checkout", "submodules", "nested", "actions"])
    ap.add_argument("--work", type=pathlib.Path)
    ap.add_argument("--name")
    ap.add_argument("--sparse", action="store_true")
    ap.add_argument("--engine", type=pathlib.Path)
    a = ap.parse_args()
    if a.command == "checkout":
        checkout(a.work, a.name, lock["sources"][a.name], a.sparse)
    elif a.command == "submodules":
        for path, entry in lock["engine_submodules"].items():
            actual = subprocess.check_output(["git", "rev-parse", f"HEAD:{path}"], cwd=a.engine, text=True).strip()
            if actual != entry["commit"]:
                raise RuntimeError(f"Engine gitlink changed: {path}")
            checkout(a.engine / "external", path.removeprefix("external/"), entry)
    elif a.command == "nested":
        tools = a.engine / "external/android-tools"
        # These gitlinks point to AOSP Gitiles, not GitHub. The GitHub release
        # tarball is not interchangeable with UN1CA's patched gitlink tree.
        # CI has normal upstream access; this sandbox restricts outbound hosts.
        git("submodule", "update", "--init", "--recursive", "--depth=1", cwd=tools)
        expected = subprocess.check_output(
            ["git", "ls-tree", "-r", "HEAD", "vendor"], cwd=tools, text=True)
        for line in expected.splitlines():
            meta, path = line.split("\t")
            mode, kind, commit = meta.split()
            if kind == "commit":
                actual = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tools / path, text=True).strip()
                if actual != commit:
                    raise RuntimeError(f"Nested gitlink mismatch: {path}")
    else:
        for key, sha in lock["actions"].items():
            if not SHA.fullmatch(sha):
                raise ValueError(f"Unpinned action: {key}")
            print(f"{key.split('@')[0]}@{sha} # {key.split('@')[1]}")


if __name__ == "__main__":
    main()
