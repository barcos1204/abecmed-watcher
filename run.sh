#!/usr/bin/env bash
# Roda o monitor uma vez. Use --dry-run para testar sem notificar.
set -u

cd "$(dirname "$0")" || exit 1

# Acha o Python (algumas distros so tem 'python')
PY=""
for cmd in python3 python; do
  if command -v "$cmd" >/dev/null 2>&1; then PY="$cmd"; break; fi
done

if [ -z "$PY" ]; then
  echo "ERRO: Python nao encontrado."
  echo "Instale com: sudo apt install python3     (Ubuntu/Debian)"
  echo "         ou: brew install python3         (macOS)"
  exit 1
fi

if [ ! -f config.ini ]; then
  echo "Ainda nao configurado. Rodando o configurador..."
  echo
  ./configurar.sh || exit 1
fi

exec "$PY" bot.py "$@"
