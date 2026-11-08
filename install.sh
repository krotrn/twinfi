#!/usr/bin/env bash
# Install twinfi from a source checkout into /usr/local (for distros without a package).
#
#   sudo ./install.sh              install CLI, GUI, service files, polkit policy
#   sudo ./install.sh --uninstall  remove everything this script installed
#
# Prefer your distribution's package (see README) when one exists.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PREFIX="${PREFIX:-/usr/local}"
LIB="$PREFIX/lib/twinfi"
BIN="$PREFIX/bin"

say() { printf '  %s  %s\n' "$1" "$2"; }

if [[ $EUID -ne 0 ]]; then
    echo "Run with sudo: sudo ./install.sh $*" >&2
    exit 1
fi

render() {  # render <data file>: point packaged paths at this prefix
    sed "s|/usr/bin/twinfi|$BIN/twinfi|g" "$1"
}

uninstall() {
    if command -v systemctl >/dev/null 2>&1; then
        systemctl disable --now twinfi.service >/dev/null 2>&1 || true
    fi
    "$BIN/twinfi" stop >/dev/null 2>&1 || true
    rm -rf "$LIB"
    rm -f "$BIN/twinfi" "$BIN/twinfi-gtk" "$BIN/apsta" \
          /etc/systemd/system/twinfi.service \
          /usr/lib/systemd/system-sleep/twinfi-sleep \
          /usr/share/polkit-1/actions/com.github.twinfi.policy \
          /usr/share/applications/com.github.twinfi.Gtk.desktop \
          /usr/share/metainfo/com.github.twinfi.Gtk.metainfo.xml \
          /usr/share/icons/hicolor/scalable/apps/com.github.twinfi.Gtk.svg \
          /usr/share/icons/hicolor/symbolic/apps/com.github.twinfi.Gtk-symbolic.svg \
          /usr/share/icons/hicolor/symbolic/apps/com.github.twinfi.Gtk-off-symbolic.svg \
          /usr/share/icons/hicolor/symbolic/apps/com.github.twinfi.Gtk-error-symbolic.svg \
          /etc/bash_completion.d/twinfi \
          /usr/local/share/zsh/site-functions/_twinfi \
          /etc/fish/completions/twinfi.fish
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload || true
    fi
    say "✔" "twinfi removed (configuration kept in /etc/twinfi)"
}

if [[ "${1:-}" == "--uninstall" ]]; then
    uninstall
    exit 0
fi

echo "Installing twinfi into $PREFIX ..."

# twinfi was called apsta until 0.13: drop that install's code, GUI files and
# completions. `twinfi` moves its settings and boot service on first use as root.
if [[ -d "$PREFIX/lib/apsta" ]]; then
    "$BIN/apsta" stop >/dev/null 2>&1 || true
    rm -rf "$PREFIX/lib/apsta"
    rm -f "$BIN/apsta-gtk" \
          /usr/share/polkit-1/actions/com.github.apsta.policy \
          /usr/share/applications/com.github.apsta.Gtk.desktop \
          /usr/share/metainfo/com.github.apsta.Gtk.metainfo.xml \
          /usr/share/icons/hicolor/scalable/apps/com.github.apsta.Gtk.svg \
          /usr/share/icons/hicolor/symbolic/apps/com.github.apsta.Gtk-symbolic.svg \
          /etc/bash_completion.d/apsta \
          /usr/local/share/zsh/site-functions/_apsta \
          /etc/fish/completions/apsta.fish
    say "✔" "Removed the apsta install this replaces"
fi

# Python packages go to a private directory, not onto the system site-packages.
rm -rf "$LIB"
install -d "$LIB"
cp -R "$SRC/twinfi_cli" "$SRC/twinfi_gui" "$LIB/"
install -m644 "$SRC/install.sh" "$LIB/install.sh"  # `twinfi uninstall` runs its --uninstall
find "$LIB" -name '__pycache__' -prune -exec rm -rf {} +
say "✔" "Python packages → $LIB"

for tool in twinfi:twinfi_cli twinfi-gtk:twinfi_gui; do
    name="${tool%%:*}" module="${tool##*:}"
    cat > "$BIN/$name" <<SH
#!/bin/sh
PYTHONPATH="$LIB\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m $module "\$@"
SH
    chmod 755 "$BIN/$name"
    say "✔" "$BIN/$name"
done
# The old name keeps working for now, with a reminder.
cat > "$BIN/apsta" <<SH
#!/bin/sh
echo "apsta is now called twinfi; please use 'twinfi' (the old name will go away)." >&2
exec "$BIN/twinfi" "\$@"
SH
chmod 755 "$BIN/apsta"

if [[ -d /usr/lib/systemd ]]; then
    render "$SRC/twinfi_cli/data/twinfi.service" > /etc/systemd/system/twinfi.service
    install -d /usr/lib/systemd/system-sleep
    render "$SRC/twinfi_cli/data/twinfi-sleep" > /usr/lib/systemd/system-sleep/twinfi-sleep
    chmod 755 /usr/lib/systemd/system-sleep/twinfi-sleep
    systemctl daemon-reload || true
    say "✔" "systemd service + sleep hook (enable with: sudo twinfi enable)"
fi

if [[ -d /usr/share/polkit-1/actions ]]; then
    render "$SRC/twinfi_cli/data/com.github.twinfi.policy" > /usr/share/polkit-1/actions/com.github.twinfi.policy
    say "✔" "polkit policy"
fi

install -Dm644 "$SRC/twinfi_gui/data/com.github.twinfi.Gtk.desktop" /usr/share/applications/com.github.twinfi.Gtk.desktop
install -Dm644 "$SRC/twinfi_gui/data/com.github.twinfi.Gtk.metainfo.xml" /usr/share/metainfo/com.github.twinfi.Gtk.metainfo.xml
for kind in scalable symbolic; do
    for icon in "$SRC"/twinfi_gui/data/icons/hicolor/"$kind"/apps/*.svg; do
        install -Dm644 "$icon" "/usr/share/icons/hicolor/$kind/apps/$(basename "$icon")"
    done
done
if command -v gtk-update-icon-cache >/dev/null; then
    gtk-update-icon-cache -q /usr/share/icons/hicolor || true
fi
say "✔" "desktop entry and icon"

completion() {  # completion <shell> <file>: install it when that shell is installed
    if command -v "$1" >/dev/null 2>&1 && "$BIN/twinfi" completion "$1" | install -Dm644 /dev/stdin "$2"; then
        say "✔" "$1 completion"
    fi
}
completion bash /etc/bash_completion.d/twinfi
completion zsh /usr/local/share/zsh/site-functions/_twinfi
completion fish /etc/fish/completions/twinfi.fish

echo
echo "Done. Next: twinfi detect"
