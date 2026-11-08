# A54 → A52s port: design, evidence, and limits

## Scope

Fisherglobe ports the **latest FUS-available international Galaxy A54 system** to
**SM-A528B / BTU (Galaxy A52s 5G, a52sxq)**. The default donor is SM-A546B/EUX;
SM-A546E and another CSC can be selected in the workflow. Carrier A54 U/U1/W
models and other A52s variants are not silently accepted.

“Latest” describes the donor. The A52s hardware base is deliberately pinned to
Android 14 / SDK 34, shipping API 30, board API 30. The candidate base is
`A528BXXU5FWK4/A528BOXM5FWK6/A528BXXU5FWK4`; FUS must still accept it and supply
its components. Do not downgrade a bootloader to satisfy this requirement.

**This is an experimental port, not a validated daily-driver ROM.** A successful
CI job means the specified build and package checks passed. It does not establish
that Android boots, that the touchscreen works, or that radios, cameras, audio,
biometrics, charging, sleep, or encryption work.

## Why this is not a rename/repack

The A54 uses Exynos 1380; the A52s uses Snapdragon 778G. Their kernels, device
trees, modem firmware, graphics/camera/audio HALs and vendor services are not
interchangeable. The assembly boundary is:

| Component | Origin |
|---|---|
| system, product, source odm, system_ext | Latest A54 |
| vendor, vendor_dlkm, target odm_dlkm/system_dlkm | Pinned A52s |
| boot kernel/ramdisk, vendor_boot, DTBO | Pinned A52s |
| bootloader and modem/CP | Never replaced by this recovery ZIP |
| dynamic partition layout | A52s qti_dynamic_partitions |
| framework/vendor compatibility patches | Pinned k4 A52s engine, with donor-specific exclusions |

The target super size is 10,643,046,400 bytes; its dynamic group limit is
10,638,852,096 bytes. The package validator rejects logical images exceeding that
group limit. EROFS is used for the assembled OS images.

## Sources and reproducibility

- The user-supplied [porting guide](https://github.com/rajdeep-3305/android-porting-guide)
  is fetched at the exact revision in `config/locks.json`. Its extraction,
  partition, AVB/DTBO and debugging guidance informs the process. It is a general
  guide, not evidence that an Exynos vendor can boot on Snapdragon.
- [k4_un1ca](https://github.com/kusti420/k4_un1ca), pinned in the lock file,
  supplies the A52s/SM7325 compatibility work. Its current donor is a Fold8, not
  an A54. We do **not** claim its Fold8 patches are donor-independent.
- [UN1CA](https://github.com/salvogiangri/UN1CA) supplies the underlying framework
  concepts and tooling. k4 and UN1CA are GPL-3.0 projects; preserve their notices
  and license terms when distributing derivatives.
- [samloader](https://github.com/ananjaser1211/samloader) is pinned for Samsung FUS
  acquisition. Version discovery needs no identifier. Downloads use an explicitly
  selected version and a public eight-digit model TAC, from which the client
  generates an identifier. No personal IMEI or serial is requested.

All engine gitlinks and action revisions are pinned. Nested AOSP tool gitlinks
are checked out recursively and verified against the pinned android-tools tree.
Samsung firmware is resolved at run time, then its exact version, package names,
sizes and SHA-256 hashes are recorded. Thus a *new* run can discover a newer donor;
reproducing an *old* run requires the versions and hashes in that run's reports.
Firmware availability is controlled by Samsung and cannot be guaranteed forever.

## Build pipeline

1. Fetch the exact engine, guide, samloader and tool revisions outside this Git
   repository. The sparse engine checkout excludes unrelated device profiles and
   the unused 1.4 GB pa2qxxx prebuilt.
2. Build the pinned Android image tools, apktool, EROFS tools, img2sdat and signapk.
3. Resolve donor latest and target latest through FUS. Keep the compatible target
   base pinned; record both observations.
4. Download explicit versions, extract only flat AP/BL/CP/CSC ZIP members, verify
   Samsung transport MD5 trailers, and record SHA-256 inventories. MD5 is an
   integrity check, not a cryptographic authenticity guarantee.
5. Extract super/partitions and kernel images using the pinned engine. Inspect
   system SDK, SSI, board/shipping API, fingerprints and floating features.
6. Generate the A54 source profile from those inputs. The current profile is
   deliberately guarded to SDK 37; a future SDK requires a new patch audit.
7. Apply compatibility patches, assemble images, audit the vendor boundary, build
   the recovery ZIP, verify its CRC and installer assertions, and emit SHA-256.

The A54 overlay runs after the A52s patches. It rejects a changed target identity,
removes the Fold8 SM8850 AICore configuration, disables the fold wallpaper policy,
and marks the result experimental. The upstream installer's Korean A528N DTBO
substitution is removed: this profile retains the SM-A528B DTBO.

### Deliberate exclusions

Fold-specific display/layout patches, the Fold8-only Bluetooth APEX, fixed-offset
Fold8 audio/zygote patches, the optional third-party rooted kernel, and optional
root/debug/integrity mods are disabled. This avoids transplanting incompatible
binary assumptions, but also means some features are **not fixed** merely because
the package builds. In particular, Bluetooth audio and native-zygote behavior
need donor-specific revalidation. Generic A52s vendor-property, HIDL, seccomp,
cgroup, performance and kernel-5.4 compatibility work is retained subject to its
own content checks. Patch failures and skipped hunks are retained in reports.

The engine's 32-bit runtime/HIDL compatibility prebuilts are tied to an AOSP build
ID. They must match the inspected A54 build or be regenerated before claiming a
working port; a successful assembly alone does not prove ABI compatibility.

## GitHub Actions

- **Pipeline checks**: syntax, YAML, exact action pins and dependency-free tests.
- **Discover A54 firmware**: manual, weekly and relevant pushes; small plan artifact.
- **Build A54 to A52s port**: manual `inspect` or `build` stage. Relevant pushes
  default to inspection, not an automatic flashable release.

Use a GitHub-hosted Ubuntu 24.04 runner for the build. The workflow removes only
disposable preinstalled runner toolchains to make room for firmware and images.
It does not flash a device or publish an automatic GitHub Release. Artifacts are
labelled experimental and retained briefly. Download both the ZIP and its reports;
verify `SHA256SUMS` before any separate hardware experiment.

Local orchestration is also available on an equivalent Ubuntu host:

```sh
python3 -m unittest discover -s tests -v
bash scripts/build.sh inspect
bash scripts/build.sh build
```

These commands need substantial disk space, Java 17, Python 3.11, the workflow's
APT dependencies, FUSE/EROFS support and network access to GitHub, AOSP Gitiles,
Gradle/Maven and Samsung FUS. They are not suitable for a small sandbox. The
optional `FISHERGLOBE_DONOR_TAC` and `FISHERGLOBE_TARGET_TAC` secrets must contain
only eight-digit public TACs. Full identifiers are rejected. Samloader file logging
is disabled before authenticated requests, and its raw output is not tee'd to CI.

## Signing and installation boundary

Only public AOSP test keys are used. This is not a private production signing
scheme. Samsung Knox/attestation is not promised. The recovery package keeps the
engine's SM-A528B model assertion and Android 14 bootloader/base assertions. It
does not include donor BL/CP/modem images. Installer assertions reduce wrong-device
risk; they are not a boot test or a backup mechanism.

Any future hardware test needs an expendable, unlocked SM-A528B, a complete backup,
the matching stock recovery/firmware and a documented recovery path. Do not treat
this repository as permission to relock a modified device. Hardware validation is
a separate manual process and must record boot, setup, calls/data, Wi-Fi/Bluetooth,
both cameras, audio, fingerprint, charging, suspend/resume and encryption results.

## Current evidence

FUS discovery has succeeded. At the November 8, 2026 observation it returned
`A546BXXUNGZJ5/A546BOXMNGZJ5/A546BXXUNGZJ5/A546BXXUNGZJ5` for SM-A546B/EUX.
This is a server observation, not a downloaded or boot-tested ROM. Always read the
current run's `firmware-plan.json` rather than treating this document as a pin.

The pinned GitHub source bootstrap has been exercised locally. Nested AOSP tool
fetches and the full firmware/build pipeline run in CI, where upstream network
access and runner resources are available. See the linked Actions runs for the
actual latest status; this document does not infer success from a queued job.
