#!/usr/bin/env bash
set -euo pipefail

# Update these before public use:
OWNER="<OWNER>"
REPO="<REPO>"
TAG="v1.0.0"
ASSET="sullys-music-downloader-macos.zip"

TMP_DIR="$(mktemp -d)"
ZIP_PATH="${TMP_DIR}/${ASSET}"
APP_NAME="sully's music downloader.app"

URL="https://github.com/${OWNER}/${REPO}/releases/download/${TAG}/${ASSET}"
echo "Downloading ${URL}"
curl -L --fail "${URL}" -o "${ZIP_PATH}"

echo "Extracting..."
unzip -q "${ZIP_PATH}" -d "${TMP_DIR}"

APP_PATH="$(find "${TMP_DIR}" -maxdepth 3 -name "${APP_NAME}" -print -quit)"
if [[ -z "${APP_PATH}" ]]; then
  echo "Could not find ${APP_NAME} in archive."
  exit 1
fi

TARGET="/Applications/${APP_NAME}"
rm -rf "${TARGET}"
cp -R "${APP_PATH}" "/Applications/"

echo "Installed to ${TARGET}"
echo "Launch from Applications: ${APP_NAME}"
