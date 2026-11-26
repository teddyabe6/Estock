#!/usr/bin/env bash
#
# Try the Android app against this computer.
#
#   ./scripts/phone.sh
#
# Run it in a second terminal while the server is up (./scripts/demo.sh, or
# `make api`). It checks the server answers, then says what to type into the
# app's Server box — and, on WSL, the Windows commands that let a phone on the
# same Wi-Fi reach a server running inside WSL, then checks each step of the
# way from the phone to the server and says which one is missing.
#
# The app it is for is one built without a server, which asks at sign-in:
# `make phone-apk`, or the APK you were sent.
#
set -uo pipefail

API_PORT="${API_PORT:-8000}"
PROBLEMS=0

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; PROBLEMS=$((PROBLEMS + 1)); }
fail() { printf '\n  Error: %s\n\n' "$*" >&2; exit 1; }

if ! curl -fsS -m 5 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
  fail "nothing answers on port ${API_PORT}. Start the server first with
  ./scripts/demo.sh, then run this in a second terminal."
fi

find_powershell() {
  local ps
  ps="$(command -v powershell.exe 2>/dev/null || true)"
  if [ -z "$ps" ] && [ -x /mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe ]; then
    ps=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
  fi
  printf '%s' "$ps"
}

# Run a PowerShell script in Windows and print what it says. Sent encoded, so
# nothing in it needs quoting twice; started from a Windows folder, because
# PowerShell complains about a WSL one.
windows() { # script
  local encoded
  encoded="$(printf '%s' "$1" | iconv -f UTF-8 -t UTF-16LE | base64 -w0)"
  (cd /mnt/c 2>/dev/null || true
   "$PS" -NoProfile -NonInteractive -EncodedCommand "$encoded" 2>/dev/null) | tr -d '\r'
}

# Addresses a phone on the same network could use, one per line. On WSL these
# are Windows' own: the phone talks to Windows, which passes it on to WSL.
windows_ips() {
  [ -n "$PS" ] || return 0
  windows 'Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -and $_.NetAdapter.Status -eq "Up" } | ForEach-Object { $_.IPv4Address.IPAddress }' \
    | grep -E '^[0-9]+(\.[0-9]+){3}$' || true
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

# When everything on this computer is in place and the phone still cannot get
# through, what is left is the phone, the Wi-Fi, or something else on the PC.
whats_left() { # one address
  local address="${1:-<the address above>}:${API_PORT}"
  bold "Still cannot connect?"
  echo
  info "1. The Server box in the app must say exactly ${address}"
  info "2. On the phone, open http://${address}/health in the browser."
  info "   - It shows {\"status\":\"ok\", ...}: the phone reaches this computer,"
  info "     so look at the address typed into the app again."
  info "   - It does not load: the phone is not reaching this computer. Check it"
  info "     is on the same Wi-Fi, not mobile data; that it is not a guest"
  info "     network (those keep devices apart); that no VPN is on, on the phone"
  info "     or here; and that no antivirus with its own firewall (Norton,"
  info "     McAfee, Kaspersky, ESET, Avast...) is blocking port ${API_PORT}."
  info "3. To rule the Wi-Fi out: turn on the phone's hotspot, connect this"
  info "   computer to it, and run this script again for the new address."
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
PS="$(find_powershell)"
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
  cat <<PS1
    if (-not (Get-NetFirewallHyperVRule -Name EstockServer -ErrorAction SilentlyContinue)) { New-NetFirewallHyperVRule -Name EstockServer -DisplayName 'Estock server' -Direction Inbound -VMCreatorId '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -Protocol TCP -LocalPorts ${API_PORT} | Out-Null }
PS1
  echo
  info "That lets devices on your Wi-Fi reach port ${API_PORT} inside WSL."
else
  cat <<PS1
    netsh interface portproxy add v4tov4 listenport=${API_PORT} listenaddress=0.0.0.0 connectport=${API_PORT} connectaddress=${WSL_IP}
    if (-not (Get-NetFirewallRule -DisplayName 'Estock server' -ErrorAction SilentlyContinue)) { New-NetFirewallRule -DisplayName 'Estock server' -Direction Inbound -Protocol TCP -LocalPort ${API_PORT} -Action Allow | Out-Null }
PS1
  echo
  info "The first line passes port ${API_PORT} on to WSL; the second lets the"
  info "phone through the firewall."
  echo
  info "WSL gets a new address each time it restarts. Run this script again"
  info "then, and paste the first line again; the second is needed only once."
fi

echo
bold "Checking the way from the phone to the server"
echo
ok "The server answers inside WSL, on port ${API_PORT}."
if [ "$mode" != mirrored ]; then
  if curl -fsS -m 5 "http://${WSL_IP}:${API_PORT}/health" >/dev/null 2>&1; then
    ok "It answers on WSL's own address (${WSL_IP}) too, where Windows sends the phone."
  else
    bad "It answers only on localhost inside WSL, not on WSL's address (${WSL_IP}). Start it with ./scripts/demo.sh or make api, which listen on every address."
  fi
fi

if [ -z "$PS" ]; then
  info "! Could not ask Windows how it is set up: PowerShell cannot be started"
  info "  from WSL here. Check the steps above by hand."
else
  ips_list=""
  for ip in $WIN_IPS; do ips_list="${ips_list:+$ips_list,}'$ip'"; done
  # What Windows can say without being Administrator: where it passes the
  # port, whether the service that does that runs, the firewall rule, what
  # kind of network the Wi-Fi is, and whether this PC reaches the server the
  # way the phone will.
  report="$(windows "
\$ErrorActionPreference = 'SilentlyContinue'
\$ProgressPreference = 'SilentlyContinue'
[System.Net.WebRequest]::DefaultWebProxy = \$null
\$port = ${API_PORT}
\$pattern = '^\\s*(0\\.0\\.0\\.0|\\*)\\s+' + \$port + '\\s+(\\S+)\\s+' + \$port + '\\s*\$'
\$forward = ''
foreach (\$row in (netsh interface portproxy show v4tov4)) { if (\$row -match \$pattern) { \$forward = \$Matches[2] } }
'forward=' + \$forward
'service=' + (Get-Service iphlpsvc).Status
'rule=' + @(Get-NetFirewallRule -DisplayName 'Estock server' | Where-Object { \"\$(\$_.Enabled)\" -eq 'True' -and \"\$(\$_.Direction)\" -eq 'Inbound' -and \"\$(\$_.Action)\" -eq 'Allow' }).Count
try { 'hyperv=' + @(Get-NetFirewallHyperVRule -Name EstockServer -ErrorAction Stop).Count } catch { 'hyperv=0' }
\$net = Get-NetConnectionProfile | Where-Object { 'Internet', 'LocalNetwork' -contains \"\$(\$_.IPv4Connectivity)\" } | Select-Object -First 1
\$category = \"\$(\$net.NetworkCategory)\"
'network=' + \$category
\$fwProfile = if (\$category -eq 'DomainAuthenticated') { 'Domain' } else { \$category }
if (\$fwProfile) { 'inbound=' + (Get-NetFirewallProfile -Name \$fwProfile).AllowInboundRules }
foreach (\$ip in @(${ips_list})) {
  try { \$code = (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 -Uri \"http://\${ip}:\$port/health\").StatusCode } catch { \$code = 0 }
  'reach=' + \$ip + ' ' + \$code
}
")"

  value() { printf '%s\n' "$report" | sed -n "s/^$1=//p" | head -1; }
  forward="$(value forward)"
  service="$(value service)"
  rule="$(value rule)"
  hyperv="$(value hyperv)"
  network="$(value network)"
  inbound="$(value inbound)"

  if [ "$mode" = mirrored ]; then
    if [ "${hyperv:-0}" -gt 0 ] 2>/dev/null; then
      ok "The WSL firewall has a rule letting the phone in."
    else
      bad "The WSL firewall has no rule for port ${API_PORT} yet: paste the line above."
    fi
  else
    if [ -z "$forward" ]; then
      bad "Windows is not passing port ${API_PORT} on to WSL yet: paste the first line above."
    elif [ "$forward" != "$WSL_IP" ]; then
      bad "Windows passes port ${API_PORT} to ${forward}, but WSL is at ${WSL_IP} now (it changes when WSL restarts): paste the first line above again."
    else
      ok "Windows passes port ${API_PORT} on to WSL (${WSL_IP})."
    fi
    if [ -n "$forward" ] && [ "$service" != Running ]; then
      bad "The Windows service that passes it on (IP Helper) is not running. In PowerShell as Administrator: Set-Service iphlpsvc -StartupType Automatic; Start-Service iphlpsvc"
    fi
    if [ "${rule:-0}" -gt 0 ] 2>/dev/null; then
      ok "The firewall has a rule letting the phone in."
    else
      bad "The firewall has no rule for port ${API_PORT} yet: paste the second line above."
    fi
  fi

  if [ "$inbound" = False ]; then
    bad "Windows blocks every incoming connection on this ${network} network, whatever the rules say. In Windows Security, Firewall & network protection, ${network} network: untick \"Blocks all incoming connections\"."
  elif [ -n "$network" ]; then
    ok "This Wi-Fi is a ${network} network, and the firewall's rules apply on it."
  fi

  if [ "$mode" != mirrored ]; then
    while read -r ip code; do
      [ -n "$ip" ] || continue
      if [ "$code" = 200 ]; then
        ok "This PC reaches the server at ${ip}:${API_PORT}, the way the phone will."
      else
        bad "This PC cannot reach the server at ${ip}:${API_PORT} either, so the phone cannot."
      fi
    done <<EOF
$(printf '%s\n' "$report" | sed -n 's/^reach=//p')
EOF
  fi
fi

say_address "$WIN_IPS"

if [ "$PROBLEMS" -gt 0 ]; then
  info "Fix what has a ✗ above, then run this script again."
  echo
else
  whats_left "$(printf '%s\n' "$WIN_IPS" | head -1)"
fi
