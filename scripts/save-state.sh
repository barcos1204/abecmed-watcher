#!/usr/bin/env bash
# Salva somente o estado. Nunca forca push nem sobrescreve um estado concorrente.
set -euo pipefail

if [ -z "$(git status --porcelain -- estado.json)" ]; then
  echo "Estado sem alteracoes."
  exit 0
fi

base_commit=$(git rev-parse HEAD)
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -- estado.json
git commit -m "estado: $(date -u +%Y-%m-%dT%H:%MZ)" -- estado.json

for attempt in 1 2 3; do
  git fetch origin main
  remote_commit=$(git rev-parse origin/main)
  if ! git merge-base --is-ancestor "$base_commit" "$remote_commit"; then
    echo "::error::O historico de main mudou. Execute check novamente."
    exit 1
  fi
  if ! git diff --quiet "$base_commit" "$remote_commit" -- estado.json; then
    echo "::error::O estado remoto mudou durante a consulta; nao foi sobrescrito. Execute check novamente."
    exit 1
  fi
  if ! git rebase origin/main; then
    git rebase --abort
    echo "::error::Conflito ao salvar o estado; nenhuma alteracao remota sobrescrita."
    exit 1
  fi
  if git push origin HEAD:refs/heads/main; then
    exit 0
  fi
  echo "Push nao concluido (tentativa $attempt/3); verificando main novamente."
done

echo "::error::Nao foi possivel salvar o estado apos 3 tentativas."
exit 1
