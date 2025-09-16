#!/usr/bin/env bash
set -Eeuo pipefail

>&2 echo "[cobol-parser-mcp] starting (LOG_LEVEL=${LOG_LEVEL:-info}, DIALECT=${COBOL_DIALECT:-COBOL85})"
if [[ ! -f "${PROLEAP_JAR:-/opt/proleap/cb2xml.jar}" ]]; then
  >&2 echo "[cobol-parser-mcp] WARNING: PROLEAP_JAR not found at '${PROLEAP_JAR:-/opt/proleap/cb2xml.jar}'."
  >&2 echo "[cobol-parser-mcp]          You can mount or bake it into the image if you use the ProLeap adapter."
fi

export PYTHONUNBUFFERED=1
export PYTHONPATH="/opt/renova/tools/cobol-parser:${PYTHONPATH:-}"

# pass through args (e.g. --stdio)
exec python -m src.main "$@"
