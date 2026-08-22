#!/usr/bin/env bash
# Cria ou atualiza o config.ini de forma interativa.
set -u

cd "$(dirname "$0")" || exit 1
CONFIG="config.ini"

echo
echo "=== Configuracao do abecmed-watch ==="
echo

# --- valores atuais, se ja existir config
cpf_atual=""
topico_atual=""
if [ -f "$CONFIG" ]; then
  cpf_atual=$(grep -i '^cpf' "$CONFIG" | head -1 | cut -d= -f2- | tr -d ' ')
  topico_atual=$(grep -i '^topico' "$CONFIG" | head -1 | cut -d= -f2- | tr -d ' ')
fi

# --- CPF
while true; do
  if [ -n "$cpf_atual" ]; then
    mascara="***.***.***-${cpf_atual: -2}"
    printf 'CPF do associado [atual: %s, Enter mantem]: ' "$mascara"
  else
    printf 'CPF do associado (so numeros): '
  fi
  read -r cpf
  cpf=$(echo "$cpf" | tr -cd '0-9')

  if [ -z "$cpf" ] && [ -n "$cpf_atual" ]; then
    cpf="$cpf_atual"
    break
  fi
  if [ ${#cpf} -eq 11 ]; then
    break
  fi
  echo "  -> Precisa ter 11 digitos. Voce digitou ${#cpf}."
done

# --- topico ntfy
echo
if [ -n "$topico_atual" ]; then
  printf 'Topico do ntfy [atual: %s, Enter mantem]: ' "$topico_atual"
else
  echo "O topico e o canal onde o app recebe as notificacoes."
  echo "Deixe em branco para eu sortear um seguro pra voce."
  printf 'Topico do ntfy: '
fi
read -r topico
topico=$(echo "$topico" | tr -cd 'a-zA-Z0-9_-')

if [ -z "$topico" ]; then
  if [ -n "$topico_atual" ]; then
    topico="$topico_atual"
  else
    # Le do urandom ate juntar 8 caracteres utilizaveis.
    sufixo=$(LC_ALL=C tr -cd 'a-z0-9' < /dev/urandom 2>/dev/null | head -c 8)
    if [ ${#sufixo} -ne 8 ]; then
      sufixo="${RANDOM}${RANDOM}"   # fallback se nao houver /dev/urandom
    fi
    topico="abecmed-${sufixo}"
    echo "  -> Sorteado: $topico"
  fi
fi

# --- grava
cat > "$CONFIG" <<EOF
# Configuracao do abecmed-watch.
# Gerado por configurar.sh — pode editar na mao se preferir.
# NAO envie este arquivo pro GitHub: ele tem seu CPF.

[abecmed]
cpf = $cpf
topico = $topico

# Intervalo entre verificacoes no modo --loop, em minutos.
# O programa sorteia um valor aleatorio entre os dois a cada ciclo.
intervalo_min = 7
intervalo_max = 12
EOF

chmod 600 "$CONFIG" 2>/dev/null

echo
echo "Salvo em $CONFIG"
echo
echo "PROXIMO PASSO — no app ntfy do celular:"
echo "  toque no + e assine exatamente este topico:"
echo
echo "      $topico"
echo
echo "Depois rode ./run.sh para testar."
echo
