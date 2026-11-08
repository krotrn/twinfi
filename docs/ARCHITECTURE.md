# Architecture

This document describes how twinfi is put together and why. Read it before a
non-trivial change.

## Layers

```mermaid
flowchart TD
    CLI["<b>twinfi_cli/cli.py</b><br/>argparse, errors → exit codes"]
    GUI["<b>twinfi_gui</b> (GTK 4 / libadwaita)<br/>a client of the CLI:<br/>--json reads, pkexec writes"]
    CMD["<b>cmd/*</b> · present<br/>thin: print results"]
    SVC["<b>services/</b> · use cases<br/>hotspot.py: start / stop / status, strategy selection<br/>detect.py: what the card can do, which methods are ready<br/>watch.py: twinfi run keeps the hotspot healthy<br/>guard.py: runs it behind twinfi start<br/>installation.py: how twinfi was installed, for update / uninstall"]
    CFG["<b>config/</b><br/>model, store, validate<br/>state.py"]
    NET["<b>net/</b><br/>strategies, transaction<br/>hostapd, dnsmasq, nm<br/>firewall, supervisor<br/>iface, subnet, channels, clients<br/>wpa (wpa_supplicant: socket or D-Bus)"]
    HW["<b>hw/</b><br/>combinations, capability<br/>interfaces, usb"]
    CORE["<b>core/</b><br/>shell (argv only), paths, fsutil (atomic)<br/>lock, output, log, errors"]

    CLI --> CMD
    GUI -. "runs twinfi" .-> CMD
    CMD --> SVC
    SVC --> CFG & NET & HW
    CFG & NET & HW --> CORE
```

Dependencies only point downwards. `core` imports nothing from twinfi.
Decisions live in `services`; a `cmd` handler only presents results. It may
still call `config` (settings are edited through `config.model`, which
validates) and `hw` read-only helpers for display directly.

`hw`, `net` and `config` never decide what the user sees:

- **Failures** raise `TwinfiError` subclasses that carry `hints`; `cli.py`
  renders them and maps them to exit codes.
- **Problems worked around** (a MAC that couldn't be set, a cleanup step that
  failed, a corrupt config file) go to `logging.getLogger(__name__).warning`.
  `cli.py` installs the handler (`output.show_library_messages()`) that shows
  them as warnings and mirrors them to the log.
- **Caveats about the running hotspot** become its `notes` (below), so
  `status` and the GUI show them for as long as it runs.

## Key decisions

### Hardware capability comes from interface combinations

`hw/combinations.py` parses `iw phy <phy> info` into `Combination(groups,
total, channels)` and asks one question: can one `AP` and one `managed`
interface exist at the same time? That means placing each requested
interface into a group with spare capacity, within `total`. `#channels <= 1`
means the AP must share the STA's channel. Earlier versions guessed from
whether AP and managed appeared in the same `#{}` group, which was wrong in
both directions. Real driver outputs live in `tests/fixtures/iw/`.

### Strategies + transactions

`net/strategies.py` holds four implementations of one interface
(`unavailable`, `start(ctx, tx)`, `stop(state)`): `hostapd`, `nmcli`
(virtual interface), `p2p` (a Wi-Fi Direct group owner through
wpa_supplicant, `net/wpa.py`: its control socket, or D-Bus where there is no
socket; see [wifi-direct.md](wifi-direct.md)) and `nmcli-single`. `services/hotspot.start` tries them
in order. Each `start` registers an undo step with the `Transaction` after
every side effect, so a failure part-way rolls back to a clean system before
the next strategy is tried.

```mermaid
flowchart TD
    S(["twinfi start"]) --> P["Plan: capability, WiFi channel,<br/>allowed channels, subnet"]
    P -- "WiFi's channel can't host, and no<br/>Wi-Fi Direct or --allow-disconnect" --> E(["HardwareError with hints"])
    P --> N{"Next strategy:<br/>hostapd → nmcli → p2p → nmcli-single"}
    N -- "unavailable" --> N
    N --> T["start(ctx, tx): each side effect<br/>registers its undo step"]
    T -- "all steps OK, hotspot live" --> W["Write /run/twinfi/state.json"] --> D(["Running"])
    T -- "a step fails" --> R["tx.rollback(): undo in reverse order"] --> N
    N -- "none left" --> F(["Error listing what each strategy hit"])
```

`nmcli-single` drops the WiFi connection, so while connected it is only tried
with `--allow-disconnect`.

When the WiFi's channel can't host (DFS, no IR, 6 GHz), the plan picks a
channel of the hotspot's own and marks `sta_channel_usable=False`: `hostapd`
and `nmcli` step aside, leaving `p2p` (cards whose combinations allow a
`P2P-GO` beside `managed` with `#channels >= 2`) and `nmcli-single`. If
neither works, the original channel explanation is raised with their reasons
appended. A `p2p` hotspot records `same_channel_required=False`, so the
watcher doesn't chase the WiFi's channel.

### Settings, decisions and notes

Whatever twinfi decides on its own, the user can set instead, and whatever it
can't follow, it explains:

- **Method**: `--method` for one run, else the profile's `method` setting,
  else `auto` (`hotspot.resolve_method`). The watcher is launched without
  `--method` unless one was given, so it reads the same setting.
- **Channel**: `net/channels.plan()` returns a `ChannelPlan` with the channel,
  the reason in words ("the least crowded nearby", "your channel setting")
  and `notes` for anything asked for but not granted (a channel on the wrong
  band, or one the card may not start a network on).
- `hotspot.build_context()` adds notes the planner can't know: the band
  setting differs from a channel the hotspot must share with the WiFi, or the
  WiFi's channel can't host at all. Methods with a channel of their own
  (`p2p`, `nmcli-single`) follow `band` and `channel` instead of sharing.
- `hotspot.start()` puts a note about the method first (chosen in the
  settings, or which methods were skipped and why), and a strategy may add
  its own (`p2p`: the radio's speed is shared; hostapd and p2p: the
  firewall's caveats).

The notes are stored in `HotspotState.notes`, printed by `twinfi start` and
`twinfi status`, exposed as `hotspot.notes` in `status --json` (so the GUI shows
them under *Why it runs this way*), and logged with the `hotspot_started`
event in `/var/log/twinfi.log`. Each is one plain sentence for the user.

### Runtime state lives in /run

`state.py` writes `HotspotState` to `/run/twinfi/state.json` once the hotspot
is fully up, with everything `stop` needs: interface names, subnet, firewall
backend and its undo data, the previous `ip_forward` value, client limits,
and the notes explaining the choices made at start (below).
`/run` is a tmpfs, so a crash or reboot can't leave a stale "running" record.
On start, a recorded hotspot that is no longer alive is cleaned up first.
Configuration (`/etc/twinfi/config.json`, world-readable) and secrets
(`/etc/twinfi/secrets.json`, 0600) are separate and written atomically.

### Processes are supervised

`net/supervisor.py` runs hostapd and dnsmasq as transient systemd units
(`twinfi-hostapd.service`, `twinfi-dnsmasq.service`, `Restart=on-failure`,
logs in the journal). On non-systemd systems it falls back to pidfiles, and
checks a pid against `/proc/<pid>/cmdline` before signalling it.

### The service watches, not just starts

`twinfi.service` runs `twinfi run --wait-sta 30`. A one-off `twinfi start`
(and so the GUI) launches the same watcher as the transient unit
`twinfi-watch.service` (`services/guard.py`, systemd only), which adopts the
hotspot that is already up; `twinfi stop` stops the watcher before the
hotspot. `services/watch.py` polls every 5 s and `decide()` (a pure function)
restarts the hotspot when:

- it went down (resume from suspend, driver reset, hostapd gave up);
- it shares the WiFi's channel and the WiFi moved to another channel;
- it shares the WiFi's channel and the WiFi has been gone for 20 s.
  The AP may be what stops NetworkManager reconnecting on another channel.

When the watcher is stopped (SIGTERM) it stops the hotspot, unless
`/run/twinfi/keep-hotspot` exists. `twinfi disable` writes that marker while it
stops the service (`cmd/service.py: keeping_hotspot()`), so turning off *Start
automatically* leaves a running hotspot up; on systemd it then launches
`twinfi-watch.service` to keep watching it. The watcher removes the marker as
it reads it, and `disable` removes it after a synchronous stop, so it never
outlives that one stop.

```mermaid
flowchart TD
    Poll(["every 5 s"]) --> St{"state.json present?"}
    St -- "no (twinfi stop)" --> Exit(["exit"])
    St -- "yes" --> Alive{"hotspot alive?"}
    Alive -- "no" --> Restart
    Alive -- "yes" --> Same{"hotspot shares the<br/>WiFi's channel?"}
    Same -- "no" --> Poll
    Same -- "yes" --> Link{"WiFi connected?"}
    Link -- "yes, same channel" --> Poll
    Link -- "yes, other channel" --> Restart
    Link -- "no, for 20 s" --> Restart
    Link -- "no, < 20 s" --> Poll
    Restart["stop, then start again<br/>retry 10 s → 20 s → … → 5 min"] --> Poll
```

A `p2p` hotspot never shares the WiFi's channel (`same_channel_required` is
false in its state), so only the first rule applies to it. If the WiFi moved
to a channel the card can't host on, the restart falls back to a `p2p` group
on cards that support it; on others every retry fails with the "no IR"
error until the network moves back. See [5ghz-wifi.md](5ghz-wifi.md) and
[wifi-direct.md](wifi-direct.md).

### Firewall backends record their own undo data

`net/firewall.py` chooses firewalld (if running), then iptables, then
nftables. Each backend's `apply` returns data its `revert` uses, so teardown
only removes what twinfi added. For example, masquerading is removed only from
zones where twinfi enabled it. Its `caveats` name rules outside twinfi's that
may still block clients (another nftables chain with `policy drop`); they are
added to the hotspot's notes.

### No shell, no secrets in argv

`core/shell.run` takes argv lists only (no `shell=True` anywhere). Passwords
travel through files: hostapd.conf (0600), NetworkManager keyfiles in
`/run/NetworkManager/system-connections` (0600), and stdin
(`--password-stdin`), never command-line arguments that other users can read
in `ps`.

### The CLI's JSON output is an interface

`status`, `detect`, `config`, `clients` and `start` accept `--json`. The GUI is
built on that output and scripts may be too, so treat its keys as a public
interface: add keys freely, but don't rename or remove them without a
changelog entry. The keys are documented in [json-output.md](json-output.md).

## The GUI

`twinfi_gui` is a GTK 4 / libadwaita application, and a *client of the CLI*.
It never imports `twinfi_cli` logic (only its version string). That gives one
implementation of every operation, one privilege boundary, and a GUI that
can't put the system into states the CLI can't explain.

```
app.py        Adw.Application: actions (refresh, about, quit), shortcuts,
              startup fixes (bundled icons, missing font DPI), --background,
              AppTray (tray menu actions → window)
window.py     main window: header, tabs, toasts, busy spinner, 5 s refresh loop,
              run_async / run_privileged helpers used by every page,
              close-to-tray, notifications instead of toasts while hidden
tray.py       system tray icon: StatusNotifierItem + com.canonical.dbusmenu
              over Gio D-Bus (no GTK)
pages/        one class per tab, each builds its widgets and exposes update(data)
  hotspot.py    status hero + start/stop, connection details, profile switcher
  clients.py    device rows with a menu (speed limit, disconnect, block), blocked list
  settings.py   network settings, profiles, start at boot and login, hardware report
share.py      Share dialog (QR code + password)
compat.py     newest libadwaita widget when available, fallback otherwise
backend.py    runs `twinfi … --json` and `pkexec twinfi …` (no GTK, unit-tested)
helpers.py    pure formatting / text logic (no GTK, unit-tested)
```

**Data flow.** Every 5 seconds (and after every action) the window runs
`twinfi status --json` in a worker thread and hands the result to each page's
`update(data)` on the main loop. `twinfi detect --json` runs once at startup.
Pages never block the main loop: subprocesses always run through
`window.run_async(work, done)`, and widgets are touched only in `done`.

```mermaid
sequenceDiagram
    participant W as window.py (main loop)
    participant T as worker thread
    participant C as twinfi CLI
    loop every 5 s and after each action
        W->>T: run_async(status)
        T->>C: twinfi status --json
        C-->>T: JSON
        T-->>W: done(data)
        W->>W: page.update(data) for each tab
    end
    W->>T: run_privileged(start)
    T->>C: pkexec /usr/bin/twinfi start (secrets via stdin)
    C-->>T: exit code + message
    T-->>W: toast, then refresh
```

**Changes** go through `window.run_privileged(work)`. It shows the spinner,
runs `pkexec /usr/bin/twinfi <args>` in a thread, shows the outcome as a toast
and refreshes. Only one privileged action runs at a time. Secrets (new
passwords, the password fetched for Share) travel over stdin and stdout,
never argv. The polkit action `com.github.twinfi.manage` (`auth_admin_keep`)
names twinfi in the prompt and remembers authentication for a few minutes.

**System tray.** `libayatana-appindicator` is built on GTK 3 and can't load
next to GTK 4, so `tray.py` implements the two D-Bus interfaces itself: it
owns `org.kde.StatusNotifierItem-<pid>-1`, exports the item at
`/StatusNotifierItem` and the menu at `/MenuBar`, and registers with
`org.kde.StatusNotifierWatcher` (or `org.freedesktop.StatusNotifierWatcher`)
whenever one appears on the session bus. The menu is described by
`helpers.tray_state(data, busy)` (pure, unit-tested) and refreshed with the
window's 5-second status, so the tray is just another view of the same data.
The icon is the app's own (`com.github.twinfi.Gtk-symbolic`, with `-off-` and
`-error-` variants) rather than a theme Wi-Fi icon, which would look like the
network applet's. The SVGs are filled outlines in `currentColor` under a
`current-color-scheme` stylesheet, so both GTK and Plasma's KIconLoader
recolour them to the panel's text colour; `IconThemePath` points at the
bundled copies for runs from source. `helpers.tray_status` reports
`Passive` while the hotspot is off if the user turned on *Hide tray icon
while the hotspot is off* (stored per user in `$XDG_CONFIG_HOME/twinfi/gui.json`),
which lets the panel hide the item; it stays `Active` while busy or when the
status is unknown.
Menu clicks go through the same `run_privileged` path as the window's
buttons. With no tray on the bus nothing is registered, and closing the
window quits as before; if the tray goes away while the window is hidden,
the window comes back.

**Rules the pages follow:**

- Periodic refreshes must not overwrite a field the user is editing. Pages
  remember the last value they wrote and update a field only if it still
  holds that value.
- Device rows are kept per MAC across refreshes, so an open menu isn't
  destroyed by the 5-second update.
- Everything user-controlled (SSIDs, hostnames) passes through `compat.esc()`
  before reaching a row title, subtitle, toast or status page, because those
  are Pango markup.

**Supporting old and new libadwaita.** Distros ship very different versions
(1.1 on Ubuntu 22.04, 1.5 on 24.04, the latest on Arch/Fedora). The GUI uses
the newest widgets available and falls back on older systems, entirely inside
`compat.py`:

| Need                  | ≥ this libadwaita                        | Fallback                    |
| --------------------- | ---------------------------------------- | --------------------------- |
| window layout         | ToolbarView (1.4)                        | Gtk.Box                     |
| tabs                  | header + bottom bar via Breakpoint (1.4) | compact header switcher     |
| text fields           | EntryRow / PasswordEntryRow (1.2)        | ActionRow + Gtk.Entry       |
| toggles               | SwitchRow (1.4)                          | ActionRow + Gtk.Switch      |
| action rows           | ButtonRow (1.6)                          | ActionRow + Gtk.Button      |
| busy indicator        | Adw.Spinner (1.6)                        | Gtk.Spinner                 |
| dialogs               | Adw.Dialog (1.5, sheet on narrow)        | modal Adw.Window            |
| about                 | AboutDialog (1.5) / AboutWindow (1.2)    | Gtk.AboutDialog             |

Outside `compat.py` only libadwaita 1.1 / GTK 4.6 API is allowed;
`tests/unit/test_gui.py` fails otherwise. `compat.ensure_font_dpi()` works
around libadwaita 1.5 collapsing page width when the session provides no
font DPI.

Because GTK 4 and libadwaita 1 keep their API stable within the major
version (deprecations warn, nothing is removed) and the app pins
`Gtk 4.0`/`Adw 1` via `gi.require_version`, library updates don't break it.
CI runs the GUI on the newest releases (Arch, Fedora) to catch problems early.

## Extending

| Task                     | Where                                                                      |
| ------------------------ | -------------------------------------------------------------------------- |
| New hotspot method       | subclass `Strategy` in `net/strategies.py`, add to `STRATEGIES`             |
| New firewall             | class with `name/apply/revert` in `net/firewall.py`, register in `detect()` |
| New init system          | `ENABLE`/`DISABLE` in `cmd/service.py` + a file in `twinfi_cli/data/`        |
| New USB chipset          | `USB_CHIPSET_DB` in `hw/usb.py`                                             |
| Card detected wrongly    | add its `iw phy` output to `tests/fixtures/iw/` with a test                 |
| New command              | parser in `cli.py`, handler in `cmd/`, logic in `services/`                 |
| GUI: new tab             | class in `twinfi_gui/pages/` with `widget` + `update(data, detect)`; register in `window.py` |
| GUI: widget newer than libadwaita 1.1 | add a helper with a fallback to `twinfi_gui/compat.py` |
| GUI: new action          | a `backend.py` method calling the CLI + `window.run_privileged(...)` |

Shell completion is generated from the argparse tree, so new commands and
flags are completable without extra work.

## Testing

- `tests/unit/`: pure functions and modules with `FakeShell` (a scriptable
  stand-in for `core.shell.run`) and isolated paths (`tests/support.py`).
- `tests/integration/`: the real CLI, in-process, against a simulated
  network stack (`fakeworld.py`). That is fake `iw`, `ip`, `nmcli`, `hostapd`,
  `dnsmasq`, `iptables`, … executables that share state in a JSON file and a
  fake sysfs. These tests cover full start → clients → stop lifecycles,
  fallback with rollback, stale-state recovery, DFS refusal and more, with no
  root and no hardware.

- `tests/unit/test_gui.py`: the GUI's non-GTK parts (`backend.py`,
  `helpers.py`) and a portability check that GTK code outside `compat.py`
  uses only libadwaita 1.1 API.
- `scripts/gui_smoke.py`: builds every GUI state (on, empty, off, single-radio
  card, CLI unavailable, narrow window, dialogs) against a fake backend on a
  headless display, and drives the tray icon over D-Bus against a fake tray
  (menu layout, start/stop, Settings, close-to-tray, Quit) (Broadway, or Xvfb where GTK lacks Broadway), with GTK
  criticals made fatal. It saves a screenshot of each view. CI runs it on
  Ubuntu 22.04, Debian 12, Ubuntu 24.04, Fedora and Arch.

Run `make test`, `make coverage`, `make typecheck` or `make gui-smoke`
(`make check` runs lint, type check and coverage, as CI does). CI enforces
≥ 94 % coverage of `twinfi_cli` and the GUI's non-GTK modules, and mypy
(`check_untyped_defs`) over the same code. GTK widget code is covered by the
smoke test instead.
