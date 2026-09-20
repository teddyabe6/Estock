#!/usr/bin/env bash
#
# Works out why you cannot reach Estock in your browser.
#
#   ./scripts/doctor.sh
#
# Run it in the same place you ran ./scripts/demo.sh, while the demo is running.
#
set -uo pipefail

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3000}"

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }

IS_WSL=no
grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null && IS_WSL=yes
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"

bold "Where this is running"
if [ "$IS_WSL" = yes ]; then
  note "WSL. Your browser runs on Windows, which is a separate machine to this."
else
  note "$(uname -s). Your browser and these servers share a machine."
fi
[ -n "$HOST_IP" ] && note "This machine's address: $HOST_IP"
echo

bold "Are the servers up?"
check_port() {
  local name="$1" port="$2" path="${3:-/}"
  if curl -fsS -m 4 -o /dev/null "http://localhost:${port}${path}" 2>/dev/null; then
    ok "$name is listening on port $port"
    return 0
  fi
  bad "$name is NOT responding on port $port"
  note "Start it with ./scripts/demo.sh"
  return 1
}
API_UP=0; WEB_UP=0
check_port "API" "$API_PORT" "/health" && API_UP=1
check_port "Web app" "$WEB_PORT" && WEB_UP=1
echo

if [ "$API_UP" = 0 ] || [ "$WEB_UP" = 0 ]; then
  bold "Fix that first"
  note "Both servers must be running before the browser can reach anything."
  exit 1
fi

bold "Reachable from outside this machine?"
# This is the same path your Windows browser takes. Loopback-only servers fail
# here while still answering on localhost.
for pair in "API:${API_PORT}:/health" "Web app:${WEB_PORT}:/"; do
  name="${pair%%:*}"; rest="${pair#*:}"; port="${rest%%:*}"; path="${rest#*:}"
  if [ -z "$HOST_IP" ]; then
    note "no address to test with"
  elif curl -fsS -m 4 -o /dev/null "http://${HOST_IP}:${port}${path}" 2>/dev/null; then
    ok "$name answers on http://${HOST_IP}:${port}"
  else
    bad "$name does NOT answer on http://${HOST_IP}:${port}"
    note "It is bound to loopback only."
  fi
done
echo

bold "Open these in your browser"
if [ "$IS_WSL" = yes ] && [ -n "$HOST_IP" ]; then
  note "http://${HOST_IP}:${WEB_PORT}          <- try this one first on WSL"
  note "http://localhost:${WEB_PORT}"
else
  note "http://localhost:${WEB_PORT}"
fi
echo

if [ "$IS_WSL" = yes ]; then
  bold "If localhost works for one port but not another"
  note "Windows forwards localhost into WSL, but not for ports it has reserved."
  note "That looks exactly like the server being down."
  note ""
  note "Quickest fix — move to a port Windows is not holding:"
  note "    WEB_PORT=8080 ./scripts/demo.sh"
  note ""
  note "To see which ports Windows has reserved, open PowerShell on Windows"
  note "(Start menu, type PowerShell) — NOT this terminal — and run:"
  note "    netsh interface ipv4 show excludedportrange protocol=tcp"
  note "    netstat -ano | findstr :${WEB_PORT}"
  echo
fi

bold "Summary"
note "Servers are running and answering locally."
if [ -n "$HOST_IP" ]; then
  note "If the browser still cannot reach them, it is Windows-side networking,"
  note "not this project. Use http://${HOST_IP}:${WEB_PORT}, or change WEB_PORT."
fi
