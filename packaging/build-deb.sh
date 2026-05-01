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

# ---------------------------------------------------------------------------
# 2. Verify build architecture
# ---------------------------------------------------------------------------
if ! command -v dpkg >/dev/null 2>&1; then
  echo "ERROR: dpkg is required to determine the Debian package architecture" >&2
  exit 1
fi
BUILD_ARCH="$(dpkg --print-architecture)"
if [ "${BUILD_ARCH}" != "armhf" ]; then
  echo "ERROR: unsupported build architecture '${BUILD_ARCH}'; this package must be built on armhf" >&2
  exit 1
fi
echo "==> Debian architecture: ${BUILD_ARCH}"

PKG_NAME="perseus-smarthome_${VERSION}_${BUILD_ARCH}"
BUILD_DIR="${REPO_ROOT}/_build/${PKG_NAME}"
DIST_DIR="${REPO_ROOT}/dist"

# ---------------------------------------------------------------------------
# 3. Drift check: packaged unit must match canonical unit post-User-substitution
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
# The packaged unit uses a dedicated system user; the canonical unit uses
# the script-install user. The User= line is the only value permitted to
# differ. Use the same broad `^User=.*` anchor that scripts/install.sh
# uses for its at-install rewrite — anchoring the canonical user to a
# specific literal (e.g. "pi") would cause this drift check to silently
# pass in the corner case where someone manually edited both unit files
# to agree on a non-canonical user value.
PACKAGED_USER="perseus-smarthome"

canonical_rendered=$(sed "s|^User=.*|User=${PACKAGED_USER}|" "${CANONICAL_UNIT}")
packaged_content=$(cat "${PACKAGED_UNIT}")

if [ "${canonical_rendered}" != "${packaged_content}" ]; then
  echo "ERROR: packaging/debian/perseus-smarthome.service has drifted from deploy/systemd/rpi-io-mcp.service." >&2
  echo "       Render deploy/systemd/rpi-io-mcp.service with User=perseus-smarthome and compare:" >&2
  diff <(echo "${canonical_rendered}") <(echo "${packaged_content}") >&2 || true
  exit 1
fi
echo "==> Drift check passed: packaged unit matches canonical unit."

# ---------------------------------------------------------------------------
# 4. Verify apt dependencies can be resolved on the build host
# Parse the package names from the Depends: line in the control template so
# there is one source of truth instead of a hardcoded duplicate list here.
# ---------------------------------------------------------------------------
DEPENDS_LINE=$(awk '/^Depends:/ { gsub(/^Depends:[[:space:]]*/, ""); print }' "${SCRIPT_DIR}/debian/control")
echo "==> Checking apt dependency resolution..."
IFS=',' read -r -a dep_entries <<< "${DEPENDS_LINE}"
for entry in "${dep_entries[@]}"; do
  # Extract first word from each entry (strips version constraints like "(>= 3.13)").
  base_pkg=$(printf '%s' "${entry}" | awk '{print $1}')
  [ -z "${base_pkg}" ] && continue
  if ! apt-cache show "${base_pkg}" >/dev/null 2>&1; then
    echo "ERROR: apt dependency '${base_pkg}' cannot be resolved on this host." >&2
    echo "       Run on a Raspberry Pi with the correct apt index." >&2
    exit 1
  fi
done
echo "==> All apt dependencies resolved."

# ---------------------------------------------------------------------------
# 5. Resolve maintainer identity
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
# 6. Stage the build tree
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
# 7. Build the virtualenv into the staged tree
# ---------------------------------------------------------------------------
echo "==> Running uv sync --no-dev --no-editable into staged tree..."
if [ ! -f "${REPO_ROOT}/uv.lock" ]; then
  echo "ERROR: uv.lock not found at ${REPO_ROOT}/uv.lock." >&2
  echo "       Commit a current uv.lock before building the package." >&2
  exit 1
fi
# --no-editable installs the project as a wheel inside site-packages instead
# of dropping a `.pth` pointer at the build directory. Without it, the
# installed venv tries to import perseus_smarthome from a path that only
# exists on the build host.
(
  cd "${BUILD_DIR}/opt/raspberry-smarthome"
  uv sync --no-dev --no-editable
)

# uv creates the venv with its absolute build-time path baked into every
# entry-point shebang and into bookkeeping files like direct_url.json.
# After dpkg-deb installs the payload, the venv sits at
# /opt/raspberry-smarthome/.venv, so every reference to the build prefix
# must be rewritten or the kernel exits 203/EXEC ("interpreter not found")
# when systemd tries to spawn rpi-io-mcp.
echo "==> Rewriting venv build-path references to runtime path..."
RUNTIME_ROOT="/opt/raspberry-smarthome"
BUILD_OPT_ROOT="${BUILD_DIR}/opt/raspberry-smarthome"
# Escape every metachar that would corrupt the sed replacement: the `|`
# delimiter used below, the `/` path separator, the `&` back-reference,
# and the literal `\`. Without `|`, a future build path containing `|`
# would silently truncate the replacement text.
ESCAPED_BUILD=$(printf '%s' "${BUILD_OPT_ROOT}" | sed 's/[|\/&\\]/\\&/g')
ESCAPED_RUNTIME=$(printf '%s' "${RUNTIME_ROOT}" | sed 's/[|\/&\\]/\\&/g')
while IFS= read -r f; do
  [ -L "$f" ] && continue
  sed -i "s|${ESCAPED_BUILD}|${ESCAPED_RUNTIME}|g" "$f"
done < <(grep -rlF --binary-files=without-match "${BUILD_OPT_ROOT}" "${BUILD_OPT_ROOT}/.venv" 2>/dev/null || true)

echo "==> venv built."

# ---------------------------------------------------------------------------
# 8. Assemble DEBIAN/ control files
# ---------------------------------------------------------------------------
echo "==> Assembling DEBIAN/ control files..."

# Escape characters that are meaningful to sed's replacement string when using
# '|' as the delimiter: '|', '&', and '\'.  This prevents a maintainer name
# or email containing any of those characters from corrupting the control file.
ESCAPED_VERSION=$(printf '%s' "${VERSION}"    | sed 's/[|&\]/\\&/g')
ESCAPED_MAINTAINER=$(printf '%s' "${MAINTAINER}" | sed 's/[|&\]/\\&/g')

# Render control with real version and maintainer
sed \
  -e "s|__VERSION__|${ESCAPED_VERSION}|" \
  -e "s|__MAINTAINER__|${ESCAPED_MAINTAINER}|" \
  "${SCRIPT_DIR}/debian/control" > "${BUILD_DIR}/DEBIAN/control"

cp "${SCRIPT_DIR}/debian/conffiles" "${BUILD_DIR}/DEBIAN/conffiles"
cp "${SCRIPT_DIR}/debian/preinst"   "${BUILD_DIR}/DEBIAN/preinst"
cp "${SCRIPT_DIR}/debian/postinst"  "${BUILD_DIR}/DEBIAN/postinst"
cp "${SCRIPT_DIR}/debian/prerm"     "${BUILD_DIR}/DEBIAN/prerm"
cp "${SCRIPT_DIR}/debian/postrm"    "${BUILD_DIR}/DEBIAN/postrm"

# ---------------------------------------------------------------------------
# 9. Set maintainer-script permissions
# ---------------------------------------------------------------------------
chmod 0755 \
  "${BUILD_DIR}/DEBIAN/preinst" \
  "${BUILD_DIR}/DEBIAN/postinst" \
  "${BUILD_DIR}/DEBIAN/prerm" \
  "${BUILD_DIR}/DEBIAN/postrm"

# ---------------------------------------------------------------------------
# 10. Build the .deb
# ---------------------------------------------------------------------------
mkdir -p "${DIST_DIR}"
DEB_PATH="${DIST_DIR}/perseus-smarthome_${VERSION}_${BUILD_ARCH}.deb"

echo "==> Building ${DEB_PATH}..."
dpkg-deb --build --root-owner-group "${BUILD_DIR}" "${DEB_PATH}"

# ---------------------------------------------------------------------------
# 11. Inspect the result
# ---------------------------------------------------------------------------
echo ""
echo "==> Package info (dpkg-deb -I):"
dpkg-deb -I "${DEB_PATH}"

echo ""
echo "==> Package contents (dpkg-deb -c):"
dpkg-deb -c "${DEB_PATH}"

echo ""
echo "==> Built: ${DEB_PATH}"
