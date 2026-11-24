#!/usr/bin/env bash
set -Eeuo pipefail

REPO_ARCHIVE="https://github.com/moeinfire/multi-client-slipstream-panel/archive/refs/heads/main.tar.gz"

if [[ "$EUID" -ne 0 ]]; then
  echo "ERROR: Run as root: sudo bash install-online.sh"
  exit 1
fi

if [[ ! -r /etc/os-release ]]; then
  echo "ERROR: Cannot identify this Linux distribution."
  exit 1
fi
. /etc/os-release
case "$ID" in
  ubuntu|debian) ;;
  *)
    case " $ID_LIKE " in
      *ubuntu*|*debian*) ;;
      *)
        echo "ERROR: This installer supports Ubuntu and Debian-based systems."
        exit 1
        ;;
    esac
    ;;
esac

NEED_TOOLS=0
command -v curl >/dev/null 2>&1 || NEED_TOOLS=1
command -v tar >/dev/null 2>&1 || NEED_TOOLS=1

if [[ "$NEED_TOOLS" -eq 1 ]]; then
  echo "Installing required download tools..."
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y curl tar ca-certificates
fi

TMP_DIR="$(mktemp -d -t slipstream-panel-install.XXXXXX)"
cleanup() {
  rm -rf -- "$TMP_DIR"
}
trap cleanup EXIT

ARCHIVE="$TMP_DIR/source.tar.gz"
SOURCE_DIR="$TMP_DIR/source"
mkdir -p "$SOURCE_DIR"

echo "Downloading the latest Slipstream Panel source from GitHub..."
curl --fail --location --silent --show-error "$REPO_ARCHIVE" --output "$ARCHIVE"

echo "Extracting project files..."
tar -xzf "$ARCHIVE" --strip-components=1 -C "$SOURCE_DIR"

for file in install.sh app.py slip-manager.py slipstream systemd/slip.service; do
  if [[ ! -f "$SOURCE_DIR/$file" ]]; then
    echo "ERROR: Required project file is missing from the downloaded archive: $file"
    exit 1
  fi
done

echo "Source archive verified. Starting the project installer..."
bash "$SOURCE_DIR/install.sh" "$@"
