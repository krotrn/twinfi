#!/bin/sh
# Install twinfi with one command, the best way for this distribution:
#
#   curl -fsSL https://raw.githubusercontent.com/krotrn/twinfi/main/get.sh | sh
#
# Arch and derivatives: the twinfi pacman repository.
# Ubuntu and derivatives: the PPA (the release .deb when the PPA has no build).
# Debian and derivatives: the release .deb, checked against SHA256SUMS.
# Everything else, and whenever no package is available: dependencies from
#   the distribution, then install.sh from the latest release into /usr/local.
#
# hostapd and dnsmasq are installed too, and the desktop app's libraries when
# a graphical session is running. Options (after `sh -s --`):
#
#   --cli-only   skip the desktop app's libraries
#   --gui        install them even without a graphical session
#   --source     install from source even where a package exists
#   --dry-run    print the commands instead of running them
#
# Running it again updates twinfi.
set -eu

REPO=krotrn/twinfi
LATEST="https://github.com/$REPO/releases/latest/download"
ARCH_REPO="https://github.com/$REPO/releases/download/arch-repo"
OS_RELEASE=${TWINFI_OS_RELEASE:-/etc/os-release}  # tests point this at fixtures

DRY_RUN=0
SOURCE=0
GUI=auto
SUDO=
TMP=

say() { printf '  %s  %s\n' "$1" "$2"; }
die() { say "✘" "$*" >&2; exit 1; }

usage() {
    sed -n '2,20s/^# \{0,1\}//p' "$0" 2>/dev/null || echo "See https://github.com/$REPO#install"
}

run() {  # run <command...>: run it, or print it with --dry-run
    if [ "$DRY_RUN" = 1 ]; then
        echo "+ $*"
    else
        "$@" </dev/null  # stdin may be this script (curl | sh)
    fi
}

as_root() {
    # shellcheck disable=SC2086  # $SUDO is empty or one word
    run $SUDO "$@"
}

fetch() {  # fetch <url> <file>
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$2" "$1"
    else
        die "Neither curl nor wget is installed."
    fi
}

tmpdir() {
    if [ -z "$TMP" ]; then
        TMP=$(mktemp -d)
        chmod 755 "$TMP"  # apt reads the .deb as its own user
        trap 'rm -rf "$TMP"' EXIT
    fi
}

release_asset() {  # release_asset <awk regex> <example>: name of the latest release's matching file
    if [ "$DRY_RUN" = 1 ]; then
        echo "$2"
        return
    fi
    [ -f "$TMP/SHA256SUMS" ] || fetch "$LATEST/SHA256SUMS" "$TMP/SHA256SUMS" || return 1
    awk -v re="$1" '$2 ~ re { print $2; exit }' "$TMP/SHA256SUMS"
}

# ── Detection ────────────────────────────────────────────────────────────────

family() {  # arch | ubuntu | debian | fedora | suse | alpine | void | unknown
    for id in ${ID:-} ${ID_LIKE:-}; do
        case $id in
            arch | archarm | manjaro* | endeavouros | cachyos) echo arch; return ;;
            ubuntu) echo ubuntu; return ;;
            debian | raspbian) echo debian; return ;;
            fedora | rhel | centos) echo fedora; return ;;
            opensuse* | suse | sles) echo suse; return ;;
            alpine) echo alpine; return ;;
            void) echo void; return ;;
        esac
    done
    echo unknown
}

want_gui() {
    case $GUI in
        yes) return 0 ;;
        no) return 1 ;;
    esac
    [ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]
}

# ── Installers ───────────────────────────────────────────────────────────────
# Each package route returns non-zero when its package isn't available, and
# main() then installs from source with the distribution's dependencies.

install_arch() {
    # twinfi was called apsta until 0.13; its repository serves both names.
    if grep -q '^\[apsta\]$' /etc/pacman.conf 2>/dev/null && ! grep -q '^\[twinfi\]' /etc/pacman.conf; then
        say "→" "Renaming the [apsta] repository in /etc/pacman.conf to [twinfi]"
        as_root sed -i 's/^\[apsta\]$/[twinfi]/' /etc/pacman.conf
    elif ! grep -q '^\[twinfi\]' /etc/pacman.conf 2>/dev/null; then
        # A repository pacman can't reach would break every later `pacman -Sy`.
        if [ "$DRY_RUN" = 0 ] && ! fetch "$ARCH_REPO/twinfi.db" /dev/null; then
            say "!" "The twinfi pacman repository isn't reachable"
            return 1
        fi
        say "→" "Adding the twinfi repository to /etc/pacman.conf"
        if [ "$DRY_RUN" = 1 ]; then
            echo "+ append [twinfi] to /etc/pacman.conf"
        else
            printf '\n[twinfi]\nSigLevel = Optional TrustAll\nServer = %s\n' "$ARCH_REPO" |
                $SUDO tee -a /etc/pacman.conf >/dev/null
        fi
    fi
    # twinfi conflicts with apsta, which pacman won't resolve with --noconfirm.
    # Removing apsta also stops a hotspot it started; its settings stay for twinfi.
    if pacman -Q apsta >/dev/null 2>&1; then
        say "→" "Removing apsta (twinfi's old name) to install twinfi in its place"
        as_root pacman -R --noconfirm apsta
    fi
    set -- twinfi hostapd dnsmasq
    want_gui && set -- "$@" python-gobject gtk4 libadwaita python-qrcode
    as_root pacman -Sy --needed --noconfirm "$@"
}

install_ubuntu() {
    if ! command -v add-apt-repository >/dev/null 2>&1; then
        as_root apt-get update
        as_root apt-get install -y software-properties-common || true
    fi
    if as_root add-apt-repository -y ppa:krotrn/apsta && as_root apt-get install -y twinfi; then
        return
    fi
    say "!" "The PPA has no package for this release; trying the release .deb"
    install_deb
}

install_deb() {  # the latest release's .deb, verified against SHA256SUMS
    deb=$(release_asset '^twinfi_.*_all\.deb$' twinfi_VERSION-1_all.deb) || return 1
    if [ -z "$deb" ]; then
        say "!" "The latest release has no .deb"
        return 1
    fi
    if [ "$DRY_RUN" = 1 ]; then
        echo "+ download and verify $deb"
    else
        fetch "$LATEST/$deb" "$TMP/$deb" || return 1
        if ! (cd "$TMP" && grep " $deb\$" SHA256SUMS | sha256sum -c - >/dev/null); then
            say "!" "$deb failed its checksum"
            return 1
        fi
    fi
    as_root apt-get update
    as_root apt-get install -y "$TMP/$deb"
}

source_deps() {  # source_deps <family>: install.sh's dependencies from the distribution
    case $1 in
        arch)
            set -- "python networkmanager iw iproute2" "hostapd dnsmasq python-jeepney" \
                "python-gobject gtk4 libadwaita python-qrcode" pacman -Sy --needed --noconfirm
            ;;
        ubuntu | debian)
            as_root apt-get update
            set -- "python3 network-manager iw iproute2" "hostapd dnsmasq python3-jeepney" \
                "python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-qrcode" apt-get install -y
            ;;
        fedora)
            set -- "python3 NetworkManager iw iproute" "hostapd dnsmasq python3-jeepney" \
                "python3-gobject gtk4 libadwaita python3-qrcode" dnf install -y
            ;;
        suse)
            set -- "python3 NetworkManager iw iproute2" "hostapd dnsmasq python3-jeepney" \
                "python3-gobject python3-gobject-Gdk typelib-1_0-Gtk-4_0 typelib-1_0-Adw-1 python3-qrcode" \
                zypper --non-interactive install
            ;;
        alpine)
            set -- "bash python3 networkmanager iw iproute2" "hostapd dnsmasq py3-jeepney" \
                "py3-gobject3 gtk4.0 libadwaita py3-qrcode" apk add
            ;;
        void)
            set -- "bash python3 NetworkManager iw iproute2" "hostapd dnsmasq python3-jeepney" \
                "python3-gobject gtk4 libadwaita python3-qrcode" xbps-install -Sy
            ;;
        *)
            say "!" "Unknown distribution: install NetworkManager, iw, iproute2, hostapd and"
            say " " "dnsmasq with your package manager."
            return
            ;;
    esac
    required=$1 recommended=$2 gui=$3
    shift 3
    # shellcheck disable=SC2086  # package lists are word-split on purpose
    as_root "$@" $required || die "Could not install: $required"
    # Names differ between releases; a missing optional package shouldn't stop the install.
    # shellcheck disable=SC2086
    as_root "$@" $recommended || say "!" "Could not install some of: $recommended"
    if want_gui; then
        # shellcheck disable=SC2086
        as_root "$@" $gui || say "!" "Could not install the desktop app's libraries: $gui"
    fi
}

source_install() {  # install.sh from the latest release's tag, into /usr/local
    if [ "$DRY_RUN" = 0 ] && ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        die "twinfi needs Python 3.10 or newer."
    fi
    sdist=$(release_asset '^twinfi-[0-9.]+\.tar\.gz$' twinfi-VERSION.tar.gz) || die "Could not reach the latest release on GitHub."
    version=${sdist#twinfi-}
    version=${version%.tar.gz}
    [ -n "$version" ] || die "Could not find the latest release."
    if [ "$DRY_RUN" = 1 ]; then
        echo "+ download https://github.com/$REPO/archive/refs/tags/v$version.tar.gz"
        as_root bash "twinfi-$version/install.sh"
        return
    fi
    fetch "https://github.com/$REPO/archive/refs/tags/v$version.tar.gz" "$TMP/src.tar.gz" ||
        die "Could not download twinfi $version."
    tar -xzf "$TMP/src.tar.gz" -C "$TMP"
    as_root bash "$TMP/twinfi-$version/install.sh"
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    for arg in "$@"; do
        case $arg in
            --cli-only | --no-gui) GUI=no ;;
            --gui) GUI=yes ;;
            --source) SOURCE=1 ;;
            --dry-run) DRY_RUN=1 ;;
            -h | --help) usage; exit 0 ;;
            *) die "Unknown option: $arg (see --help)" ;;
        esac
    done

    [ "$(uname -s)" = Linux ] || [ "$DRY_RUN" = 1 ] || die "twinfi runs on Linux only."
    if [ "$(id -u)" -ne 0 ]; then
        if command -v sudo >/dev/null 2>&1 || [ "$DRY_RUN" = 1 ]; then
            SUDO=sudo
        elif command -v doas >/dev/null 2>&1; then
            SUDO=doas
        else
            die "Run as root, or install sudo."
        fi
    fi

    if [ -r "$OS_RELEASE" ]; then
        # shellcheck disable=SC1090
        . "$OS_RELEASE"
    fi
    distro=$(family)
    [ "$DRY_RUN" = 1 ] || tmpdir
    if want_gui; then gui_note="with the desktop app"; else gui_note="command line only"; fi
    say "→" "Installing twinfi for ${PRETTY_NAME:-$distro} ($gui_note)"

    case $SOURCE/$distro in
        0/arch) install_arch ;;
        0/ubuntu) install_ubuntu ;;
        0/debian) install_deb ;;
        *) false ;;
    esac || {
        case $SOURCE/$distro in
            0/arch | 0/ubuntu | 0/debian) say "→" "No package available; installing from source instead" ;;
        esac
        source_deps "$distro"
        source_install
    }

    [ "$DRY_RUN" = 1 ] && return
    if ! command -v twinfi >/dev/null 2>&1; then
        die "twinfi was installed but isn't on PATH; open a new terminal."
    fi
    if ! nmcli -t -f RUNNING general 2>/dev/null | grep -q running; then
        say "!" "NetworkManager isn't running; twinfi needs it (e.g. sudo systemctl enable --now NetworkManager)."
    fi
    echo
    say "✔" "twinfi $(twinfi --version 2>/dev/null | awk '{print $NF}') installed. Checking your Wi-Fi card:"
    echo
    twinfi detect || true
    echo
    say "→" "Start a hotspot with: sudo twinfi start"
}

main "$@"
