# abecmed-watcher

Avisa no celular quando o catálogo do bot da ABECMED muda — flor nova, óleo
voltando ao estoque, preço diferente.

Só Python 3, sem instalar dependência nenhuma.

## Passo a passo

**1. Instale o app.** Procure por **ntfy** na Play Store ou App Store. Grátis,
sem cadastro. É por ele que os avisos chegam.

**2. Baixe o projeto.** Botão verde **Code → Download ZIP**, extraia numa pasta.
No Windows, instale o Python de [python.org](https://python.org) marcando
**"Add Python to PATH"** — sem essa caixinha nada funciona. No Ubuntu e macOS
já vem de fábrica.

**3. Configure.** Rode `configurar.bat` (Windows, dois cliques) ou
`./configurar.sh` (Linux/macOS). Ele pede seu CPF de associado e o canal de
avisos — aperte Enter no canal que ele sorteia um nome seguro. **No fim, abra o
ntfy, toque no + e assine o nome que ele mostrar.**

**4. Rode.** `run.bat` ou `./run.sh`. O celular apita com o catálogo atual — é
a confirmação de que funcionou. Depois disso, **só avisa quando muda**.

Para deixar ligado sozinho: `run-loop.bat` ou `./run.sh --loop`. Verifica a
cada 7–12 minutos (sorteado) até você fechar a janela ou apertar Ctrl+C.

| | Windows | Linux / macOS |
|---|---|---|
| configurar | `configurar.bat` | `./configurar.sh` |
| rodar uma vez | `run.bat` | `./run.sh` |
| modo contínuo | `run-loop.bat` | `./run.sh --loop` |
| testar sem notificar | — | `./run.sh --dry-run` |

> Tópicos do ntfy.sh são públicos: quem souber o nome recebe seus avisos.
> Aceite o nome sorteado pelo configurador.

## config.ini

Criado pelo configurador, editável no Bloco de Notas:

```ini
[abecmed]
cpf = 12345678900
topico = abecmed-jepv8l0v

intervalo_min = 7
intervalo_max = 12
```

Rodar o configurador de novo é seguro: Enter mantém o valor atual.

**Não versione** — tem seu CPF. Já está no `.gitignore`. As variáveis de
ambiente `ABECMED_CPF` e `NTFY_TOPIC`, se existirem, têm prioridade.

Apagar o `estado.json` faz a próxima execução mandar o catálogo inteiro de novo
— útil pra reconfirmar que está funcionando sem esperar o estoque mudar.

## Rodar na nuvem (opcional)

Sem servidor, sem deixar o PC ligado:

1. Fork deste repositório.
2. **Settings → Secrets and variables → Actions**: crie `ABECMED_CPF` e `NTFY_TOPIC`.
3. **Settings → Actions → General → Workflow permissions**: marque **Read and write**
   (sem isso falha com 403).
4. Aba **Actions**, habilite e rode `check` uma vez à mão.

O cron do Actions não aceita intervalo sorteado — roda a cada 10 min com jitter.

## Como funciona

Abre uma sessão no Typebot da associação e navega sozinho: paciente → CPF →
menu → flores → concentrados → óleo. Junta o texto das telas, compara com a
rodada anterior (`estado.json`), notifica se mudou.

**Não interpreta nome nem preço** — compara o texto inteiro. Menos elegante,
muito mais difícil de quebrar: o aviso entrega o texto literal que o bot
escreveu, já legível. Em compensação, qualquer alteração dispara notificação,
inclusive um typo corrigido ou emoji trocado.

Precisa do CPF de um **associado** — é assim que o bot identifica quem está
falando. Sem CPF válido a conversa não passa da segunda tela. As requisições
usam cabeçalhos de navegador; não burla autenticação (o bot não tem nenhuma),
serve pra não ser barrado pela proteção anti-bot da hospedagem.

## Quando quebrar

Vai quebrar quando a associação mexer no fluxo. Chega um aviso
**"abecmed-watch quebrou"** com as opções que não foram reconhecidas — uma vez
por sequência de falhas, não a cada ciclo. O conserto costuma ser um regex em
`collect()`, dentro do `bot.py`:

```python
chat.pick(r"flor")
chat.pick(r"concentrad")
chat.pick(r"[óo]leo")
```

---

MIT. Sem vínculo com a ABECMED — ferramenta de conveniência, de associado para associado.
