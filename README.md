# abecmed-watcher

Avisa pelo ntfy quando o catálogo do bot da ABECMED muda. As notificações de
flores separam o que entrou, o que permaneceu e o que saiu do estoque.

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

**4. Rode.** `run.bat` ou `./run.sh`. Sem um estado anterior, envia a lista atual.
Depois disso, só avisa quando há mudança. Como o repositório pode já conter
`estado.json`, use o envio manual abaixo para receber uma lista imediatamente.

Para deixar ligado sozinho: `run-loop.bat` ou `./run.sh --loop`. Verifica a
cada 7–12 minutos (sorteado) até você fechar a janela ou apertar Ctrl+C.

| | Windows | Linux / macOS |
|---|---|---|
| configurar | `configurar.bat` | `./configurar.sh` |
| rodar uma vez | `run.bat` | `./run.sh` |
| modo contínuo | `run-loop.bat` | `./run.sh --loop` |
| testar sem notificar | — | `./run.sh --dry-run` |
| enviar estoque atual | `python bot.py --notify-current` | `./run.sh --notify-current` |

> Tópicos do ntfy.sh são públicos: quem souber o nome recebe seus avisos.
> Aceite o nome sorteado pelo configurador.

## config.ini

Criado pelo configurador, editável no Bloco de Notas:

```ini
[abecmed]
cpf = SEU_CPF_DE_ASSOCIADO
topico = SEU_TOPICO_NTFY

intervalo_min = 7
intervalo_max = 12
```

Rodar o configurador de novo é seguro: Enter mantém o valor atual.

**Não versione** — tem seu CPF. Já está no `.gitignore`. As variáveis de
ambiente `ABECMED_CPF` e `NTFY_TOPIC`, se existirem, têm prioridade.

Para conferir o estoque sem esperar uma mudança, use `--notify-current`.
Isso não apaga nem altera a referência salva em `estado.json`.

## Rodar na nuvem (opcional)

Sem servidor, sem deixar o PC ligado:

1. Fork deste repositório.
2. **Settings → Secrets and variables → Actions**: crie `ABECMED_CPF` e `NTFY_TOPIC`.
3. **Settings → Actions → General → Workflow permissions**: marque **Read and write**
   (sem isso falha com 403).
4. Aba **Actions**, habilite e rode `check` uma vez à mão.

O workflow `check` funciona na branch `main`. Está agendado a cada 10 minutos,
com uma espera aleatória de até 5 minutos antes da consulta. O GitHub pode
atrasar execuções: isso não é uma garantia de horário ou de monitoramento
contínuo. O modo local `--loop` sorteia seu próprio intervalo.

### Receber o estoque atual agora

1. Abra **Actions → check → Run workflow**.
2. Selecione **main**.
3. Marque **Enviar o estoque atual ao ntfy** e execute.

Esse envio mostra todas as strains disponíveis, mesmo sem mudança. Não altera
o estado nem inventa entradas ou saídas. Uma execução normal bem-sucedida e sem
mudanças não envia mensagem. Fazer merge de um PR também não força um envio.

## Formato das notificações

Exemplo ilustrativo de mudança (os nomes não representam o estoque real):

```text
Novidades:
- Strain C

Em estoque:
- Strain B

Sem estoque:
- Strain A
```

- **Novidades:** opções que não estavam na consulta anterior e estão agora.
- **Em estoque:** opções que continuam disponíveis; as novidades não se repetem aqui.
- **Sem estoque:** opções que estavam antes e acabaram de sair.

Cada seção sem itens mostra `- Nenhuma.`. As entradas e saídas se referem à
última mudança detectada, não a um histórico acumulado. As notificações antigas
continuam no histórico do ntfy; o script não as edita nem apaga.

O conteúdo enviado é texto simples, sem depender de suporte a negrito ou
riscado. Listas longas são divididas em mensagens numeradas `(1/2)`, `(2/2)` etc.,
respeitando um orçamento de 3.500 bytes UTF-8 por parte, sem truncar as strains.

## Como funciona

Abre uma sessão no Typebot da associação e navega pelos avisos iniciais →
paciente → CPF → menu → flores → THC, quando essa escolha existe. Também
consulta concentrados/óleo quando esse ramo está disponível. Compara o relatório
com a rodada anterior (`estado.json`).

Não interpreta nome nem preço: cada opção é comparada pelo texto completo.
Por isso, uma troca de preço ou de nome aparece como saída do texto antigo e
entrada do novo. Só mudar a ordem das flores não gera aviso. Uma alteração no
texto ou em outra seção ainda gera um aviso, mas informa que as opções de
flores continuam iguais, sem repetir menus e instruções no corpo da mensagem.

Uma resposta sem opções de flores é tratada conservadoramente como consulta
incompleta, não como prova de que tudo esgotou. Nesse caso, mantém o estoque
anterior e pede verificação do fluxo.

Precisa do CPF de um **associado** — é assim que o bot identifica quem está
falando. Sem CPF válido a conversa não passa da segunda tela. As requisições
usam cabeçalhos de navegador; não burla autenticação (o bot não tem nenhuma),
serve pra não ser barrado pela proteção anti-bot da hospedagem.

## Quando quebrar

Vai quebrar quando a associação mexer no fluxo. Chega um aviso
**"abecmed-watch quebrou"** com o erro relevante. Isso também pode ocorrer por
indisponibilidade temporária da rede ou do serviço. O controle do aviso fica
salvo em `estado.json`: após o ntfy aceitar o alerta, não o repete a cada nova
execução do Actions. Quando a consulta volta a funcionar, envia um aviso de
recuperação. O último catálogo válido é preservado durante as falhas.

Se for uma mudança de fluxo, o ajuste costuma estar em `collect()`, dentro de
`bot.py`:

```python
chat.pick(r"flor")
chat.pick(r"concentrad")
chat.pick(r"[óo]leo")
```

## Confiabilidade e diagnóstico

- O estado só avança depois que o ntfy confirma todas as partes do aviso.
  Nos logs aparece o ID aceito pelo servidor, sem imprimir o tópico ou o CPF
  nessa confirmação. Isso confirma a publicação, não a entrega ao celular.
- Se uma publicação falhar, a próxima consulta tenta novamente. Se parte de
  uma mensagem já foi aceita antes da falha, essa parte pode se repetir.
- A gravação local de `estado.json` usa substituição atômica. Um JSON inválido
  interrompe a execução, preservando o arquivo para diagnóstico.
- No Actions, o estado do alerta de falha é salvo mesmo quando a consulta falha;
  o workflow continua indicando falha. O checkout usa a versão atual de `main`.
- Se houver um commit concorrente só de código, o salvamento reaplica o commit
  de estado e tenta o push novamente, até 3 vezes, sem force push. Se o estado
  remoto também mudou, para com erro, sem sobrescrevê-lo. Rode `check` novamente.
- Caso o envio seja aceito mas a gravação/push do estado falhe, um aviso pode
  se repetir na próxima rodada. Não há promessa de entrega exatamente uma vez.

## Testes

```sh
python3 -m unittest discover -s tests -v
```

Os testes não consultam a associação nem enviam notificações: usam respostas
simuladas e repositórios Git locais temporários. Cobrem o formato, diferenças
de estoque, reordenação, preços, limites UTF-8, falhas/recuperação, envio manual,
gravação atômica e concorrência ao salvar o estado. O workflow `tests` os executa
nos PRs, sem usar os secrets do monitor.

---

MIT. Sem vínculo com a ABECMED — ferramenta de conveniência, de associado para associado.
