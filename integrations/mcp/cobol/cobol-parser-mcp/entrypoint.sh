#!/usr/bin/env bash
set -Eeuo pipefail

>&2 echo "[cobol-parser-mcp] starting (LOG_LEVEL=${LOG_LEVEL:-info}, DIALECT=${COBOL_DIALECT:-COBOL85})"

# Helpful environment echo for debugging volumes / paths
>&2 echo "[cobol-parser-mcp] WORKSPACE_HOST=${WORKSPACE_HOST:-} WORKSPACE_CONTAINER=${WORKSPACE_CONTAINER:-}"
>&2 echo "[cobol-parser-mcp] CB2XML_CLASSPATH=${CB2XML_CLASSPATH:-} PROLEAP_CLASSPATH=${PROLEAP_CLASSPATH:-}"

# Print a readiness line (your transport doesn’t require it, but it helps ops)
>&2 echo "mcp server ready"
