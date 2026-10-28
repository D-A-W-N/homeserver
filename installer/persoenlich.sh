#!/bin/sh
# Persönliches ISO (build-iso.sh --config, D24), late_command im Installer: Konfiguration und
# Erststart ins neue System; aunserver-erststart.service richtet beim ersten Start alles ein.
set -e
q=/cdrom/aunserver-installer/persoenlich
install -d -m 0700 /target/etc/aunserver /target/etc/aunserver/secrets
install -m 0600 "$q/config.yml" /target/etc/aunserver/config.yml
install -m 0600 "$q/erststart.env" /target/etc/aunserver/erststart.env
[ -f "$q/restic_password" ] && install -m 0600 "$q/restic_password" /target/etc/aunserver/secrets/restic_password
cp /target/opt/aunserver/installer/aunserver-erststart.service /target/etc/systemd/system/
in-target systemctl enable aunserver-erststart.service
