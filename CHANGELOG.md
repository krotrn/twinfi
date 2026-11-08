# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.13.3] - 2026-11-08

### Added

- *Hide tray icon while the hotspot is off* in Settings → Startup. KDE
  Plasma then moves the icon into its hidden icons until the hotspot starts.
  It's off by default, because waybar and some other bars hide such icons
  completely.

### Fixed

- The tray icon no longer looks like the network applet's Wi-Fi icon. It
  showed the theme's Wi-Fi icons, so with Wi-Fi off it looked like a
  full-signal connection. It now shows twinfi's own icon: faded and struck
  through while the hotspot is off, and with a "!" when twinfi can't report
  its status.
- The tray icon follows the panel's text colour on KDE Plasma. On a dark
  panel it was drawn dark grey and was hard to see.

### Changed

- The desktop app no longer needs Pillow. The share dialog draws its QR code
  directly from python-qrcode, so the packages, `get.sh` and the `gui` extra
  drop `python3-pil` / `python-pillow`. This also ends the Pillow security
  advisories against the locked development dependencies: no fixed Pillow
  supports Python 3.10, which twinfi still runs on (Ubuntu 22.04).

## [0.13.2] - 2026-10-14

### Fixed

- zsh completion for `twinfi` works after upgrading from apsta. The Arch and
  Debian packages now also ship `_apsta`, which completes the `apsta` command
  and makes zsh rebuild its stale completion cache. Before, swapping `_apsta`
  for `_twinfi` kept zsh's file count the same, so it never noticed. On 0.13.0
  or 0.13.1, `rm ~/.zcompdump*` and opening a new shell fixes it right away.

## [0.13.1] - 2026-10-14

### Security

- `twinfi qr` no longer writes the hotspot password to `/var/log/twinfi.log`.
  Without python-qrcode installed it printed the QR text, which contains the
  password, and also logged it. The log is readable only by root. If you ran
  `twinfi qr` that way, delete the `QR payload` lines from the log, or change
  the password with `sudo twinfi config --generate-password`.
- `twinfi update` on Python older than 3.10.12 now refuses a source archive
  containing links or paths outside the folder it unpacks into.

## [0.13.0] - 2026-10-13

### Changed

- **apsta is now called twinfi.** The command, the desktop app, the
  packages and the settings directory (`/etc/twinfi`) use the new name, and
  environment variables start with `TWINFI_`. The `apsta` command still works
  for now: it runs twinfi and prints a reminder.
- The first `sudo twinfi` command after the update moves `/etc/apsta` to
  `/etc/twinfi`, replaces a boot service set up by `apsta enable` (systemd
  units are enabled under the new name; OpenRC and runit ask you to run
  `sudo twinfi enable`) and renames an `[apsta]` section in `pacman.conf`.
- Moving over, by install route:
  - Ubuntu PPA: `sudo apt upgrade`. The `apsta` package becomes a
    transitional package that installs twinfi; remove it whenever you like.
  - Arch pacman repository: `sudo pacman -Syu` replaces apsta with twinfi.
  - Release `.deb`: `sudo apsta update` installs twinfi.
  - pipx: `sudo pipx uninstall --global apsta && sudo pipx install --global twinfi`.
  - pip: `pip install --upgrade apsta` installs twinfi (the last `apsta`
    release on PyPI depends on it); use the `twinfi` command afterwards.
  - `install.sh` or anything else: run `get.sh` again, which removes the
    apsta install it replaces.
- A hotspot started by apsta can't be stopped by twinfi; stop it before
  updating, or restart the computer.

### Fixed

- The boot service failed at every start until settings had been saved once:
  its sandbox made `/etc` read-only and skipped the settings directory when it
  didn't exist yet. systemd now creates `/etc/twinfi` for it.

## [0.12.0] - 2026-10-10

### Added

- One-command install for any distribution:
  `curl -fsSL https://raw.githubusercontent.com/krotrn/apsta/main/get.sh | sh`.
  It uses the pacman repository, the PPA or the release `.deb` where they
  exist and otherwise installs from source with the distribution's
  dependencies, adding hostapd, dnsmasq and (in a graphical session) the
  desktop app's libraries.
- The Arch and Debian/Ubuntu packages install bash, zsh and fish completions,
  so `apsta <Tab>` works right after installing.
- `sudo apsta update` (or `upgrade`) installs the latest release and
  `sudo apsta uninstall` removes apsta completely: its boot service, package,
  pacman repository or PPA, settings and log (`--keep-config` keeps the
  settings). Both go through whatever installed apsta: the pacman repository,
  the PPA, the release `.deb` (checked against `SHA256SUMS`) or `install.sh`.
- Shell completion suggests your profile names for `apsta profile show`, `use`
  and `delete`, and for `apsta profile create --from`.

## [0.11.1] - 2026-10-10

### Changed

- When another nftables chain drops forwarded traffic, the warning that clients
  may get no internet is now one of the hotspot's notes, so `apsta status`
  (and `status --json`, and so the desktop app) shows it for as long as the
  hotspot runs, not only `apsta start`.
- `apsta recommend` checks the same card as `apsta detect` (the one connected
  to WiFi first), instead of possibly a different one.
- `apsta config --set active_profile=` (empty) says a profile name is needed.

## [0.11.0] - 2026-10-06

### Added

- System tray icon for the desktop app (StatusNotifierItem, so it works on KDE
  Plasma, Xfce, Cinnamon, MATE, Budgie, LXQt, waybar and other Wayland bars,
  and GNOME with the AppIndicator extension). It shows the hotspot's state and
  device count; its menu starts/stops and shares the hotspot, switches profile
  and band, turns *Start automatically* on or off, and opens the device list or
  Settings. With a tray, closing the window keeps the app running there.
- *Show in the tray at login* (Settings), or `apsta-gtk --background`, starts
  the app straight into the tray.

### Fixed

- Turning off *Start automatically* (`apsta disable`) no longer stops a
  hotspot the service had started. On systemd the watcher `apsta start` uses
  takes over; on OpenRC and runit the hotspot keeps running unwatched until
  you stop it.

## [0.10.0] - 2026-10-06

### Added

- AppStream metainfo (`com.github.apsta.Gtk.metainfo.xml`), installed by the
  .deb, the Arch package, `install.sh` and the wheel, so software centers such
  as GNOME Software and KDE Discover list the app.
- Documentation website at [krotrn.github.io/apsta](https://krotrn.github.io/apsta/).

### Changed

- README: a one-line definition, a comparison with other hotspot tools, a
  supported-hardware table and an FAQ; it now renders correctly on PyPI.

## [0.9.0] - 2026-10-05

### Added

- Wi-Fi Direct fallback (method `p2p`), as Windows' Mobile Hotspot does: when
  your WiFi is on a channel the card can't host on (radar/DFS channels 52–144,
  such as campus networks, 5 GHz channels the firmware marks "no IR", or
  6 GHz), cards that can run a Wi-Fi Direct group on a second channel (most
  Intel cards) now give the hotspot a channel of its own instead of refusing.
  Same name, password, DHCP and NAT as hostapd mode; the radio switches
  between the two channels, so they share its speed. apsta asks
  NetworkManager's wpa_supplicant for the group through its control socket
  (Arch, Debian, Ubuntu) or over D-Bus with the Python library jeepney
  (Fedora, openSUSE, Alpine, Void); the password is never on a command line.
  `apsta detect` and the GUI show whether it's available and what's missing.
  See [docs/wifi-direct.md](docs/wifi-direct.md).
- `method` setting: choose how the hotspot runs (`auto`, `hostapd`, `nmcli`,
  `p2p`, `nmcli-single`) for `start`, the app, autostart and the watcher, not
  only per run with `--method`. With a method that has its own channel
  (`p2p`), your `band` and `channel` settings are always followed.
- Notes that explain every choice: which method and why the others were
  skipped, which channel and why, and any setting that couldn't be followed
  (for example *"Your band setting is 5 GHz, but the hotspot is on 2.4 GHz
  because it shares your WiFi's channel"*). Shown by `apsta start` and
  `apsta status`, in `status --json` (`hotspot.notes`), in the app's new *Why
  it runs this way* section, and written to `/var/log/apsta.log`.
- App: *Method* and *Channel* choices in Settings.
- Optional dependency `jeepney` (`pip install "apsta[p2p]"`; recommended by
  the .deb, optional on Arch).

### Changed

- `channel` is now followed whenever the hotspot has a channel of its own.
  Before, a scan for the least crowded channel overrode it. The new default
  `channel=auto` keeps that scan; profiles from earlier versions that still
  have the old default (`6`) become `auto`.
- On 5 GHz, the least crowded channel is chosen from 149–165 as well as
  36–48, and only among channels the card may start a network on (Intel
  cards often block 36–48).

## [0.8.0] - 2026-10-05

### Added

- `hidden` setting: don't broadcast the network name (hostapd and
  NetworkManager). The QR code carries the hidden flag so phones still join.
- `allowed_macs` setting: only the listed devices may join, even with the
  password (hostapd mode). NetworkManager can't enforce it, so apsta refuses
  those methods instead of starting an open hotspot. Blocking an allowlisted
  client still works.
- `apsta qr`: a QR code in the terminal for joining with a phone camera.
- GUI: "Hide network name" switch in Settings.

### Fixed

- A hotspot started with `apsta start` or the GUI no longer cuts off your
  internet when the WiFi network changes channel (for example a phone hotspot
  switching to 5 GHz). `start` now runs the watcher in the background
  (`apsta-watch.service`, systemd only): it stops the hotspot so the WiFi can
  reconnect, and brings it back once the network is on a channel the card can
  host on. Before, the laptop stayed disconnected until `apsta stop`.
- The watcher no longer holds the command lock while waiting for WiFi to
  reconnect, so `apsta stop` and the GUI aren't blocked meanwhile.
- The service's and the watcher's messages reach the journal as they happen,
  not in blocks when Python's output buffer fills.
- `--allow-disconnect` hotspots are no longer restarted every 20 s by the
  service because the WiFi they dropped on purpose was "lost".

### Documentation

- `docs/5ghz-wifi.md`: on Intel cards the firmware's "no IR" rules can be
  stricter than the law; how to check, and the driver patch (maintained by
  linux-wifi-hotspot) that hands the decision back to the kernel, with its
  costs.
- `docs/5ghz-wifi.md`: what happens when the network switches band while the
  hotspot is running (phone hotspots do this by themselves), and how the
  service recovers.
- Mermaid diagrams in the README (method selection), `docs/ARCHITECTURE.md`
  (layers, start and rollback, the watcher, the GUI's data flow),
  `docs/5ghz-wifi.md` and `CONTRIBUTING.md` (release pipeline).

## [0.7.1] - 2026-10-04

### Fixed

- Hosting on a channel the WiFi card isn't allowed to start a network on.
  Intel cards mark 5 GHz channels 36–144 "no IR"; when the card has to share
  the WiFi connection's channel and that channel is one of them, `start` used
  to try hostapd and NetworkManager and fail with driver errors. apsta now
  reads which channels allow an AP, refuses up front with the fix (switch the
  network to 2.4 GHz), and `--allow-disconnect` hosts on an allowed channel
  instead. When free to choose, it only picks allowed channels (e.g. 5 GHz
  149–165) and falls back to 2.4 GHz.
- `detect` warns about this before you start, and shows "Hotspot on 5 GHz";
  the desktop app's hardware report too. `detect --json` adds
  `capability.ap_frequencies` and `verdict.warnings`.
- NetworkManager fallback: wait until NetworkManager has adopted the new
  interface instead of failing with "No suitable device found".

### Documentation

- `docs/5ghz-wifi.md`: why the hotspot can't start while your WiFi is on some
  5 GHz channels, how to check, and the fixes. Linked from the error, from
  `apsta detect` and from the README.

## [0.7.0] - 2026-10-04

Rewrite of the internals around a layered architecture
(see `docs/ARCHITECTURE.md`), fixing a series of correctness, reliability and
security problems.

### Upgrade notes

- **Stop a running hotspot before upgrading from 0.6** (`sudo apsta stop`).
  Runtime state moved from `/etc/apsta/config.json` to `/run/apsta`. The .deb
  and Arch packages do this for you.
- `--force` is now an alias of `--allow-disconnect`. It no longer skips the
  hostapd method; it only *allows* falling back to a mode that drops WiFi.
- `status --disconnect/--limit-client/--use-profile` still work but are
  deprecated. Use `apsta clients …` and `apsta profile use`.
- `detect --json`: `supports_ap_sta_concurrent`/`supports_ap_sta_split` are
  replaced by `ap_sta` and `same_channel_required`.
- Python ≥ 3.10 is required (3.9 reached end of life in October 2025).

### Fixed

- AP+STA detection now applies per-group limits. Cards whose AP and managed
  types share a group limited to one interface are no longer reported as
  concurrent, and multi-channel cards are no longer reported as unsupported.
- hostapd config sets the regulatory `country_code` (5 GHz no longer fails on
  the world domain) and enables 802.11n/ac + WMM (no more 54 Mbps cap).
- 6 GHz WiFi connections are detected; iw ≥ 6 frequency output (`5180.0`) is parsed.
- Start is all-or-nothing: partial failures roll back, and dnsmasq, IP and
  NAT failures are errors, not warnings.
- Starting twice no longer orphans hostapd/dnsmasq; stale state after a crash
  is cleaned up automatically.
- Hotspot subnet is chosen to avoid existing networks. DNS uses the system
  resolver instead of hard-coded 8.8.8.8.
- NAT works with firewalld, nftables, ufw and docker, and through any uplink
  (ethernet, VPN), not only the WiFi interface. `ip_forward` is restored on stop.
- Client list shows associated stations instead of stale DHCP leases.
  Disconnect works (hostapd control socket); clients can be blocked.
- Per-client bandwidth limits no longer overwrite each other. Limits can be removed.
- The resume hook waits for WiFi to reassociate before choosing a channel.
- config.json is written atomically. A corrupt file is backed up instead of
  silently replaced by defaults.
- GUI no longer overwrites fields while you type.
- Found on real hardware (Intel AX201, NetworkManager 1.58):
  - NetworkManager adopted the new AP interface and its wpa_supplicant blocked
    hostapd ("Match already configured"). apsta now marks the interface
    unmanaged through a runtime NetworkManager config before creating it.
  - A hotspot was reported live although hostapd had failed: a `__ap`
    interface reports type AP immediately. apsta now waits for hostapd's
    `state=ENABLED`, and status checks look for an actual broadcasting SSID.
  - Failing hostapd/dnsmasq units restarted forever; now at most 5 times a minute.
  - The regulatory country now comes from the card's self-managed domain (e.g.
    `IN`) when the global one is the world domain `00`.
  - The P2P-device entry in `iw dev` no longer corrupts the interface list.
- Added `scripts/hardware_check.sh` for real-hardware testing.
- `--json` output is clean JSON: progress messages go to stderr (`start --json`
  mixed them into stdout).
- `status --limit-kbps` without `--limit-client` is a usage error instead of a crash.

### Security

- No shared default password: a random one is generated on first start.
- Passwords are no longer printed to the journal or passed on command lines
  (nmcli, pkexec).
- GUI uses `pkexec apsta` with a dedicated polkit action instead of `pkexec sh -c`.
- Runtime files moved from `/tmp` to `/run/apsta`; no `shell=True` anywhere.

### Added

- `apsta run`: foreground supervisor used by the service. It restarts the
  hotspot after resume or a driver reset and follows WiFi channel changes.
- hostapd/dnsmasq run as supervised transient systemd units, with logs in the journal.
- `apsta clients` (list/disconnect/`--block`/unblock/limit/unlimit).
- `apsta start --method`, `--wait-sta`, `--ssid`, `--password-stdin`, `--interface`.
- `apsta config --password-stdin`, `--generate-password`, `--show-password`, repeatable `--set`.
- `apsta status --check` (exit code only).
- `apsta enable` supports OpenRC and runit.
- Shell completions generated from the CLI definition.
- Unit and integration test suites (no root or hardware needed), tests for
  the sleep hook, coverage gate in CI (≥ 94 %).

### GUI

- Redesigned: Hotspot / Devices / Settings tabs. A status hero with one
  start/stop button, a device list with per-device speed limit, disconnect and
  block, a Share dialog (QR code + password, fetched with authentication),
  network settings with band and interface pickers, profiles, a start-at-boot
  toggle, a hardware report, toasts, keyboard shortcuts and an About window.
- Uses the newest libadwaita widgets when present (ToolbarView, adaptive
  tabs with a bottom bar on narrow windows, SwitchRow, ButtonRow, Adw.Dialog
  sheets, AboutDialog, Adw.Spinner) and falls back on older versions.
- Runs on libadwaita ≥ 1.1 / GTK ≥ 4.6. It previously crashed on Ubuntu/Pop!_OS
  22.04, Linux Mint 21 and Debian 12 (`Adw.ToolbarView`, `Adw.Banner`,
  `Adw.EntryRow`). Newer widgets go through `apsta_gui/compat.py`.
- CI builds every view on Ubuntu 22.04, Debian 12, Ubuntu 24.04, Fedora and
  Arch (`scripts/gui_smoke.py`) and uploads screenshots.
- User-supplied text (SSIDs, hostnames) is escaped before display; it was
  previously interpreted as Pango markup.
- pkexec failures are explained (cancelled, not authorized, no polkit agent).
  Shows a helpful window instead of exiting when the CLI isn't installed.
- Works around libadwaita 1.5 (Ubuntu 24.04) collapsing page width when the
  session sets no font DPI. Replaces the deprecated `Gdk.Texture.new_for_pixbuf`.
- Own app icon; the desktop file's `StartupWMClass` now matches the app ID, so
  docks group the window with its launcher.

### Documentation

- `docs/ARCHITECTURE.md`: layers, design decisions, the GUI's structure and
  compatibility strategy, testing.
- `docs/json-output.md`: the `--json` output of every command and exit codes,
  now a documented, stable interface. `detect --json` and `status --json`
  share one interface shape (`type`, not `iftype`).
- `CONTRIBUTING.md` (development, GUI rules, releasing), `SECURITY.md`,
  issue and pull request templates.

### Removed

- `setup.py` (pyproject.toml only), `gtk-ui/` launcher scripts (entry points
  and `install.sh` replace them).

## [0.6.2] and earlier

See the git history.
