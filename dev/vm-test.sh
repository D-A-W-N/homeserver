#!/usr/bin/env bash
# QEMU-Testumgebung für aunserver (Testmatrix aus docs/PLAN.md, Abschnitt 10).
# Benötigt: qemu-system-x86_64, qemu-img, OVMF (für UEFI), curl, sha256sum.
# shellcheck disable=SC2054  # Kommas gehören zu QEMU-Optionen, keine Array-Trenner
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VM_DIR=${VM_DIR:-$SCRIPT_DIR/../.vm}
ISO_BASE=https://cdimage.debian.org/debian-cd/current/amd64/iso-cd
SYS_SIZE=${SYS_SIZE:-20G}
DATA_SIZE=${DATA_SIZE:-50G}
RAM=${RAM:-4096}

usage() {
  cat <<USAGE
Verwendung: ${0##*/} <Befehl> [Optionen]

Befehle:
  fetch                 Aktuelles Debian-netinst-ISO laden und per SHA256 prüfen
  install  <Szenario>   VM neu anlegen und vom ISO booten (löscht die alten Testplatten)
  autoinstall <Szenario>  wie install, aber vollautomatisch mit installer/preseed.cfg.in
                        plus dev/preseed-dev.cfg (Benutzer nasadmin, Passwort "aunserver",
                        eigener SSH-Schlüssel); schaltet sich danach ab, dann 'boot'
  boot     <Szenario>   Installierte VM ohne ISO starten
                        (SSH: localhost:2222, HTTPS: localhost:8443, Cockpit: localhost:9090)
  vt       <Nr> [Szenario]  Konsole <Nr> im laufenden Installer/VM einblenden (statt Strg+Alt+F<Nr>,
                        das der Host oft abfängt). Zurück zum Installer: vt 1 (grafisch: vt 5)
  clean                 Alle Testplatten und VM-Daten löschen

Szenarien (Nummern der Testmatrix):
  1   UEFI, SSD (System) + leere HDD (Daten)
  2   BIOS, wie 1
  3   UEFI, NVMe (System) + zwei SATA-HDDs (Auswahl der Datenplatte im Setup)
  4   UEFI, zwei SSDs (Installer muss fragen)
  5   UEFI, nur eine Platte (Single-Disk-Modus)
  8   UEFI, wie 1, Datenplatte trägt bereits das Label AUNDATA
  nodata  UEFI, nur SSD (z. B. zum Testen von Szenario 7 nach der Installation)
  Szenarien 6, 7 und 9 laufen auf einer bereits installierten VM (boot).

Optionen:
  --iso <Datei>   anderes ISO verwenden (z. B. das mit build-iso.sh gebaute)
  --headless      ohne Fenster starten (nur mit fertiger Installation sinnvoll)
  --print         QEMU-Aufruf nur ausgeben, nicht starten

Umgebungsvariablen:
  VM_DIR          Ablage für Platten und ISO (Default: .vm im Repo)
  VM_NAME         Name für den Monitor-Socket, wenn mehrere VMs parallel laufen (Default: vm)
  SSH_PORT, HTTPS_PORT, COCKPIT_PORT   Weiterleitungen auf dem Host (Default: 2222, 8443, 9090)
  SSH_PUBKEY      Schlüssel für autoinstall (Default: ~/.ssh/id_ed25519.pub)
  NO_DATA=1       bei 'boot': ohne Datenplatte starten (Testmatrix 7)
  CPU_MODEL       virtuelle CPU bei KVM (Standard: host), z. B. qemu64
  DRIVE_OPTS      zusätzliche Optionen für die Platten, z. B. ",cache=none" (lokal traten mit
                  QEMU 11.1/Kernel 7.1 vereinzelt beschädigte Dateien in der VM auf)

Hinweise für den Installer-Test:
  - Preseed ohne ISO-Umbau (Spike S2): im Bootmenü 'e' bzw. Tab drücken und anhängen:
      auto=true priority=critical url=http://10.0.2.2:8000/preseed.cfg
    (10.0.2.2 ist der Host aus Sicht der VM; z. B. 'python3 -m http.server 8000' im Preseed-Ordner)
  - Platten-Merkmale im Installer prüfen: in einem zweiten Terminal
      dev/vm-test.sh vt 2      (dann im VM-Fenster Enter drücken)
      grep . /sys/block/*/queue/rotational
USAGE
}

# kurzer Pfad, weil Unix-Sockets maximal 107 Zeichen erlauben
monitor_sock() { echo "/tmp/aun-${VM_NAME:-vm}-$1.sock"; }

die() { echo "Fehler: $*" >&2; exit 1; }

find_ovmf() {
  local dir
  for dir in /usr/share/edk2/x64 /usr/share/edk2-ovmf/x64 /usr/share/OVMF /usr/share/edk2/ovmf /usr/share/ovmf; do
    for code in OVMF_CODE.4m.fd OVMF_CODE_4M.fd OVMF_CODE.fd; do
      if [ -f "$dir/$code" ]; then
        OVMF_CODE=$dir/$code
        # passende VARS-Vorlage zum CODE-Namen
        local vars=${code/CODE/VARS}
        [ -f "$dir/$vars" ] && { OVMF_VARS=$dir/$vars; return 0; }
      fi
    done
  done
  return 1
}

fetch() {
  mkdir -p "$VM_DIR"
  local sums name expected
  sums=$(curl -fsSL "$ISO_BASE/SHA256SUMS")
  # nur das reguläre netinst-ISO (nicht edu/mac)
  read -r expected name < <(echo "$sums" | grep -E ' debian-[0-9.]+-amd64-netinst\.iso$' | head -n1)
  [ -n "${name:-}" ] || die "Kein netinst-ISO in $ISO_BASE/SHA256SUMS gefunden"
  if [ ! -f "$VM_DIR/$name" ]; then
    curl -fL --progress-bar -o "$VM_DIR/$name.part" "$ISO_BASE/$name"
    mv "$VM_DIR/$name.part" "$VM_DIR/$name"
  fi
  echo "$expected  $VM_DIR/$name" | sha256sum -c -
  ln -sf "$name" "$VM_DIR/debian-netinst.iso"
  echo "ISO bereit: $VM_DIR/debian-netinst.iso"
  echo "Hinweis: SHA256SUMS wurde nicht per GPG geprüft (SHA256SUMS.sign)."
}

# Preseed für autoinstall bauen und per HTTP bereitstellen (10.0.2.2:8000 aus Sicht der VM)
serve_preseed() {
  local www=$VM_DIR/www repo=$SCRIPT_DIR/.. key=${SSH_PUBKEY:-$HOME/.ssh/id_ed25519.pub}
  [ -f "$key" ] || die "SSH-Schlüssel fehlt: $key (SSH_PUBKEY setzen)"
  mkdir -p "$www"
  cp "$repo/installer/select-disk.sh" "$www/"
  cp "$key" "$www/authorized_keys"
  local early='wget -qO /tmp/select-disk.sh http://10.0.2.2:8000/select-disk.sh \&\& AUN_YES=1 sh /tmp/select-disk.sh'
  local late='mkdir -p /target/home/nasadmin/.ssh \&\& wget -qO /target/home/nasadmin/.ssh/authorized_keys http://10.0.2.2:8000/authorized_keys \&\& chmod 700 /target/home/nasadmin/.ssh \&\& in-target chown -R nasadmin:nasadmin /home/nasadmin/.ssh'
  sed -e "s|@EARLY_CMD@|$early|" -e "s|@LATE_CMD@|$late|" "$repo/installer/preseed.cfg.in" > "$www/preseed.cfg"
  cat "$SCRIPT_DIR/preseed-dev.cfg" >> "$www/preseed.cfg"
  python3 -m http.server 8000 --bind 127.0.0.1 --directory "$www" >/dev/null 2>&1 &
  PRESEED_PID=$!
}

# Kernel und Initrd des Installers aus dem ISO holen
extract_kernel() {
  local iso=$1 out=$VM_DIR/kernel
  [ -f "$out/install.amd/initrd.gz" ] && [ "$out/install.amd/initrd.gz" -nt "$iso" ] && return 0
  mkdir -p "$out"
  if command -v bsdtar >/dev/null; then
    bsdtar -xf "$iso" -C "$out" install.amd/vmlinuz install.amd/initrd.gz
  elif command -v 7z >/dev/null; then
    7z x -y -o"$out" "$iso" install.amd/vmlinuz install.amd/initrd.gz >/dev/null
  else
    die "bsdtar oder 7z wird zum Auspacken des ISOs gebraucht"
  fi
  chmod u+w "$out/install.amd"/*
  touch "$out/install.amd/initrd.gz"
}

main() {
  local cmd=${1:-}
  [ -n "$cmd" ] || { usage; exit 1; }
  shift || true
  case "$cmd" in
    -h|--help|help) usage; exit 0 ;;
    fetch) fetch; exit 0 ;;
    vt)
      local n=${1:?Konsolennummer fehlt} sock
      sock=$(monitor_sock "${2:-1}")
      [ -S "$sock" ] || die "Keine laufende VM für Szenario ${2:-1} (Monitor-Socket $sock fehlt)"
      python3 - "$sock" "$n" <<'PY'
import socket, sys, time
s = socket.socket(socket.AF_UNIX)
s.connect(sys.argv[1])
time.sleep(0.3)
s.send(f"sendkey ctrl-alt-f{sys.argv[2]}\n".encode())
time.sleep(0.3)
PY
      exit 0 ;;
    clean) rm -rf "${VM_DIR:?}"/*.qcow2 "$VM_DIR"/*.img "$VM_DIR"/OVMF_VARS*.fd; echo "Testplatten gelöscht (ISO bleibt)."; exit 0 ;;
    install|boot|autoinstall) ;;
    *) usage; exit 1 ;;
  esac

  local scenario=${1:-}
  [ -n "$scenario" ] || die "Szenario fehlt"
  shift
  local iso=$VM_DIR/debian-netinst.iso headless=0 print=0
  while [ $# -gt 0 ]; do
    case "$1" in
      --iso) iso=${2:?--iso braucht eine Datei}; shift 2 ;;
      --headless) headless=1; shift ;;
      --print) print=1; shift ;;
      *) die "Unbekannte Option: $1" ;;
    esac
  done

  # Szenario auswerten
  local firmware=uefi sys=ssd data=hdd data2=0 label=0
  case "$scenario" in
    1) ;;
    2) firmware=bios ;;
    3) sys=nvme; data2=1 ;;
    4) data=ssd ;;
    5) data=none ;;
    8) label=1 ;;
    nodata) data=none ;;
    *) die "Unbekanntes Szenario: $scenario" ;;
  esac
  # NO_DATA=1: installierte VM ohne Datenplatte starten (Testmatrix 7)
  [ "$cmd" = boot ] && [ "${NO_DATA:-0}" = 1 ] && data=none data2=0

  mkdir -p "$VM_DIR"
  local sys_img=$VM_DIR/sys-$scenario.qcow2 data_img=$VM_DIR/data-$scenario.qcow2
  local data2_img=$VM_DIR/data2-$scenario.qcow2

  if [ "$cmd" = install ] || [ "$cmd" = autoinstall ]; then
    [ -e "$iso" ] || die "ISO fehlt: $iso (erst '${0##*/} fetch' ausführen)"
    rm -f "$sys_img" "$data_img" "$data2_img" "$VM_DIR/data-$scenario.img" "$VM_DIR/OVMF_VARS-$scenario.fd"
    qemu-img create -q -f qcow2 "$sys_img" "$SYS_SIZE"
    [ "$data2" = 1 ] && qemu-img create -q -f qcow2 "$data2_img" "$DATA_SIZE"
    if [ "$data" != none ]; then
      if [ "$label" = 1 ]; then
        command -v mkfs.ext4 >/dev/null || die "mkfs.ext4 fehlt (e2fsprogs) für Szenario 8"
        # Dateisystem mit Label direkt auf rohem Image, dann als qcow2 einbinden
        data_img=$VM_DIR/data-$scenario.img
        truncate -s "$DATA_SIZE" "$data_img"
        mkfs.ext4 -q -F -L AUNDATA "$data_img"
      else
        qemu-img create -q -f qcow2 "$data_img" "$DATA_SIZE"
      fi
    fi
  else
    [ -f "$sys_img" ] || die "Keine installierte VM für Szenario $scenario (erst 'install')"
    [ -f "$data_img" ] || [ -f "$VM_DIR/data-$scenario.img" ] || [ "$data" = none ] || die "Datenplatte fehlt"
    [ -f "$VM_DIR/data-$scenario.img" ] && data_img=$VM_DIR/data-$scenario.img
  fi
  local data_fmt=qcow2
  [ "${data_img##*.}" = img ] && data_fmt=raw

  local args=(-m "$RAM" -smp 2 -device ahci,id=ahci
    -nic "user,hostfwd=tcp::${SSH_PORT:-2222}-:22,hostfwd=tcp::${HTTPS_PORT:-8443}-:443,hostfwd=tcp::${COCKPIT_PORT:-9090}-:9090")
  # CPU_MODEL: z. B. qemu64 statt host (lokal mit Kernel 7.1/Ryzen 2700X beschädigte Daten in der VM)
  [ -w /dev/kvm ] && args+=(-enable-kvm -cpu "${CPU_MODEL:-host}")

  if [ "$firmware" = uefi ]; then
    find_ovmf || die "OVMF nicht gefunden (Paket edk2-ovmf bzw. ovmf installieren)"
    local vars=$VM_DIR/OVMF_VARS-$scenario.fd
    [ -f "$vars" ] || cp "$OVMF_VARS" "$vars"
    args+=(-drive "if=pflash,format=raw,readonly=on,file=$OVMF_CODE" -drive "if=pflash,format=raw,file=$vars")
  fi

  # Systemplatte (SSD: rotation_rate=1, NVMe meldet sich selbst als nicht rotierend)
  if [ "$sys" = nvme ]; then
    args+=(-drive "if=none,id=sys,format=qcow2,file=$sys_img${DRIVE_OPTS:-}" -device nvme,drive=sys,serial=aunnvme0)
  else
    args+=(-drive "if=none,id=sys,format=qcow2,file=$sys_img${DRIVE_OPTS:-}" -device ide-hd,drive=sys,bus=ahci.0,rotation_rate=1,serial=aunsys0)
  fi
  # Datenplatte (HDD: rotation_rate=7200)
  case "$data" in
    hdd) args+=(-drive "if=none,id=data,format=$data_fmt,file=$data_img${DRIVE_OPTS:-}" -device ide-hd,drive=data,bus=ahci.1,rotation_rate=7200,serial=aundata0) ;;
    ssd) args+=(-drive "if=none,id=data,format=$data_fmt,file=$data_img${DRIVE_OPTS:-}" -device ide-hd,drive=data,bus=ahci.1,rotation_rate=1,serial=aundata0) ;;
  esac
  # zweite HDD (ahci.2 bleibt für das CD-Laufwerk frei)
  [ "$data2" = 1 ] && args+=(-drive "if=none,id=data2,format=qcow2,file=$data2_img${DRIVE_OPTS:-}" -device ide-hd,drive=data2,bus=ahci.3,rotation_rate=7200,serial=aundata1)
  if [ "$cmd" = install ]; then
    args+=(-drive "if=none,id=cd,media=cdrom,readonly=on,file=$iso" -device ide-cd,drive=cd,bus=ahci.2 -boot order=dc)
  elif [ "$cmd" = autoinstall ]; then
    extract_kernel "$iso"
    args+=(-drive "if=none,id=cd,media=cdrom,readonly=on,file=$iso" -device ide-cd,drive=cd,bus=ahci.2
      -kernel "$VM_DIR/kernel/install.amd/vmlinuz" -initrd "$VM_DIR/kernel/install.amd/initrd.gz"
      -append "auto=true priority=critical url=http://10.0.2.2:8000/preseed.cfg vga=788 --- quiet"
      -no-reboot)
  fi
  args+=(-monitor "unix:$(monitor_sock "$scenario"),server,nowait")
  [ "$headless" = 1 ] && args+=(-display none -serial mon:stdio)
  # zusätzliche QEMU-Optionen, z. B. QEMU_EXTRA="-monitor unix:/tmp/mon.sock,server,nowait"
  # shellcheck disable=SC2206
  [ -n "${QEMU_EXTRA:-}" ] && args+=($QEMU_EXTRA)

  if [ "$print" = 1 ]; then
    printf 'qemu-system-x86_64'; printf ' %q' "${args[@]}"; echo
    exit 0
  fi
  if [ "$cmd" = autoinstall ]; then
    serve_preseed
    trap 'kill "$PRESEED_PID" 2>/dev/null' EXIT
    echo "Automatische Installation, Szenario $scenario ($firmware). Die VM schaltet sich danach ab."
    qemu-system-x86_64 "${args[@]}"
    echo "Fertig. Starten mit: ${0##*/} boot $scenario, dann ssh -p ${SSH_PORT:-2222} nasadmin@localhost"
    exit 0
  fi
  echo "Starte Szenario $scenario ($cmd, $firmware). SSH nach der Installation: ssh -p ${SSH_PORT:-2222} <benutzer>@localhost"
  exec qemu-system-x86_64 "${args[@]}"
}

main "$@"
