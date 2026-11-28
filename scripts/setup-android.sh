#!/usr/bin/env bash
#
# Set this computer up to run the Android app on a phone plugged in by USB.
#
#   ./scripts/setup-android.sh
#
# For Linux and WSL (Ubuntu or Debian, on an x86-64 PC). Installs what
# `flutter run` needs to build the app and put it on a phone: Java 17,
# Flutter 3.27.1 (the version this project is built with) and the Android
# SDK. About 2 GB to download, and more the first time the app is built.
# Safe to run again: it skips what is already there.
#
# Then: ./scripts/phone-usb.sh (see docs/local-setup.md).
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FLUTTER_VERSION=3.27.1
FLUTTER_DIR="${FLUTTER_DIR:-$HOME/flutter}"
ANDROID_SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
CMDLINE_TOOLS_ZIP=commandlinetools-linux-11076708_latest.zip
# What this project's Gradle build asks for (Flutter 3.27's defaults).
SDK_PACKAGES=("platform-tools" "platforms;android-35" "build-tools;34.0.0" "ndk;26.1.10909125")

bold() { printf '\n\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '\n  Error: %s\n\n' "$*" >&2; exit 1; }

[ "$(uname)" = Linux ] || fail "this script is for Linux and WSL. On a Mac, install
  Android Studio and Flutter $FLUTTER_VERSION as flutter.dev describes."
[ "$(uname -m)" = x86_64 ] || fail "Flutter and the Android SDK for Linux need an x86-64 PC."
command -v apt-get >/dev/null || fail "this script needs apt (Ubuntu or Debian). Install Java 17,
  Flutter $FLUTTER_VERSION and the Android SDK as flutter.dev describes."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO=sudo

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# --------------------------------------------------------------------------- #
bold "1/5  Java 17 and the tools to unpack things"
# --------------------------------------------------------------------------- #
# Java 17 rather than whatever is newest: the project's Gradle (8.3) does not
# run on Java 21. android-sdk-platform-tools-common carries the rules that let
# adb use a phone's USB port without root.
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq openjdk-17-jdk-headless curl unzip xz-utils zip git \
  usbutils android-sdk-platform-tools-common >/dev/null
JDK_DIR="$(ls -d /usr/lib/jvm/java-17-openjdk-* 2>/dev/null | head -1)"
[ -n "$JDK_DIR" ] || fail "Java 17 did not install."
info "Java 17: $JDK_DIR"
if [ -n "$SUDO" ] && ! id -nG | tr ' ' '\n' | grep -qx plugdev; then
  $SUDO usermod -aG plugdev "$USER"
  info "Added you to the plugdev group (for adb and USB)."
fi

# --------------------------------------------------------------------------- #
bold "2/5  Flutter $FLUTTER_VERSION"
# --------------------------------------------------------------------------- #
if [ -x "$FLUTTER_DIR/bin/flutter" ]; then
  FLUTTER="$FLUTTER_DIR/bin/flutter"
elif command -v flutter >/dev/null; then
  FLUTTER="$(command -v flutter)"
else
  FLUTTER=""
fi

if [ -z "$FLUTTER" ]; then
  [ ! -e "$FLUTTER_DIR" ] || fail "$FLUTTER_DIR exists but is not Flutter. Move it, or set FLUTTER_DIR."
  info "Downloading Flutter (about 750 MB)..."
  curl -fL --retry 3 --progress-bar -o "$work/flutter.tar.xz" \
    "https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_${FLUTTER_VERSION}-stable.tar.xz"
  info "Unpacking it into $FLUTTER_DIR..."
  tar -xJf "$work/flutter.tar.xz" -C "$work"
  mkdir -p "$(dirname "$FLUTTER_DIR")"
  mv "$work/flutter" "$FLUTTER_DIR"
  rm -f "$work/flutter.tar.xz"
  FLUTTER="$FLUTTER_DIR/bin/flutter"
fi
"$FLUTTER" config --no-analytics >/dev/null 2>&1 || true
flutter_version() {
  "$FLUTTER" --version --machine 2>/dev/null \
    | sed -n 's/.*"frameworkVersion": *"\([^"]*\)".*/\1/p' | head -1
}
have="$(flutter_version)"
if [ "$have" = 0.0.0-unknown ]; then
  # Flutter reads its version from git, and git will not read a folder that
  # another user owns until told it is safe.
  git config --global --add safe.directory "$(cd "$(dirname "$FLUTTER")/.." && pwd)"
  have="$(flutter_version)"
fi
if [ "$have" = "$FLUTTER_VERSION" ]; then
  info "Flutter $have: $FLUTTER"
else
  info "Flutter ${have:-?} at $FLUTTER; this project is built with $FLUTTER_VERSION."
  info "Carrying on with it — if a build fails, install $FLUTTER_VERSION instead."
fi

# --------------------------------------------------------------------------- #
bold "3/5  The Android SDK"
# --------------------------------------------------------------------------- #
export JAVA_HOME="$JDK_DIR"
SDKMANAGER="$ANDROID_SDK/cmdline-tools/latest/bin/sdkmanager"
if [ ! -x "$SDKMANAGER" ]; then
  info "Downloading Android's command-line tools..."
  curl -fL --retry 3 --progress-bar -o "$work/cmdline-tools.zip" \
    "https://dl.google.com/android/repository/$CMDLINE_TOOLS_ZIP"
  unzip -q "$work/cmdline-tools.zip" -d "$work/cmdline-tools"
  mkdir -p "$ANDROID_SDK/cmdline-tools"
  rm -rf "$ANDROID_SDK/cmdline-tools/latest"
  mv "$work/cmdline-tools/cmdline-tools" "$ANDROID_SDK/cmdline-tools/latest"
fi
info "Accepting the Android SDK licences..."
# `yes` is cut off when sdkmanager has read enough, which is not a failure.
yes 2>/dev/null | "$SDKMANAGER" --sdk_root="$ANDROID_SDK" --licenses >/dev/null || true
info "Installing ${SDK_PACKAGES[*]} (about 1 GB)..."
"$SDKMANAGER" --sdk_root="$ANDROID_SDK" --install "${SDK_PACKAGES[@]}" \
  | grep -vE '^\[=*|^Loading|^$' || true
for package in platform-tools platforms/android-35 build-tools/34.0.0 ndk/26.1.10909125; do
  [ -d "$ANDROID_SDK/$package" ] || fail "the Android SDK package $package did not install."
done
info "Android SDK: $ANDROID_SDK"

# --------------------------------------------------------------------------- #
bold "4/5  Pointing Flutter at them"
# --------------------------------------------------------------------------- #
"$FLUTTER" config --android-sdk "$ANDROID_SDK" --jdk-dir "$JDK_DIR" >/dev/null
yes 2>/dev/null | "$FLUTTER" doctor --android-licenses >/dev/null 2>&1 || true
"$FLUTTER" precache --android >/dev/null
(cd "$ROOT/mobile" && "$FLUTTER" pub get >/dev/null)

# New terminals find flutter and adb by name.
marker="# Estock: Flutter and the Android SDK"
if ! grep -qF "$marker" "$HOME/.bashrc" 2>/dev/null; then
  cat >> "$HOME/.bashrc" <<EOF

$marker (scripts/setup-android.sh)
export ANDROID_HOME="$ANDROID_SDK"
export PATH="$(dirname "$FLUTTER"):\$ANDROID_HOME/platform-tools:\$PATH"
EOF
  info "Added flutter and adb to your PATH in ~/.bashrc."
fi

# --------------------------------------------------------------------------- #
bold "5/5  Checking"
# --------------------------------------------------------------------------- #
"$FLUTTER" doctor 2>&1 | grep -E '^\[' || true
info "Android toolchain needs a tick. Linux toolchain, Chrome and Android"
info "Studio do not matter here."

bold "Done"
info "Open a new terminal (so flutter and adb are on your PATH), then:"
info "  ./scripts/demo.sh        in one terminal, for the server"
info "  ./scripts/phone-usb.sh   in another, with the phone plugged in"
if grep -qi microsoft /proc/sys/kernel/osrelease 2>/dev/null; then
  echo
  info "On WSL, Windows has to hand the phone to WSL first. Once, in Windows"
  info "PowerShell:  winget install --exact dorssel.usbipd-win"
  info "The rest is in docs/local-setup.md, \"From your computer, phone on a cable\"."
fi
echo
