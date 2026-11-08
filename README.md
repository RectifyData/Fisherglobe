# Fisherglobe

**Experimental GitHub Actions pipeline: latest Samsung Galaxy A54 system → Galaxy A52s 5G.**

Default scope: **SM-A546B/EUX → SM-A528B/BTU (a52sxq)**. The A54 donor follows
Samsung FUS; the A52s keeps its pinned Android 14 vendor/kernel base. This is not
a bootloader downgrade, a vendor rename, or a claim of a working daily-driver ROM.

## Run it

1. Open **Actions → Build A54 to A52s port → Run workflow**.
2. Choose **inspect** to resolve/download/extract and audit the actual firmware,
   or **build** to attempt the experimental recovery ZIP.
3. Read the run summary and `port-reports-*` artifact. A build artifact is named
   `EXPERIMENTAL-a52sxq-*` and includes its SHA-256 and package-validation report.

**Pipeline checks** runs the fast tests. **Discover A54 firmware** runs weekly and
on demand without downloading multi-GB firmware. No workflow flashes a phone or
creates an automatic release.

```sh
python3 -m unittest discover -s tests -v
# On a suitably provisioned Ubuntu 24.04 build host:
bash scripts/build.sh inspect
bash scripts/build.sh build
```

See **[docs/PORTING.md](docs/PORTING.md)** for the partition boundary, exact source
pins, disabled donor-specific patches, signing policy, resource requirements and
hardware-validation checklist. The supplied
[rajdeep-3305/android-porting-guide](https://github.com/rajdeep-3305/android-porting-guide)
is used alongside the pinned k4/UN1CA A52s compatibility engine.

## What success means

- Source/pin checks: the automation inputs are consistent.
- Inspection success: FUS versions and extracted donor/target properties were read.
- Build success: a recovery ZIP passed CRC, model/base-assertion and partition-size checks.
- **Boot/hardware success: not established by CI.** Touch, radios, cameras, audio,
  biometrics, encryption and sleep still require testing on an expendable device.

Samsung firmware and upstream prebuilts are fetched outside Git, never committed.
Only public eight-digit TACs are accepted for FUS downloads; do not supply a real
IMEI. The output uses public AOSP test keys and preserves target model/base guards.

Status: experimental; consult the latest Actions run rather than assuming a queued
or historical job succeeded. License: GPL-3.0-or-later (see `LICENSE`).
