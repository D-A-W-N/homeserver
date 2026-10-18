#!/usr/bin/env bash
# Baut aus dem offiziellen Debian-13-netinst-ISO das aunserver-Installations-ISO (Plan, Abschnitt 7.1).
#
#   installer/build-iso.sh [--iso DEBIAN.iso] [--out aunserver.iso] [--dev --dev-key KEY.pub]
#
# Ergebnis: Bootmenü-Eintrag "aunserver installieren" (UEFI und BIOS), Preseed und Plattenauswahl
# auf dem Stick, das Repo (git HEAD) als Archiv; der Installer entpackt es nach /opt/aunserver.
# --dev: zusätzlich dev/preseed-dev.cfg (keine Rückfragen, Passwort "aunserver"), SSH-Schlüssel,
#        Bootmenü startet nach 5 s von selbst. NUR für Tests, nie auf einen echten Stick.
#
# Braucht xorriso; fehlt es, läuft das Skript automatisch in einem Debian-13-Container (Docker).
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
REPO=$(cd "$SCRIPT_DIR/.." && pwd)
ISO_BASE=https://cdimage.debian.org/debian-cd/current/amd64/iso-cd

die() { echo "Fehler: $*" >&2; exit 1; }
info() { echo "== $*"; }

ISO_IN="$REPO/.vm/debian-netinst.iso" ISO_OUT="" DEV=0 DEV_KEY="" VERIFY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --iso) ISO_IN=${2:?}; shift ;;
    --out) ISO_OUT=${2:?}; shift ;;
    --dev) DEV=1 ;;
    --dev-key) DEV_KEY=${2:?}; shift ;;
    --no-verify) VERIFY=0 ;;
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "Unbekannte Option: $1" ;;
  esac
  shift
done

# --- ohne xorriso: dasselbe Skript im Container ausführen --------------------------------
if ! command -v xorriso >/dev/null; then
  command -v docker >/dev/null || die "xorriso fehlt (Paket xorriso bzw. libisoburn) und Docker ist nicht da."
  info "xorriso fehlt, baue in einem Debian-13-Container"
  iso_dir=$(cd "$(dirname "$(readlink -f "$ISO_IN")")" && pwd)
  # Im Container nur ins Repo schreibbar: dort bauen, danach an den gewünschten Ort verschieben
  tmp_out="aunserver-build-$$.iso"
  args=(--iso "/iso/$(basename "$(readlink -f "$ISO_IN")")" --out "/repo/$tmp_out")
  [ "$DEV" = 1 ] && args+=(--dev)
  [ -n "$DEV_KEY" ] && args+=(--dev-key "/key/$(basename "$DEV_KEY")")
  [ "$VERIFY" = 0 ] && args+=(--no-verify)
  mounts=(-v "$REPO:/repo" -v "$iso_dir:/iso:ro")
  [ -n "$DEV_KEY" ] && mounts+=(-v "$(cd "$(dirname "$DEV_KEY")" && pwd):/key:ro")
  docker run --rm "${mounts[@]}" -e HOST_UID="$(id -u)" -e HOST_GID="$(id -g)" -w /repo debian:trixie-slim \
    bash -c 'apt-get update -qq && apt-get install -y -qq xorriso git curl ca-certificates >/dev/null \
             && git config --global --add safe.directory /repo \
             && installer/build-iso.sh "$@"; rc=$?; chown "$HOST_UID:$HOST_GID" /repo/aunserver-build-*.iso 2>/dev/null; exit $rc' \
    _ "${args[@]}"
  if [ -z "$ISO_OUT" ]; then
    version=$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || echo unbekannt)
    ISO_OUT="$REPO/aunserver-$version$([ "$DEV" = 1 ] && echo -dev).iso"
  fi
  mv "$REPO/$tmp_out" "$ISO_OUT"
  info "Abgelegt: $ISO_OUT"
  exit 0
fi

[ -f "$ISO_IN" ] || die "Debian-ISO fehlt: $ISO_IN (dev/vm-test.sh fetch lädt es)"
ISO_REAL=$(readlink -f "$ISO_IN")
VERSION=$(git -C "$REPO" describe --tags --always --dirty 2>/dev/null || echo unbekannt)
[ -n "$ISO_OUT" ] || ISO_OUT="$REPO/aunserver-$VERSION$([ "$DEV" = 1 ] && echo -dev).iso"

# --- Eingabe-ISO prüfen -------------------------------------------------------------------
if [ "$VERIFY" = 1 ]; then
  info "Prüfe $(basename "$ISO_REAL") gegen die Debian-Prüfsummen"
  sums=$(curl -fsSL "$ISO_BASE/SHA256SUMS") || die "SHA256SUMS nicht ladbar (offline? dann --no-verify)"
  expected=$(echo "$sums" | awk -v f="$(basename "$ISO_REAL")" '$2 == f {print $1}')
  [ -n "$expected" ] || die "$(basename "$ISO_REAL") steht nicht in den aktuellen SHA256SUMS (veraltet? dann neu laden oder --no-verify)"
  echo "$expected  $ISO_REAL" | sha256sum -c --quiet - || die "Prüfsumme stimmt nicht"
fi
if [ "$DEV" = 1 ]; then
  [ -f "${DEV_KEY:-}" ] || die "--dev braucht --dev-key mit einem öffentlichen SSH-Schlüssel"
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/aunserver-installer"

# --- Bootmenüs aus dem Original holen ------------------------------------------------------
xorriso -osirrox on -indev "$ISO_REAL" \
  -extract /boot/grub/grub.cfg "$WORK/grub.cfg" \
  -extract /isolinux/isolinux.cfg "$WORK/isolinux.cfg" \
  -extract /isolinux/menu.cfg "$WORK/menu.cfg" \
  -extract /isolinux/gtk.cfg "$WORK/gtk.cfg" \
  -extract /isolinux/spkgtk.cfg "$WORK/spkgtk.cfg" \
  -extract /md5sum.txt "$WORK/md5sum.txt" 2>/dev/null
for f in grub.cfg isolinux.cfg menu.cfg gtk.cfg spkgtk.cfg md5sum.txt; do
  [ -s "$WORK/$f" ] || die "$f fehlt im ISO, Aufbau des Debian-ISOs hat sich geändert (Skript anpassen)"
done
chmod u+w "$WORK"/*.cfg "$WORK/md5sum.txt"
grep -q '^set theme=' "$WORK/grub.cfg" || die "grub.cfg hat keine Zeile 'set theme=', Einfügepunkt fehlt"
grep -q '^include gtk.cfg' "$WORK/menu.cfg" || die "menu.cfg bindet gtk.cfg nicht ein, Einfügepunkt fehlt"

BOOT_ARGS="auto=true priority=critical preseed/file=/cdrom/preseed.cfg vga=788"

# UEFI: eigener Eintrag vor den Debian-Einträgen, als Standard
{
  sed -n '1,/^set theme=/p' "$WORK/grub.cfg"
  echo "set default=0"
  [ "$DEV" = 1 ] && echo "set timeout=5"
  cat <<GRUB
menuentry --hotkey=a 'aunserver installieren ($VERSION)' {
    set background_color=black
    linux    /install.amd/vmlinuz $BOOT_ARGS --- quiet
    initrd   /install.amd/initrd.gz
}
GRUB
  sed '1,/^set theme=/d' "$WORK/grub.cfg"
} > "$WORK/grub.new"

# BIOS: eigene Datei vor dem grafischen Installer, nur sie ist Standard
cat > "$WORK/aunserver.cfg" <<ISOLINUX
label aunserver
	menu label ^aunserver installieren ($VERSION)
	menu default
	kernel /install.amd/vmlinuz
	append initrd=/install.amd/initrd.gz $BOOT_ARGS --- quiet
ISOLINUX
sed -i '/^default installgui/d; /menu default/d' "$WORK/gtk.cfg"
# Debian startet im BIOS-Menü nach 30 s ohne Tastendruck die Sprachausgabe-Installation
# (timeout/ontimeout in spkgtk.cfg). Auf einem NAS unerwünscht: Automatik entfernen, der
# Menüpunkt bleibt. Gefunden im M7-Test.
grep -q '^ontimeout' "$WORK/spkgtk.cfg" || die "spkgtk.cfg ohne ontimeout, Aufbau des Debian-ISOs hat sich geändert"
sed -i '/^# timeout to speech-enabled install/d; /^timeout /d; /^ontimeout /d; /^menu autoboot /d' "$WORK/spkgtk.cfg"
sed -i 's/^include gtk.cfg/include aunserver.cfg\ninclude gtk.cfg/' "$WORK/menu.cfg"
[ "$DEV" = 1 ] && sed -i 's/^timeout 0/timeout 50/' "$WORK/isolinux.cfg"

# --- Preseed, Plattenauswahl, Repo ----------------------------------------------------------
early='sh /cdrom/aunserver-installer/select-disk.sh'
late='cp /cdrom/aunserver-installer/aunserver.tar.gz /target/tmp/ \&\& in-target tar -xzf /tmp/aunserver.tar.gz -C /opt \&\& in-target rm /tmp/aunserver.tar.gz \&\& cp /cdrom/aunserver-installer/aunserver-login.sh /target/etc/profile.d/aunserver.sh'
if [ "$DEV" = 1 ]; then
  early="AUN_YES=1 $early"
  late="$late \&\& mkdir -p /target/home/nasadmin/.ssh \&\& cp /cdrom/aunserver-installer/authorized_keys /target/home/nasadmin/.ssh/ \&\& chmod 700 /target/home/nasadmin/.ssh \&\& in-target chown -R nasadmin:nasadmin /home/nasadmin/.ssh"
  cp "$DEV_KEY" "$WORK/aunserver-installer/authorized_keys"
fi
sed -e "s|@EARLY_CMD@|$early|" -e "s|@LATE_CMD@|$late|" "$REPO/installer/preseed.cfg.in" > "$WORK/preseed.cfg"
[ "$DEV" = 1 ] && cat "$REPO/dev/preseed-dev.cfg" >> "$WORK/preseed.cfg"

cp "$REPO/installer/select-disk.sh" "$REPO/installer/aunserver-login.sh" "$WORK/aunserver-installer/"
info "Repo-Stand $VERSION einpacken"
# "git stash create" liefert einen Commit mit nicht committeten Änderungen (ohne den Arbeitsstand
# anzufassen), sonst HEAD; nicht versionierte Dateien (.vm, .venv, *.iso) bleiben draußen
tree=$(git -C "$REPO" stash create 2>/dev/null || true)
# tar.umask=022: Ordner 755, Dateien 644/755 (Standard wäre 002, also gruppenbeschreibbar; M7-Test)
git -C "$REPO" -c tar.umask=022 archive --format=tar --prefix=aunserver/ "${tree:-HEAD}" | gzip -9 > "$WORK/aunserver-installer/aunserver.tar.gz"
echo "$VERSION" > "$WORK/aunserver-installer/VERSION"

# --- md5sum.txt fortschreiben (sonst meldet die Medienprüfung Fehler) ------------------------
md5_of() { md5sum "$1" | cut -d' ' -f1; }
{
  grep -vE '  \./(boot/grub/grub\.cfg|isolinux/(isolinux|menu|gtk|spkgtk|aunserver)\.cfg|preseed\.cfg|aunserver-installer/.*)$' "$WORK/md5sum.txt"
  echo "$(md5_of "$WORK/grub.new")  ./boot/grub/grub.cfg"
  for f in isolinux menu gtk spkgtk aunserver; do
    src=$WORK/$f.cfg
    echo "$(md5_of "$src")  ./isolinux/$f.cfg"
  done
  echo "$(md5_of "$WORK/preseed.cfg")  ./preseed.cfg"
  for f in "$WORK"/aunserver-installer/*; do
    echo "$(md5_of "$f")  ./aunserver-installer/$(basename "$f")"
  done
} > "$WORK/md5sum.new"

# --- ISO schreiben (Bootfähigkeit für UEFI und BIOS wie im Original) --------------------------
info "Schreibe $(basename "$ISO_OUT")"
rm -f "$ISO_OUT"
xorriso -indev "$ISO_REAL" -outdev "$ISO_OUT" \
  -map "$WORK/grub.new" /boot/grub/grub.cfg \
  -map "$WORK/isolinux.cfg" /isolinux/isolinux.cfg \
  -map "$WORK/menu.cfg" /isolinux/menu.cfg \
  -map "$WORK/gtk.cfg" /isolinux/gtk.cfg \
  -map "$WORK/spkgtk.cfg" /isolinux/spkgtk.cfg \
  -map "$WORK/aunserver.cfg" /isolinux/aunserver.cfg \
  -map "$WORK/preseed.cfg" /preseed.cfg \
  -map "$WORK/aunserver-installer" /aunserver-installer \
  -map "$WORK/md5sum.new" /md5sum.txt \
  -boot_image any replay 2>&1 | grep -E "^xorriso : (FAILURE|SORRY|WARNING)" || true
[ -s "$ISO_OUT" ] || die "ISO wurde nicht geschrieben"
info "Fertig: $ISO_OUT ($(du -h "$ISO_OUT" | cut -f1))"
[ "$DEV" = 1 ] && echo "   ACHTUNG: Dev-ISO (installiert ohne Rückfragen und löscht die erkannte Systemplatte), nur für VMs!"
echo "   Auf einen USB-Stick schreiben: sudo dd if=$(basename "$ISO_OUT") of=/dev/sdX bs=4M status=progress conv=fsync"
