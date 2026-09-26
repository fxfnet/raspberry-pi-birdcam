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
`rsync`, **without `--delete`**. It is a mirror that only grows, with no
history:

- **one copy of `corrections.json`, and no older version.** Every hour it is
  replaced by whatever is on the drive, damaged or not. A damage is usually
  noticed later (the admin fails when saving a correction), so macaron may
  already hold the damaged file. Only a Time Machine backup of macaron, if
  there is one, would go further back.
- **a photo deleted in the admin stays on macaron**: this is what makes a
  deletion recoverable;
- **a renamed photo can exist under several names on macaron.** Starring and
  correcting the species rename the file, and the backup keeps every name: a
  photo corrected then starred exists three times. A bird photo retagged as
  motion only keeps its old `bird_` name, since `motion_*` files are not backed
  up; `star_motion_*` files are.

Capture names follow
`bird_<YYYYMMDD_HHMMSS_mmm>_burst<i>_motion<score>_conf<x.xx>_best<label>[_sp<species>_spconf<x.xx>].jpg`,
possibly prefixed with `star_` and suffixed with `_1`. The timestamp with
milliseconds identifies a photo across renames.

### 1. Stop the backup, including a run in progress

```bash
ssh birdcam
sudo systemctl stop birdcam-backup.timer birdcam-backup.service
systemctl is-active birdcam-backup.service   # must print inactive
```

Stopping the timer alone does not stop an `rsync` already running.

### 2. Stop what writes to the drive

```bash
sudo systemctl stop birdcam birdcam-gallery-admin birdcam-restart.timer
```

`birdcam` writes captures; the admin renames and deletes photos and appends to
`corrections.json`; the restart timer would start `birdcam` again at 03:00. The
public gallery only reads and can keep running.

### 3a. Bring back a deleted photo

Search by the full timestamp, on macaron and on the drive:

```bash
ssh -i ~/.ssh/id_ed25519_backup macaron@192.168.1.177 'ls birdcam_backups/captures/ | grep 20260920_143512_417'
ls /mnt/birdcam-usb/captures/ | grep 20260920_143512_417
```

If the drive still has that timestamp under another name, the photo was renamed,
not deleted: restore nothing. Otherwise copy the name listed on macaron. If
several names come up, take the last state of the photo: the `star_` one if it
was starred, the `_spconf1.00` one if its species was corrected by hand. File
dates cannot tell them apart, since renaming and `rsync -a` both keep them.

```bash
rsync -a --ignore-existing -e "ssh -i ~/.ssh/id_ed25519_backup" \
  'macaron@192.168.1.177:birdcam_backups/captures/<exact name from the list>' \
  /mnt/birdcam-usb/captures/
```

Restore photo by photo. A bulk `rsync` of the whole `captures/` folder would
bring back every old name, and the gallery would show duplicates.

### 3b. Bring back `corrections.json`

Fetch and check the macaron copy **before** touching the one on the drive:

```bash
rsync -a -e "ssh -i ~/.ssh/id_ed25519_backup" \
  macaron@192.168.1.177:birdcam_backups/corrections.json /tmp/corrections.json
python3 -c "import json; d = json.load(open('/tmp/corrections.json')); print(len(d), 'entries, last', d[-1]['corrected_at'] if d else '-')"
```

If this fails, or shows fewer entries or an older last date than expected, the
macaron copy is damaged too: stop here, keep the backup timer stopped, and look
for an older version in Time Machine on macaron.

If the copy is good, set the drive's file aside and put the copy in place:

```bash
mv /mnt/birdcam-usb/corrections.json /mnt/birdcam-usb/corrections.json.$(date +%F_%H%M).bak
cp /tmp/corrections.json /mnt/birdcam-usb/corrections.json
```

Write to `/mnt/birdcam-usb/corrections.json`, never to `~/birdcam/corrections.json`:
the latter is a symlink to the drive, and replacing it would leave the gallery
writing to the SD card. Corrections made after the last backup are lost; the
file set aside keeps them if it can still be read.

### 4. Restart

```bash
sudo systemctl start birdcam birdcam-gallery-admin birdcam-restart.timer birdcam-backup.timer
systemctl is-active birdcam birdcam-gallery birdcam-gallery-admin birdcam-restart.timer birdcam-backup.timer
```

Expected: five `active`.

## If the USB drive is lost too

**Order matters.** `setup_system.sh` writes an empty `[]` `corrections.json` on
a new drive and enables the hourly backup, which then replaces the full file on
macaron with that empty one, within minutes of the setup.

1. On macaron, before anything else, keep a dated copy of the file:

   ```bash
   cp -p ~/birdcam_backups/corrections.json ~/birdcam_backups/corrections.json.$(date +%F_%H%M)
   ```

2. Format a new drive (`sudo mkfs.ext4 -L birdcam-usb /dev/sdX1`) and run the
   setup script.

3. Copy the photos back, then the dated `corrections.json` from step 1:

   ```bash
   ssh birdcam
   rsync -a --exclude='corrections.json*' -e "ssh -i ~/.ssh/id_ed25519_backup" \
     macaron@192.168.1.177:birdcam_backups/ /mnt/birdcam-usb/
   rsync -a -e "ssh -i ~/.ssh/id_ed25519_backup" \
     'macaron@192.168.1.177:birdcam_backups/corrections.json.<date from step 1>' \
     /mnt/birdcam-usb/corrections.json
   ```

This bulk copy also brings back every photo deleted in the admin and every old
name of renamed photos: expect duplicates in the gallery, to clean up in the
admin. Motion pictures are not backed up; they are purged after 14 days anyway.
