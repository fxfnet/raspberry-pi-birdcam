# Restoring the birdcam Pi or its data

Two situations:

- **the SD card died**: sections 1 to 4 below;
- **the Pi runs and some data must come back from macaron** (a photo deleted
  by mistake, a damaged `corrections.json`, a lost USB drive): section
  "Restoring from the macaron backup while the Pi is running".

The backup lives on macaron in `/Users/macaron/birdcam_backups/`
(`captures/` and `corrections.json`).


What survives an SD card failure:

| Item | Where | Survives |
|---|---|---|
| Code, systemd units, scripts | GitHub | yes |
| Species model (`model/garden_birds.onnx`), fine-tune checkpoint | GitHub | yes |
| MobileNetSSD detector | re-downloaded by `scripts/install_models.sh` | yes |
| Captures and `corrections.json` | USB drive labelled `birdcam-usb` | yes |
| Bird pictures and `corrections.json` (not motion pictures) | copied hourly to macaron, `~/birdcam_backups/` | yes, even if the USB drive dies |
| System configuration (below) | SD card only | rebuilt by `scripts/setup_system.sh` |

## 1. Flash a new card

Raspberry Pi Imager, Raspberry Pi OS (64-bit, Debian Trixie), with in the
customisation screen:

- hostname `oaso`, user `fxf`
- Wi-Fi SSID and password (not stored in this repo)
- SSH enabled

## 2. SSH access from the Mac

The Mac uses a dedicated key for automation (`Host birdcam` in `~/.ssh/config`):

```bash
ssh-keygen -R 192.168.1.40
ssh-copy-id -i ~/.ssh/id_ed25519_birdcam.pub fxf@192.168.1.40
ssh birdcam hostname   # must print oaso
```

Tailscale: remove the dead `oaso` machine in the Tailscale admin console
(Machines) first, otherwise the new one is registered as `oaso-1`.

## 3. Clone and run the setup script

With the `birdcam-usb` drive plugged in (the script stops if it is missing):

```bash
ssh -t birdcam
git clone https://github.com/fxfnet/raspberry-pi-birdcam.git ~/birdcam
bash ~/birdcam/scripts/setup_system.sh   # asks for the sudo password
sudo reboot
```

The script is idempotent and can be re-run. It sets up:

1. packages (Picamera2, OpenCV, NumPy, Flask)
2. the USB drive mount (`/mnt/birdcam-usb`, `nofail`) and the `captures` and
   `corrections.json` symlinks into `~/birdcam`
3. passwordless sudo limited to `systemctl` and `journalctl`
   (`/etc/sudoers.d/birdcam-fxf`, validated with `visudo -c`)
4. persistent journald logs capped at 100 MB (masks Raspberry Pi OS' volatile
   default; uncapped, the journal grows without limit and wears the card)
5. Wi-Fi power save off (it made SSH and the gallery intermittently unreachable)
6. boot to `multi-user.target` (no desktop)
7. models (`scripts/install_models.sh`)
8. the backup key `~/.ssh/id_ed25519_backup`; if macaron refuses it, the script
   prints the public key to add to `~/.ssh/authorized_keys` on macaron
9. birdcam services and timers (`scripts/install_services.sh`), including the
   hourly backup to macaron
10. Tailscale, node name `oaso` (open the printed link to authorise)

## 4. Check

```bash
ssh birdcam 'systemctl is-active birdcam birdcam-gallery birdcam-gallery-admin; /usr/sbin/iw dev wlan0 get power_save; ls ~/birdcam/captures | wc -l'
```

Expected: three `active`, `Power save: off`, and the capture count of the USB drive.

## Restoring from the macaron backup while the Pi is running

### What the backup is, and what it is not

`scripts/backup_usb.sh` copies the USB drive to macaron every hour with
`rsync`, **without `--delete`**. It is a mirror that only grows, not a set of
dated snapshots:

- **one copy of `corrections.json`**, the one of the last hour. The file is
  append-only, so this latest copy holds every correction made before it;
- **a photo deleted in the admin stays on macaron**: this is what makes a
  deletion recoverable;
- **a renamed photo exists twice on macaron.** Starring, retagging and
  correcting the species rename the file; the backup keeps the old name next to
  the new one. The timestamp in the name (`bird_20260920_143512_417...`)
  identifies the photo across renames.
- motion pictures (`motion_*`) are not backed up.

### 1. Stop the backup first

```bash
ssh birdcam
sudo systemctl stop birdcam-backup.timer
```

If the drive holds a damaged `corrections.json`, the next hourly run would copy
it over the only good copy on macaron. Stopping the timer comes before anything
else.

### 2. Stop what writes to the drive

```bash
sudo systemctl stop birdcam birdcam-gallery-admin
```

`birdcam` writes captures, the admin renames and deletes photos and appends to
`corrections.json`. The public gallery only reads and can keep running.

### 3a. Bring back a deleted photo

Find it on macaron by its timestamp, and make sure it is not still on the drive
under another name:

```bash
ssh -i ~/.ssh/id_ed25519_backup macaron@192.168.1.177 'ls birdcam_backups/captures/ | grep 20260920_1435'
ls /mnt/birdcam-usb/captures/ | grep 20260920_1435
```

If the drive has nothing with that timestamp, copy the file back:

```bash
rsync -a --ignore-existing -e "ssh -i ~/.ssh/id_ed25519_backup"   macaron@192.168.1.177:birdcam_backups/captures/bird_20260920_143512_417.jpg   /mnt/birdcam-usb/captures/
```

Restore photo by photo. A bulk `rsync` of the whole `captures/` folder would
also bring back the old name of every renamed photo, and they would show up
twice in the gallery.

### 3b. Bring back `corrections.json`

```bash
mv /mnt/birdcam-usb/corrections.json /mnt/birdcam-usb/corrections.json.$(date +%F_%H%M).bak
rsync -a -e "ssh -i ~/.ssh/id_ed25519_backup"   macaron@192.168.1.177:birdcam_backups/corrections.json /mnt/birdcam-usb/
python3 -m json.tool /mnt/birdcam-usb/corrections.json > /dev/null && echo valid
```

Write to `/mnt/birdcam-usb/corrections.json`, never to `~/birdcam/corrections.json`:
the latter is a symlink to the drive, and replacing it would leave the gallery
writing to the SD card. Corrections made in the admin after the last backup are
lost; the damaged file set aside keeps them if they can be read.

### 4. Restart

```bash
sudo systemctl start birdcam birdcam-gallery-admin birdcam-backup.timer
systemctl is-active birdcam birdcam-gallery birdcam-gallery-admin birdcam-backup.timer
```

Expected: four `active`.

## If the USB drive is lost too

Format a new drive (`sudo mkfs.ext4 -L birdcam-usb /dev/sdX1`), run the setup
script, then copy the backup back from macaron:

```bash
ssh birdcam 'rsync -a -e "ssh -i ~/.ssh/id_ed25519_backup" macaron@192.168.1.177:birdcam_backups/ /mnt/birdcam-usb/'
```

This bulk copy also brings back every photo deleted in the admin, and the old
name of every renamed photo (see "What the backup is" above): expect duplicates
in the gallery, to clean up in the admin. Motion pictures are not in the backup.

Motion pictures are not backed up; they are purged after 14 days anyway.
