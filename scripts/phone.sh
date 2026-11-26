#!/usr/bin/env bash
#
# Try the Android app against this computer.
#
#   ./scripts/phone.sh
#
# Run it in a second terminal while the server is up (./scripts/demo.sh, or
# `make api`). It checks the server answers, then says what to type into the
# app's Server box — and, on WSL, the Windows commands that let a phone on the
# same Wi-Fi reach a server running inside WSL.
#
# The app it is for is one built without a server, which asks at sign-in:
# `make phone-apk`, or the APK you were sent.
#
set -uo pipefail

API_PORT="${API_PORT:-8000}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '\n  Error: %s\n\n' "$*" >&2; exit 1; }

if ! curl -fsS -m 5 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
  fail "nothing answers on port ${API_PORT}. Start the server first with
  ./scripts/demo.sh, then run this in a second terminal."
fi

# Addresses a phone on the same network could use, one per line. On WSL these
# are Windows' own: the phone talks to Windows, which passes it on to WSL.
windows_ips() {
  local ps
  ps="$(command -v powershell.exe 2>/dev/null || true)"
  if [ -z "$ps" ] && [ -x /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe ]; then
    ps=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
  fi
  [ -n "$ps" ] || return 0
  # Started from a Windows folder: PowerShell warns about a WSL one.
  (cd /mnt/c 2>/dev/null || true
   "$ps" -NoProfile -NonInteractive -Command \
     'Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | ForEach-Object { $_.IPv4Address.IPAddress }' \
     2>/dev/null) | tr -d '\r' | grep -E '^[0-9]+(\.[0-9]+){3}$' || true
}

local_ips() {
  if [ "$(uname)" = Darwin ]; then
    for iface in en0 en1; do ipconfig getifaddr "$iface" 2>/dev/null; done
  else
    hostname -I 2>/dev/null | tr ' ' '\n' | grep -E '^[0-9]+(\.[0-9]+){3}$' \
      | grep -vE '^(127\.|172\.17\.)' || true
  fi
}

say_address() { # addresses, one per line
  local ips="$1" count
  count="$(printf '%s\n' "$ips" | grep -c . || true)"
  echo
  bold "On your phone"
  echo
  info "Connect it to the same Wi-Fi as this computer, open Estock, and in the"
  info "Server box type:"
  echo
  if [ "$count" -eq 0 ]; then
    info "    <this computer's address>:${API_PORT}"
    echo
    info "Find the address with ipconfig in Windows PowerShell (\"IPv4 Address\""
    info "under your Wi-Fi), or in your Wi-Fi settings."
  else
    printf '%s\n' "$ips" | while read -r ip; do
      [ -n "$ip" ] && info "    ${ip}:${API_PORT}"
    done
    if [ "$count" -gt 1 ]; then
      echo
      info "(One of these: whichever is on the same Wi-Fi as the phone.)"
    fi
  fi
  echo
  info "Then sign in as owner@merkato-demo.et / demo-password-123"
  echo
}

case "$(cat /proc/sys/kernel/osrelease 2>/dev/null || true)" in
  *[Mm]icrosoft*) ;;
  *)
    say_address "$(local_ips)"
    info "If the phone cannot connect, this computer's firewall may be refusing"
    info "port ${API_PORT} from other devices."
    echo
    exit 0
    ;;
esac

# WSL. In its usual (NAT) mode WSL sits behind Windows on an address of its
# own that the phone cannot see, so Windows has to pass the port on. In
# mirrored mode WSL shares Windows' address and only the firewall is in the
# way.
WSL_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
WIN_IPS="$(windows_ips)"

mode="$(wslinfo --networking-mode 2>/dev/null | tr -d '\r' || true)"
if [ -z "$mode" ]; then
  mode=nat
  for ip in $WIN_IPS; do
    case " $(hostname -I 2>/dev/null) " in *" $ip "*) mode=mirrored ;; esac
  done
fi

echo
bold "Once, in Windows"
echo
info "Open PowerShell as Administrator (Start menu, type PowerShell,"
info "right-click it, Run as administrator) and paste:"
echo
if [ "$mode" = mirrored ]; then
  cat <<PS
    if (-not (Get-NetFirewallHyperVRule -Name EstockServer -ErrorAction SilentlyContinue)) { New-NetFirewallHyperVRule -Name EstockServer -DisplayName 'Estock server' -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts ${API_PORT} | Out-Null }
PS
  echo
  info "That lets devices on your Wi-Fi reach port ${API_PORT} inside WSL."
else
  cat <<PS
    netsh interface portproxy add v4tov4 listenport=${API_PORT} listenaddress=0.0.0.0 connectport=${API_PORT} connectaddress=${WSL_IP}
    if (-not (Get-NetFirewallRule -DisplayName 'Estock server' -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName 'Estock server' -Direction Inbound -Protocol TCP -LocalPort ${API_PORT} -Action Allow | Out-Null }
PS
  echo
  info "The first line passes port ${API_PORT} on to WSL; the second lets the"
  info "phone through the firewall."
  echo
  info "WSL gets a new address each time it restarts. Run this script again"
  info "then, and paste the first line again; the second is needed only once."
fi

say_address "$WIN_IPS"
