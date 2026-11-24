#!/usr/bin/env bash
# Fetch the ASK 5.0a Vehicle Interface Volume, which tests/test_wire_surface.py
# reads Table 1-38 (VI MMS) out of.
#
# Table 1-38 is the authority on which messages a Level 1 VI must support and
# in which direction — MA-L1-015 makes it a compliance requirement, and the
# volume states the Direction column is "relative to the VI interface". Without
# it the surface test can only check FEATURES against the implementation, which
# is the wrong way round: it forces the documentation to match whatever the code
# happens to do.
#
# Same stance as the schema: the standard is public (Distribution Statement A)
# but not redistributed here. Files land in schema/a-gra/, gitignored, verified
# against scripts/agra-spec.sha256. Pinned at the v5.0a tag.
#
# Separate from fetch-agra-schema.sh on purpose: XSD validation must not break
# because a PDF moved.
#
# Override the source with AGRA_SPEC_URL or the destination with
# AGRA_SPEC_DIR.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASE="${AGRA_SPEC_URL:-https://gitlab.com/open-arsenal/a-gra/standard/-/raw/v5.0a/Documentation}"
DEST="${AGRA_SPEC_DIR:-schema/a-gra}"
DIGESTS="$ROOT/scripts/agra-spec.sha256"

FILES=("ASK 5.0a Vehicle Interface Volume.pdf")

if command -v sha256sum >/dev/null 2>&1; then
  CHECK=(sha256sum -c --status); GEN=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  CHECK=(shasum -a 256 -c --status); GEN=(shasum -a 256)
else
  echo "need sha256sum or shasum to verify the download" >&2
  exit 1
fi

verify() {
  [ -d "$DEST" ] || return 1
  for f in "${FILES[@]}"; do [ -f "$DEST/$f" ] || return 1; done
  (cd "$DEST" && "${CHECK[@]}" "$DIGESTS") >/dev/null 2>&1
}

if verify; then
  echo "spec already present and verified in $DEST/"
else
  mkdir -p "$DEST"
  for f in "${FILES[@]}"; do
    echo "fetching $f …"
    tmp="$(mktemp)"
    # URL-encode spaces; the published filenames contain them.
    enc="${f// /%20}"
    if ! curl -sSfL --max-time 300 "$BASE/$enc" -o "$tmp"; then
      rm -f "$tmp"
      echo "could not download $BASE/$enc" >&2
      exit 1
    fi
    mv "$tmp" "$DEST/$f"
    chmod 644 "$DEST/$f"
  done

  if ! verify; then
    {
      echo
      echo "Checksum mismatch: $BASE"
      echo "does not serve what scripts/agra-spec.sha256 pins. Upstream has"
      echo "most likely published a new revision of the volume."
      echo
      echo "Review the change, then re-pin with:"
      echo "  (cd $DEST && ${GEN[*]} \"${FILES[0]}\") > scripts/agra-spec.sha256"
    } >&2
    exit 1
  fi
fi

cat <<EOF

Spec ready. tests/test_wire_surface.py reads Table 1-38 from it
automatically.
EOF
