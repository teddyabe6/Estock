#!/usr/bin/env bash
#
# Run the Android app on a phone plugged into this computer, with hot reload.
#
#   ./scripts/phone-usb.sh
#
# Start the server first, in another terminal (./scripts/demo.sh). Set this
# computer up once with ./scripts/setup-android.sh, and turn USB debugging on
# in the phone (docs/local-setup.md, "From your computer, phone on a cable").
#
# The phone reaches the server through the cable: `adb reverse` makes the
# phone's own 127.0.0.1:8000 lead to port 8000 here, so Wi-Fi, addresses and
# firewalls do not come into it.
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_PORT="${API_PORT:-8000}"

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '\n  Error: %s\n\n' "$*" >&2; exit 1; }

# What setup-android.sh installed, even in a terminal opened before it ran.
for dir in "${ANDROID_HOME:-$HOME/Android/Sdk}/platform-tools" "$HOME/flutter/bin"; do
  if [ -d "$dir" ]; then
    case ":$PATH:" in *":$dir:"*) ;; *) PATH="$dir:$PATH" ;; esac
  fi
done
command -v flutter >/dev/null || fail "Flutter is not installed. Run ./scripts/setup-android.sh first."
command -v adb >/dev/null || fail "adb is not installed. Run ./scripts/setup-android.sh first."
ADB="$(command -v adb)"

curl -fsS -m 5 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1 \
  || fail "the server is not running. Start it first, in another terminal: ./scripts/demo.sh"

on_wsl() { grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; }

# One line per phone adb can see: its serial, then device, unauthorized, or
# "no" (as in "no permissions").
phones() { "$ADB" devices 2>/dev/null | tail -n +2 | awk 'NF >= 2 { print $1, $2 }'; }
count() { phones | awk -v state="$1" '$2 == state' | grep -c . || true; }
any() { phones | grep -c . || true; }

"$ADB" start-server >/dev/null 2>&1

# On WSL a phone plugged into the PC belongs to Windows until usbipd-win hands
# it over, which it does once allowed (`usbipd bind`, as Administrator).
attach_from_windows() {
  local usbipd list rows shared busid
  usbipd="$(command -v usbipd.exe 2>/dev/null || true)"
  # Where its installer puts it, for a WSL started before it was installed,
  # which has not seen Windows' new PATH.
  if [ -z "$usbipd" ] && [ -x "/mnt/c/Program Files/usbipd-win/usbipd.exe" ]; then
    usbipd="/mnt/c/Program Files/usbipd-win/usbipd.exe"
  fi
  if [ -z "$usbipd" ]; then
    bold "Windows has to hand the phone to WSL"
    info "Install usbipd-win once, in Windows PowerShell — open it from the"
    info "Start menu; it is not this WSL terminal — with:"
    info "    winget install --exact dorssel.usbipd-win"
    info "then run this script again."
    return 1
  fi
  list="$(cd /mnt/c 2>/dev/null; "$usbipd" list 2>/dev/null | tr -d '\r')"
  rows="$(printf '%s\n' "$list" | grep -E '^[0-9]+-[0-9.]+ ' || true)"
  # Already in WSL: it can take adb a moment, or wait on the phone's say-so.
  printf '%s\n' "$rows" | grep -qE ' Attached *$' && return 0
  shared="$(printf '%s\n' "$rows" | grep -E ' Shared *$' || true)"
  if [ "$(printf '%s\n' "$shared" | grep -c .)" -eq 1 ]; then
    busid="$(printf '%s\n' "$shared" | awk '{ print $1 }')"
    info "Handing the phone (USB $busid) from Windows to WSL..."
    if (cd /mnt/c 2>/dev/null; "$usbipd" attach --wsl --busid "$busid" >/dev/null 2>&1); then
      return 0
    fi
    info "That did not work. In Windows PowerShell: usbipd attach --wsl --busid $busid"
    return 1
  fi
  bold "Windows has to hand the phone to WSL"
  if [ -n "$shared" ]; then
    info "More than one USB device is shared with WSL. In Windows PowerShell,"
    info "attach the phone's, with its BUSID from the list below:"
    info "    usbipd attach --wsl --busid <BUSID>"
  else
    info "Allow it once: in Windows PowerShell opened as Administrator, find the phone"
    info "in the list below (its name, or \"ADB Interface\") and run, with its BUSID:"
    info "    usbipd bind --busid <BUSID>"
  fi
  echo
  printf '%s\n' "$list" | sed -n '/^BUSID/,/^$/p' | sed 's/^/      /'
  info "Then run this script again."
  return 1
}

if [ "$(any)" -eq 0 ] && on_wsl; then
  attach_from_windows || exit 1
  # A phone takes a few seconds to show up once attached.
  for _ in $(seq 1 15); do [ "$(any)" -gt 0 ] && break; sleep 1; done
fi
if [ "$(any)" -eq 0 ]; then
  bold "No phone found"
  info "Check the cable (a charge-only cable carries no data), that USB debugging"
  info "is on (Settings, Developer options), and that the phone is unlocked."
  if on_wsl; then
    info "If Windows still has it, in Windows PowerShell: usbipd attach --wsl --busid <BUSID>"
  fi
  echo
  exit 1
fi

# adb running as you may not be let into the phone's USB port: WSL usually has
# no udev to grant it. adb running as root is.
if [ "$(count no)" -gt 0 ]; then
  info "adb may not open the phone's USB port as you; restarting it as root."
  "$ADB" kill-server >/dev/null 2>&1
  if [ "$(id -u)" -eq 0 ]; then
    "$ADB" start-server >/dev/null 2>&1
  else
    sudo "$ADB" start-server >/dev/null 2>&1 || fail "could not start adb with sudo."
  fi
  for _ in $(seq 1 10); do [ "$(count no)" -eq 0 ] && [ "$(any)" -gt 0 ] && break; sleep 1; done
fi

# The first time, the phone asks whether to trust this computer.
if [ "$(count unauthorized)" -gt 0 ]; then
  bold "On the phone: tap Allow"
  info "Unlock it: it asks \"Allow USB debugging?\". Tick \"Always allow from this"
  info "computer\" and tap Allow. Waiting..."
  for _ in $(seq 1 60); do [ "$(count unauthorized)" -eq 0 ] && break; sleep 1; done
fi

serial="${ANDROID_SERIAL:-$(phones | awk '$2 == "device" { print $1; exit }')}"
[ -n "$serial" ] || fail "the phone is connected but not ready ($(phones | tr '\n' ' ')).
  Unplug it, plug it in again, and run this script again."
if [ "$(count device)" -gt 1 ] && [ -z "${ANDROID_SERIAL:-}" ]; then
  info "More than one phone is connected; using $serial. Choose with ANDROID_SERIAL=<serial>."
fi

# The phone's own 127.0.0.1:8000, through the cable, to the server here.
"$ADB" -s "$serial" reverse "tcp:${API_PORT}" "tcp:${API_PORT}" >/dev/null \
  || fail "could not connect the phone to the server through the cable (adb reverse)."

model="$("$ADB" -s "$serial" shell getprop ro.product.model 2>/dev/null | tr -d '\r')"
bold "Running Estock on ${model:-the phone}"
info "The phone reaches the server here through the cable, as 127.0.0.1:${API_PORT}."
info "The first build takes several minutes; later ones are quick."
info "Once it is running: r reloads after a change to the code, R restarts, q quits."
echo
cd "$ROOT/mobile" || exit 1
exec flutter run -d "$serial" --dart-define=API_BASE_URL="http://127.0.0.1:${API_PORT}/api/v1"
