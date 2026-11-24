#!/usr/bin/env bash
# Fetch the A-GRA 5.0a schema documents that tests/test_wire_xsd.py
# validates the published wire corpus against.
#
# The standard is public — Distribution Statement A, approved for public
# release — but it is not redistributed in this repository. Files land in
# schema/a-gra/, which is gitignored, and are checked against the digests
# pinned in scripts/agra-schema.sha256 so you always know which revision you
# are running. Same source, tag, and digests as oa-gateway's
# scripts/fetch-agra-schema.sh: the two repositories must agree on what
# "A-GRA 5.0a" means or their conformance results are not comparable.
#
# Pinned at the v5.0a tag, not main: open-arsenal/a-gra/standard has since
# moved main to A-GRA 6.0a, which open-vi does not target. AGRA_SCHEMA_VERSION
# on the wire is 005.0a to match.
#
# Override the source with AGRA_SCHEMA_URL or the destination with
# AGRA_SCHEMA_DIR, for a program-specific Message Set or an offline mirror.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BASE="${AGRA_SCHEMA_URL:-https://gitlab.com/open-arsenal/a-gra/standard/-/raw/v5.0a/Schema}"
DEST="${AGRA_SCHEMA_DIR:-schema/a-gra}"
DIGESTS="$ROOT/scripts/agra-schema.sha256"

# Both are required: the message definitions xs:include the security markings,
# and compiling without them leaves types unresolved.
FILES=(A-GRA_MessageDefinitions_v5_0_a.xsd A-GRA_SecurityMarkings_v5_0_a.xsd)

if command -v sha256sum >/dev/null 2>&1; then
  CHECK=(sha256sum -c --status)
  GEN=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  CHECK=(shasum -a 256 -c --status)
  GEN=(shasum -a 256)
else
  echo "need sha256sum or shasum to verify the download" >&2
  exit 1
fi

verify() {
  [ -d "$DEST" ] || return 1
  for f in "${FILES[@]}"; do
    [ -f "$DEST/$f" ] || return 1
  done
  (cd "$DEST" && "${CHECK[@]}" "$DIGESTS") >/dev/null 2>&1
}

if verify; then
  echo "schema already present and verified in $DEST/"
else
  mkdir -p "$DEST"
  for f in "${FILES[@]}"; do
    echo "fetching $f …"
    tmp="$(mktemp)"
    # Download to a temporary file so an interrupted run cannot leave a
    # partial schema behind that later looks like a checksum failure.
    if ! curl -sSfL --max-time 300 "$BASE/$f" -o "$tmp"; then
      rm -f "$tmp"
      echo "could not download $BASE/$f" >&2
      exit 1
    fi
    mv "$tmp" "$DEST/$f"
    chmod 644 "$DEST/$f"
  done

  if ! verify; then
    {
      echo
      echo "Checksum mismatch: $BASE"
      echo "does not serve what scripts/agra-schema.sha256 pins. Upstream has"
      echo "most likely published a new revision."
      echo
      echo "Review the change, then re-pin with:"
      echo "  (cd $DEST && ${GEN[*]} ${FILES[*]}) > scripts/agra-schema.sha256"
    } >&2
    exit 1
  fi
fi

cat <<EOF

Schema ready. tests/test_wire_xsd.py finds it automatically; to point
elsewhere:

  UCI_XSD=$DEST/${FILES[0]} pytest tests/test_wire_xsd.py
EOF
