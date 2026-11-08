# Runs after the pinned A52s device patches, before generic UN1CA patches.
[[ "$SOURCE_FIRMWARE" == SM-A546[BE]/* ]] || ABORT "Fisherglobe requires an international A54 donor"
[[ "$TARGET_CODENAME" == "a52sxq" ]] || ABORT "Fisherglobe is only for Galaxy A52s 5G"
[[ "$(GET_PROP vendor ro.product.vendor.device)" == "a52sxq" ]] || ABORT "Target vendor identity changed"
[[ "$(GET_PROP vendor ro.build.version.sdk)" == "34" ]] || ABORT "Target Android 14 vendor is required"

# Do not advertise a folding display or a flagship NPU on the A52s.
SET_PROP system persist.wm.fold.wallpaper_policy false
DELETE_FROM_WORK_DIR product etc/sysconfig/google_aicore_QC_SM8850.xml
SET_PROP product remote_provisioning.tee.rkp_only --delete
SET_PROP system ro.fisherglobe.donor_model "$(cut -d / -f 1 <<< "$SOURCE_FIRMWARE")"
SET_PROP system ro.fisherglobe.status experimental
SET_PROP system ro.fisherglobe.hardware_tested false
