#!/bin/bash
# packaging/build-deb.sh — Build the perseus-smarthome .deb on a Pi (armv7l).
# Usage: bash packaging/build-deb.sh
# Must be run from the repository root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# ---------------------------------------------------------------------------
# 1. Read version from pyproject.toml
# ---------------------------------------------------------------------------
VERSION=$(awk -F'"' '/^version = / {print $2}' "${REPO_ROOT}/pyproject.toml")
if [ -z "${VERSION}" ]; then
  echo "ERROR: could not parse version from pyproject.toml" >&2
  exit 1
fi
echo "==> Version: ${VERSION}"

PKG_NAME="perseus-smarthome_${VERSION}_armhf"
BUILD_DIR="${REPO_ROOT}/_build/${PKG_NAME}"
DIST_DIR="${REPO_ROOT}/dist"

# ---------------------------------------------------------------------------
# 2. Drift check: packaged unit must match canonical unit post-User-substitution
#
# The only permitted difference between the two files is the User= line:
#   canonical:  User=pi
#   packaged:   User=perseus-smarthome
#
# All other fields (ExecStart, WorkingDirectory, Group, Restart, etc.) must
# be identical.  If the canonical unit gains new fields they must also be
# applied to the packaged unit, and this check will catch the divergence.
# ---------------------------------------------------------------------------
CANONICAL_UNIT="${REPO_ROOT}/deploy/systemd/rpi-io-mcp.service"
PACKAGED_UNIT="${SCRIPT_DIR}/debian/perseus-smarthome.service"
# Canonical unit uses the script-install user; the packaged unit uses a
# dedicated system user.  These are the only two values permitted to differ.
CANONICAL_USER="pi"
PACKAGED_USER="perseus-smarthome"

canonical_rendered=$(sed "s/^User=${CANONICAL_USER}$/User=${PACKAGED_USER}/" "${CANONICAL_UNIT}")
packaged_content=$(cat "${PACKAGED_UNIT}")

if [ "${canonical_rendered}" != "${packaged_content}" ]; then
  echo "ERROR: packaging/debian/perseus-smarthome.service has drifted from deploy/systemd/rpi-io-mcp.service." >&2
  echo "       Render deploy/systemd/rpi-io-mcp.service with User=perseus-smarthome and compare:" >&2
  diff <(echo "${canonical_rendered}") <(echo "${packaged_content}") >&2 || true
  exit 1
fi
echo "==> Drift check passed: packaged unit matches canonical unit."

# ---------------------------------------------------------------------------
# 3. Verify apt dependencies can be resolved on the build host
# ---------------------------------------------------------------------------
DEPENDS="liblgpio1 libffi8 adduser systemd libc6 python3"
echo "==> Checking apt dependency resolution..."
for pkg in ${DEPENDS}; do
  # Strip version constraint for lookup (e.g. "python3 (>= 3.13)" -> "python3")
  base_pkg="${pkg%%[[:space:]]*}"
  if ! apt-cache show "${base_pkg}" >/dev/null 2>&1; then
    echo "ERROR: apt dependency '${base_pkg}' cannot be resolved on this host." >&2
    echo "       Run on a Raspberry Pi with the correct apt index." >&2
    exit 1
  fi
done
echo "==> All apt dependencies resolved."

# ---------------------------------------------------------------------------
# 4. Resolve maintainer identity
# ---------------------------------------------------------------------------
if [ -n "${DEB_MAINTAINER:-}" ]; then
  MAINTAINER="${DEB_MAINTAINER}"
else
  GIT_NAME=$(git -C "${REPO_ROOT}" config user.name 2>/dev/null || true)
  GIT_EMAIL=$(git -C "${REPO_ROOT}" config user.email 2>/dev/null || true)
  if [ -z "${GIT_NAME}" ] || [ -z "${GIT_EMAIL}" ]; then
    echo "ERROR: Cannot determine maintainer identity." >&2
    echo "       Set DEB_MAINTAINER env var, or configure git user.name and user.email." >&2
    exit 1
  fi
  MAINTAINER="${GIT_NAME} <${GIT_EMAIL}>"
fi
# Basic RFC 5322 sanity check: the email portion must contain '@'.
case "${MAINTAINER}" in
  *@*) : ;;
  *)
    echo "ERROR: Maintainer email looks invalid: '${MAINTAINER}'" >&2
    echo "       Set DEB_MAINTAINER='Your Name <you@example.com>' to override." >&2
    exit 1
    ;;
esac
echo "==> Maintainer: ${MAINTAINER}"

# ---------------------------------------------------------------------------
# 5. Stage the build tree
# ---------------------------------------------------------------------------
echo "==> Staging build tree in ${BUILD_DIR}..."
rm -rf "${BUILD_DIR}"
mkdir -p \
  "${BUILD_DIR}/DEBIAN" \
  "${BUILD_DIR}/etc/systemd/system" \
  "${BUILD_DIR}/opt/raspberry-smarthome"

# Stage source tree (matching the standard rsync exclude list)
rsync -a --delete \
  --exclude='.git' \
  --exclude='.env' \
  --exclude='.venv' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  --exclude='_build' \
  --exclude='dist' \
  "${REPO_ROOT}/" "${BUILD_DIR}/opt/raspberry-smarthome/"

# Stage the packaged systemd unit (already drift-checked above)
cp "${PACKAGED_UNIT}" "${BUILD_DIR}/etc/systemd/system/rpi-io-mcp.service"

# ---------------------------------------------------------------------------
# 6. Build the virtualenv into the staged tree
# ---------------------------------------------------------------------------
echo "==> Running uv sync --no-dev into staged tree..."
if [ ! -f "${REPO_ROOT}/uv.lock" ]; then
  echo "ERROR: uv.lock not found at ${REPO_ROOT}/uv.lock." >&2
  echo "       Commit a current uv.lock before building the package." >&2
  exit 1
fi
(
  cd "${BUILD_DIR}/opt/raspberry-smarthome"
  uv sync --no-dev
)
echo "==> venv built."

# ---------------------------------------------------------------------------
# 7. Assemble DEBIAN/ control files
# ---------------------------------------------------------------------------
echo "==> Assembling DEBIAN/ control files..."

# Render control with real version and maintainer
sed \
  -e "s/__VERSION__/${VERSION}/" \
  -e "s/__MAINTAINER__/${MAINTAINER}/" \
  "${SCRIPT_DIR}/debian/control" > "${BUILD_DIR}/DEBIAN/control"

cp "${SCRIPT_DIR}/debian/conffiles" "${BUILD_DIR}/DEBIAN/conffiles"
cp "${SCRIPT_DIR}/debian/preinst"   "${BUILD_DIR}/DEBIAN/preinst"
cp "${SCRIPT_DIR}/debian/postinst"  "${BUILD_DIR}/DEBIAN/postinst"
cp "${SCRIPT_DIR}/debian/prerm"     "${BUILD_DIR}/DEBIAN/prerm"
cp "${SCRIPT_DIR}/debian/postrm"    "${BUILD_DIR}/DEBIAN/postrm"

# ---------------------------------------------------------------------------
# 8. Set maintainer-script permissions
# ---------------------------------------------------------------------------
chmod 0755 \
  "${BUILD_DIR}/DEBIAN/preinst" \
  "${BUILD_DIR}/DEBIAN/postinst" \
  "${BUILD_DIR}/DEBIAN/prerm" \
  "${BUILD_DIR}/DEBIAN/postrm"

# ---------------------------------------------------------------------------
# 9. Build the .deb
# ---------------------------------------------------------------------------
mkdir -p "${DIST_DIR}"
DEB_PATH="${DIST_DIR}/perseus-smarthome_${VERSION}_armhf.deb"

echo "==> Building ${DEB_PATH}..."
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${DEB_PATH}"

# ---------------------------------------------------------------------------
# 10. Inspect the result
# ---------------------------------------------------------------------------
echo ""
echo "==> Package info (dpkg-deb -I):"
dpkg-deb -I "${DEB_PATH}"

echo ""
echo "==> Package contents (dpkg-deb -c):"
dpkg-deb -c "${DEB_PATH}"

echo ""
echo "==> Built: ${DEB_PATH}"
