# Restoring the birdcam Pi after an SD card failure

What survives an SD card failure:

| Item | Where | Survives |
|---|---|---|
| Code, systemd units, scripts | GitHub | yes |
| Species model (`model/garden_birds.onnx`), fine-tune checkpoint | GitHub | yes |
| MobileNetSSD detector | re-downloaded by `scripts/install_models.sh` | yes |
| Captures and `corrections.json` | USB drive labelled `birdcam-usb` | yes (no copy of the drive itself) |
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
4. persistent journald logs (masks Raspberry Pi OS' volatile default)
5. Wi-Fi power save off (it made SSH and the gallery intermittently unreachable)
6. boot to `multi-user.target` (no desktop)
7. models (`scripts/install_models.sh`)
8. birdcam services and timers (`scripts/install_services.sh`)
9. Tailscale, node name `oaso` (open the printed link to authorise)

## 4. Check

```bash
ssh birdcam 'systemctl is-active birdcam birdcam-gallery birdcam-gallery-admin; /usr/sbin/iw dev wlan0 get power_save; ls ~/birdcam/captures | wc -l'
```

Expected: three `active`, `Power save: off`, and the capture count of the USB drive.
