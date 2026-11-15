#!/usr/bin/env bash
# O mesmo configurador e usado no Windows, macOS e Linux.
set -u

for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then
    exec "$cmd" "$(dirname "$0")/scripts/configure.py"
  fi
done
echo "Python 3 nao encontrado. Instale-o para configurar o monitor." >&2
exit 1
