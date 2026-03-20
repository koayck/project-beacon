#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run with sudo: sudo bash scripts/install_starlink_nm_dispatcher.sh"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TOGGLE_SCRIPT="${REPO_ROOT}/scripts/toggle_starlink_tc.sh"
TARGET_SSID_DEFAULT="${TARGET_SSID:-Starlink}"
DISPATCHER_PATH="/etc/NetworkManager/dispatcher.d/90-project-beacon-starlink-tc"

if [[ ! -x "${TOGGLE_SCRIPT}" ]]; then
  echo "Missing executable toggle script: ${TOGGLE_SCRIPT}"
  exit 1
fi

cat > "${DISPATCHER_PATH}" <<DISPATCH
#!/usr/bin/env bash
set -euo pipefail

TARGET_SSID="\${TARGET_SSID:-${TARGET_SSID_DEFAULT}}"
TOGGLE_SCRIPT="${TOGGLE_SCRIPT}"

if ! command -v nmcli >/dev/null 2>&1; then
  exit 0
fi

ssids="\$(nmcli -t -f active,ssid dev wifi 2>/dev/null | awk -F: '\$1 == "yes" {print \$2}')"
if grep -Fxq "\${TARGET_SSID}" <<<"\${ssids}"; then
  mode="starlink"
else
  mode="direct"
fi

STARLINK_MOCK_SOURCE="nm-dispatcher" TARGET_SSID="\${TARGET_SSID}" "\${TOGGLE_SCRIPT}" "\${mode}" >/dev/null 2>&1 || true
exit 0
DISPATCH

chmod 755 "${DISPATCHER_PATH}"
echo "Installed NetworkManager dispatcher at ${DISPATCHER_PATH}"
echo "Target SSID: ${TARGET_SSID_DEFAULT}"
