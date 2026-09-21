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
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_LOG="$ROOT/backend/var/api.log"
WEB_LOG="$ROOT/backend/var/web.log"

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

bold "Are the tools the Linux ones?"
# A Windows node or npm found first on PATH runs through CMD.EXE, which cannot
# use this project's files. It is the usual reason the web app will not start
# on WSL. Ubuntu's `nodejs` package leaves npm out, so npm can be Windows' copy
# while node looks perfectly fine — report each tool on its own.
NODE_BAD=0
NODE_OLD=0
NPM_BAD=0
PYTHON_BAD=0
NPM_PATH=""
for tool in node npm python3; do
  tool_path="$(command -v "$tool" 2>/dev/null || true)"
  [ "$tool" = npm ] && NPM_PATH="$tool_path"
  if [ -z "$tool_path" ]; then
    bad "$tool is not installed"
    case "$tool" in
      node) NODE_BAD=1 ;;
      npm) NPM_BAD=1 ;;
      python3) PYTHON_BAD=1 ;;
    esac
    continue
  fi
  case "$tool_path" in
    /mnt/*)
      bad "$tool is Windows' $tool ($tool_path)"
      note "It runs through CMD.EXE, which cannot use this project's files."
      case "$tool" in
        node) NODE_BAD=1 ;;
        npm) NPM_BAD=1 ;;
        python3) PYTHON_BAD=1 ;;
      esac
      ;;
    *)
      version=""
      case "$tool" in
        node) version="$(node --version 2>/dev/null)" ;;
        npm) version="$(npm --version 2>/dev/null)" ;;
        python3) version="$(python3 --version 2>/dev/null | awk '{print $2}')" ;;
      esac
      [ -n "$version" ] && version=" $version"
      # A version that is too old fails later, in the middle of a build.
      if [ "$tool" = node ] \
        && ! [ "$(node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0)" \
               -ge 20 ] 2>/dev/null; then
        bad "node$version is too old; this project needs 20 or newer"
        NODE_OLD=1
      else
        ok "$tool$version -> $tool_path"
      fi
      ;;
  esac
done

if [ "$NODE_OLD" = 1 ]; then
  echo
  note "Install a newer Node, then open a new terminal:"
  note "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  note "    exec \$SHELL -l && nvm install 22"
  if [ "$NPM_BAD" = 1 ]; then
    note "That brings a matching npm too, so it clears both lines above."
    note "Do NOT 'apt-get install npm' — it would pair npm with the old Node."
  fi
  note "Then:  ./scripts/demo.sh"
elif [ "$NPM_BAD" = 1 ] && [ "$NODE_BAD" = 0 ]; then
  echo
  note "Node is fine; only npm is wrong. Ubuntu's 'nodejs' package leaves npm out."
  case "$NPM_PATH" in
    /mnt/*) note "That is why npm fell through to Windows' copy." ;;
  esac
  note "    sudo apt-get install -y npm"
  note "If that pulls in an older Node, install a matched pair instead:"
  note "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  note "    exec \$SHELL -l && nvm install 22"
  note "Then:  ./scripts/demo.sh"
elif [ "$NODE_BAD" = 1 ] || [ "$NPM_BAD" = 1 ]; then
  echo
  note "Install Node and npm inside WSL itself, then open a new terminal:"
  note "    curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
  note "    exec \$SHELL -l && nvm install 22"
  note "Check it took effect — 'which node npm' must NOT show /mnt/."
  note "Then:  ./scripts/demo.sh"
fi
if [ "$PYTHON_BAD" = 1 ]; then
  echo
  note "Install Python inside WSL itself:"
  note "    sudo apt-get update && sudo apt-get install -y python3 python3-venv"
  note "Then:  rm -rf .venv && ./scripts/demo.sh"
fi
echo

bold "Are the servers up?"
check_port() {
  local name="$1" port="$2" path="${3:-/}"
  if curl -fsS -m 4 -o /dev/null "http://localhost:${port}${path}" 2>/dev/null; then
    ok "$name is listening on port $port"
    return 0
  fi
  bad "$name is NOT responding on port $port"
  local log=""
  case "$name" in
    API) log="$API_LOG" ;;
    *)   log="$WEB_LOG" ;;
  esac
  if [ -s "$log" ]; then
    note "Last lines of ${log#"$ROOT"/}:"
    echo
    tail -n 20 "$log" | sed 's/^/      /'
    echo
  else
    note "No log yet. Start it with ./scripts/demo.sh"
  fi
  return 1
}
API_UP=0; WEB_UP=0
check_port "API" "$API_PORT" "/health" && API_UP=1
check_port "Web app" "$WEB_PORT" && WEB_UP=1
echo

if [ "$WEB_UP" = 0 ]; then
  bold "Why the web app may have stopped"
  # Next's dev server is the usual casualty of both of these on WSL.
  watches="$(cat /proc/sys/fs/inotify/max_user_watches 2>/dev/null || echo unknown)"
  if [ "$watches" != unknown ] && [ "$watches" -lt 65536 ] 2>/dev/null; then
    bad "File-watch limit is only $watches — Next often exceeds this"
    note "Raise it for this boot:"
    note "    sudo sysctl fs.inotify.max_user_watches=524288"
    note "And keep it across restarts:"
    note "    echo 'fs.inotify.max_user_watches=524288' | sudo tee -a /etc/sysctl.conf"
  else
    ok "File-watch limit is $watches"
  fi

  total_mb="$(awk '/MemTotal/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)"
  avail_mb="$(awk '/MemAvailable/ {printf "%d", $2/1024}' /proc/meminfo 2>/dev/null || echo 0)"
  if [ "$total_mb" -gt 0 ] && [ "$total_mb" -lt 2048 ]; then
    bad "Only ${total_mb}MB of memory (${avail_mb}MB free) — Next may be killed"
    note "On WSL, raise it in C:\\Users\\<you>\\.wslconfig:"
    note "    [wsl2]"
    note "    memory=4GB"
    note "then run  wsl --shutdown  in PowerShell and reopen WSL."
  else
    ok "Memory: ${total_mb}MB total, ${avail_mb}MB available"
  fi
  echo
fi

if [ "$API_UP" = 0 ] || [ "$WEB_UP" = 0 ]; then
  bold "Fix that first"
  note "Both servers must be running before the browser can reach anything."
  note "Restart with ./scripts/demo.sh and read any error it prints."
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
