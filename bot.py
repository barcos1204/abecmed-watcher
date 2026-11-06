#!/usr/bin/env python3
"""
abecmed-watch — avisa quando o catalogo do bot da ABECMED muda.

O site (bot.abecmed.com.br) e um Typebot. Este script percorre o fluxo
de conversa como se fosse um navegador, junta o texto das telas de
produto num relatorio, e compara com a execucao anterior. Se mudou,
notifica via ntfy.sh.

Compara as opcoes de flores sem interpretar nome/preco. Mudancas apenas
na ordem das strains nao geram notificacao.

Configuracao, em ordem de prioridade:
    1. variaveis de ambiente ABECMED_CPF e NTFY_TOPIC (usado no GitHub Actions)
    2. arquivo config.ini ao lado deste script (use ./configurar.sh)

Uso:
    ./run.sh                          # ou run.bat no Windows
    python3 bot.py --dry-run          # roda, imprime, nao notifica nem salva
"""

import argparse
import configparser
import gzip
import json
import os
import random
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))

BASE = "https://bot.abecmed.com.br"
# Identificador atual do bot. O site e consultado antes de cada conversa para
# descobrir automaticamente um novo publicId caso a ABECMED publique outra versao.
TYPEBOT = "bot-abecmed-2-1"
NTFY_BASE = "https://ntfy.sh"

# Cabecalhos identicos aos que o Firefox manda nesse site. Alem de evitar
# bloqueio por protecao anti-bot da Vercel, mantem a requisicao consistente:
# UA de navegador com headers de script destoa mais do que nao mascarar nada.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:154.0) "
        "Gecko/20100101 Firefox/154.0"
    ),
    "Accept": "*/*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip",
    "Content-Type": "application/json",
    "Origin": BASE,
    "Referer": BASE + "/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

TIMEOUT = 30
RETRIES = 3

# Intervalo do modo --loop, em minutos. Sorteado a cada ciclo.
INTERVALO_MIN = 7
INTERVALO_MAX = 12

# Blocos do richText que viram quebra de linha no texto plano.
BLOCK_TYPES = {"p", "ul", "ol", "li", "h1", "h2", "h3", "blockquote"}

# Orcamento por mensagem em bytes UTF-8, com folga para o limite do ntfy.
MAX_MSG = 3500


class FlowError(Exception):
    """O fluxo do Typebot nao esta onde a gente esperava."""


# ---------------------------------------------------------------- HTTP


def post_json(url, payload, headers=None):
    body = json.dumps(payload).encode("utf-8")
    base_headers = dict(BROWSER_HEADERS)
    base_headers.update(headers or {})
    # Valor None = remover o header (usado pra tirar o disfarce ao falar com o ntfy).
    base_headers = {k: v for k, v in base_headers.items() if v is not None}

    last_error = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, data=body, method="POST", headers=base_headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                text = raw.decode("utf-8")
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as exc:
            last_error = exc
            # 4xx nao adianta repetir.
            if exc.code < 500:
                detail = exc.read().decode("utf-8", "replace")[:300]
                raise FlowError("HTTP %s em %s: %s" % (exc.code, url, detail)) from exc
        except Exception as exc:  # rede, timeout, JSON invalido
            last_error = exc
        if attempt < RETRIES - 1:
            time.sleep(2 ** attempt)

    raise FlowError("falhou apos %d tentativas em %s: %s" % (RETRIES, url, last_error))


def get_text(url, headers=None):
    """Baixa uma pagina de texto usando os mesmos cabecalhos do navegador."""
    base_headers = dict(BROWSER_HEADERS)
    base_headers.update(headers or {})
    base_headers.pop("Content-Type", None)

    last_error = None
    for attempt in range(RETRIES):
        req = urllib.request.Request(url, method="GET", headers=base_headers)
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8")
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500:
                raise FlowError("HTTP %s em %s" % (exc.code, url)) from exc
        except Exception as exc:
            last_error = exc
        if attempt < RETRIES - 1:
            time.sleep(2 ** attempt)

    raise FlowError("falhou apos %d tentativas em %s: %s" % (RETRIES, url, last_error))


def discover_typebot():
    """Descobre o publicId publicado na pagina, com fallback para o atual."""
    configured = os.environ.get("ABECMED_TYPEBOT", "").strip()
    if configured:
        return configured

    try:
        page = get_text(BASE + "/")
    except FlowError:
        return TYPEBOT

    match = re.search(r'"publicId"\s*:\s*"([a-zA-Z0-9_-]+)"', page)
    return match.group(1) if match else TYPEBOT


# ------------------------------------------------------- richText -> texto


def flatten(node):
    """Achata a arvore richText do Typebot em texto plano legivel."""
    if isinstance(node, list):
        return "".join(flatten(n) for n in node)
    if not isinstance(node, dict):
        return ""

    children = node.get("children")
    if children is None:
        return node.get("text", "")

    inner = flatten(children)
    kind = node.get("type")

    if kind == "li":
        return "- " + inner.strip() + "\n"
    if kind in BLOCK_TYPES:
        return inner + "\n"
    return inner


def messages_to_text(messages):
    """Junta as bolhas de uma resposta num bloco de texto."""
    parts = []
    for msg in messages:
        content = msg.get("content") or {}
        if content.get("type") == "richText":
            parts.append(flatten(content.get("richText", [])))
        elif "url" in content:
            parts.append("[%s] %s" % (msg.get("type", "midia"), content["url"]))
    return tidy("\n".join(parts))


def tidy(text):
    """Tira espaco no fim das linhas e colapsa linhas em branco repetidas."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    out = []
    for line in lines:
        if not line and out and not out[-1]:
            continue
        out.append(line)
    return "\n".join(out).strip()


# ------------------------------------------------------------- conversa


class Chat:
    def __init__(self):
        public_id = discover_typebot()
        self.last = post_json(
            "%s/api/v1/typebots/%s/startChat" % (BASE, public_id),
            {"isStreamEnabled": False, "prefilledVariables": {}, "isOnlyRegistering": False},
            headers={"Origin": BASE, "Referer": BASE + "/"},
        )
        self.session_id = self.last.get("sessionId")
        if not self.session_id:
            raise FlowError("startChat nao devolveu sessionId")

    @property
    def items(self):
        payload = self.last.get("input") or {}
        return [i.get("content", "") for i in payload.get("items", [])]

    @property
    def input_type(self):
        return (self.last.get("input") or {}).get("type")

    @property
    def text(self):
        return messages_to_text(self.last.get("messages", []))

    def send(self, text):
        self.last = post_json(
            "%s/api/v1/sessions/%s/continueChat" % (BASE, self.session_id),
            {"message": {"type": "text", "text": text}},
            headers={"Origin": BASE, "Referer": BASE + "/"},
        )
        return self.last

    def pick(self, pattern, required=True):
        """Escolhe a opcao cujo texto casa com o regex. Devolve o texto escolhido."""
        rx = re.compile(pattern, re.I)
        for content in self.items:
            if rx.search(content):
                self.send(content)
                return content
        if required:
            raise FlowError(
                "nenhuma opcao casou com /%s/ — opcoes: %r" % (pattern, self.items)
            )
        return None


# ----------------------------------------------------------------- fluxo

MENU_HINT = re.compile(r"flor|concentrad|[óo]leo", re.I)
PATIENT_HINT = re.compile(r"\bpaciente\b", re.I)
GO_ON = re.compile(
    r"\bciente\b|\bentendi\b|continuar|prosseguir|avan[çc]ar|come[çc]ar|^ok$",
    re.I,
)


def reach_patient(chat, max_hops=5):
    """Avanca por comunicados ate aparecer a opcao de paciente."""
    for _ in range(max_hops):
        if any(PATIENT_HINT.search(i) for i in chat.items):
            return
        if chat.pick(GO_ON.pattern, required=False):
            continue
        if len(chat.items) == 1:
            chat.send(chat.items[0])
            continue
        raise FlowError("nao cheguei na entrada de paciente — opcoes: %r" % (chat.items,))
    raise FlowError("nao cheguei na entrada de paciente depois de %d telas" % max_hops)


def reach_menu(chat, max_hops=5):
    """Avanca por telas intermediarias ate chegar no menu principal."""
    for _ in range(max_hops):
        if any(MENU_HINT.search(i) for i in chat.items):
            return
        if chat.pick(GO_ON.pattern, required=False):
            continue
        if len(chat.items) == 1:  # tela de "ok" com nome diferente
            chat.send(chat.items[0])
            continue
        raise FlowError("nao cheguei no menu — opcoes: %r" % (chat.items,))
    raise FlowError("nao cheguei no menu depois de %d telas" % max_hops)


def format_cpf(cpf):
    """Formata os 11 digitos como o campo atual do Typebot exige."""
    digits = re.sub(r"\D", "", cpf)
    if len(digits) != 11:
        raise ValueError("CPF deve ter 11 digitos")
    return "%s.%s.%s-%s" % (digits[:3], digits[3:6], digits[6:9], digits[9:])


def collect(cpf):
    """Percorre o fluxo e devolve o relatorio em texto."""
    chat = Chat()
    sections = []

    reach_patient(chat)
    chat.pick(r"paciente")

    if chat.input_type != "text input":
        raise FlowError("esperava campo de CPF, veio %r" % (chat.input_type,))
    # Em setembro/2026 o bot passou a rejeitar o CPF sem pontuacao.
    chat.send(format_cpf(cpf))

    reach_menu(chat)
    sections.append(("MENU", "", chat.items))

    # --- flores
    chat.pick(r"flor")

    # O BOT ABECMED 2.1 adicionou uma etapa de composto antes do catalogo.
    # So depois de escolher THC as strains disponiveis sao exibidas.
    if any(re.search(r"\bTHC\b", i, re.I) for i in chat.items):
        chat.pick(r"\bTHC\b")

    sections.append(("FLORES", chat.text, chat.items))
    chat.pick(r"voltar|in[íi]cio", required=False)

    # --- concentrados
    if any(re.search(r"concentrad", i, re.I) for i in chat.items):
        chat.pick(r"concentrad")
        sections.append(("CONCENTRADOS", chat.text, chat.items))

        # o oleo costuma estar pendurado nesse ramo
        if chat.pick(r"[óo]leo", required=False):
            sections.append(("OLEO", chat.text, chat.items))

    return render(sections)


def render(sections):
    out = []
    for title, text, options in sections:
        out.append("== %s ==" % title)
        if text:
            out.append(text)
        if options:
            out.append("opcoes: " + " | ".join(options))
        out.append("")
    return tidy("\n".join(out))


# --------------------------------------------------------------- estado


def load_config(path):
    """Le config.ini. Ausente ou malformado nao e erro: caimos no ambiente."""
    parser = configparser.ConfigParser()
    try:
        parser.read(path, encoding="utf-8")
    except (OSError, configparser.Error):
        return {}
    if not parser.has_section("abecmed"):
        return {}
    return {k: v.strip() for k, v in parser["abecmed"].items()}


def load_state(path):
    try:
        with open(path, encoding="utf-8") as fh:
            state = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise FlowError("nao foi possivel ler o estado; arquivo preservado") from exc
    if (
        not isinstance(state, dict)
        or not isinstance(state.get("report", ""), str)
        or not isinstance(state.get("failure_notified", False), bool)
    ):
        raise FlowError("estado invalido; arquivo preservado")
    return state


def save_state(path, state):
    """Substitui o JSON atomicamente; uma escrita incompleta nao apaga o anterior."""
    updated = dict(state, updated_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(path)),
            prefix=".estado-", suffix=".tmp", delete=False,
        ) as fh:
            temporary = fh.name
            json.dump(updated, fh, ensure_ascii=False, indent=1)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise FlowError("nao foi possivel salvar o estado") from exc
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def section_options(report, title):
    """Extrai as opcoes de uma secao renderizada do relatorio."""
    header = "== %s ==" % title
    inside = False
    for line in report.splitlines():
        if line.startswith("== "):
            inside = line == header
            continue
        if inside and line.startswith("opcoes: "):
            return [item.strip() for item in line[8:].split(" | ") if item.strip()]
    return []


def normalize_flower_order(report):
    """Normaliza somente a ordem das opcoes da secao FLORES."""
    header = "== FLORES =="
    inside = False
    lines = []
    for line in report.splitlines():
        if line.startswith("== "):
            inside = line == header
        if inside and line.startswith("opcoes: "):
            items = [item.strip() for item in line[8:].split(" | ") if item.strip()]
            line = "opcoes: " + " | ".join(sorted(items))
        lines.append(line)
    return "\n".join(lines)


def only_flower_order_changed(old, new):
    """Indica que o relatorio mudou apenas porque as flores foram reordenadas."""
    old_items = section_options(old, "FLORES")
    new_items = section_options(new, "FLORES")
    if not old_items or not new_items:
        return False
    return normalize_flower_order(old) == normalize_flower_order(new)


def catalog_changes(old, new):
    """Devolve produtos que entraram e sairam, preservando a ordem do catalogo."""
    old_items = section_options(old, "FLORES")
    new_items = section_options(new, "FLORES")
    old_set = set(old_items)
    new_set = set(new_items)
    added = [item for item in new_items if item not in old_set]
    removed = [item for item in old_items if item not in new_set]
    return added, removed


def change_highlight(old, new):
    """Tres grupos sem duplicatas, relativos somente a ultima mudanca."""
    added, removed = catalog_changes(old, new)
    added_set = set(added)
    kept = [item for item in section_options(new, "FLORES") if item not in added_set]
    lines = []
    for title, items in (
        ("Novidades:", added),
        ("Em estoque:", kept),
        ("Sem estoque:", removed),
    ):
        if lines:
            lines.append("")
        lines.append(title)
        lines.extend("- %s" % item for item in dict.fromkeys(items))
        if not items:
            lines.append("- Nenhuma.")
    return "\n".join(lines)


def current_catalog_message(report):
    """Monta uma mensagem com o estoque atual, sem alterar o estado salvo."""
    items = section_options(report, "FLORES")
    if not items:
        raise FlowError("o catalogo atual nao trouxe nenhuma strain")
    return "\n".join(
        ["Estoque atual de strains:", ""]
        + ["- %s" % item for item in dict.fromkeys(items)]
    )


# ------------------------------------------------------------ notificacao


def message_parts(message, limit=MAX_MSG):
    """Divide por linhas e, se necessario, caracteres; nunca corta bytes UTF-8."""
    if limit < 4:
        raise ValueError("o limite deve comportar qualquer caractere UTF-8")
    if not message.strip():
        raise FlowError("notificacao vazia")
    parts = []
    current = []
    size = 0
    for line in message.splitlines(keepends=True):
        line_size = len(line.encode("utf-8"))
        if current and size + line_size > limit:
            parts.append("".join(current))
            current, size = [], 0
        if line_size <= limit:
            current.append(line)
            size += line_size
            continue
        for char in line:
            char_size = len(char.encode("utf-8"))
            if size + char_size > limit:
                parts.append("".join(current))
                current, size = [], 0
            current.append(char)
            size += char_size
    if current:
        parts.append("".join(current))
    return parts


def notify(topic, title, message, tags):
    """Publica texto simples e confirma o aceite de cada parte pelo servidor."""
    # Uma quebra de linha isolada no limite nao deve virar um aviso vazio.
    parts = [part for part in message_parts(message) if part.strip()]
    ids = []
    for number, part in enumerate(parts, 1):
        part_title = title if len(parts) == 1 else "%s (%d/%d)" % (title, number, len(parts))
        response = post_json(
            NTFY_BASE,
            {"topic": topic, "title": part_title, "message": part, "tags": tags},
            headers={
                "User-Agent": "abecmed-watch",
                "Origin": None,
                "Referer": None,
                "Sec-Fetch-Dest": None,
                "Sec-Fetch-Mode": None,
                "Sec-Fetch-Site": None,
            },
        )
        if (
            not isinstance(response, dict)
            or response.get("event") != "message"
            or response.get("topic") != topic
            or not isinstance(response.get("id"), str)
            or not response["id"]
        ):
            raise FlowError("ntfy nao confirmou o aceite da parte %d/%d" % (number, len(parts)))
        ids.append(response["id"])
        # Nao registra o topico nem o CPF. Aceite nao comprova entrega no celular.
        print("ntfy: parte %d/%d aceita; id=%r" % (number, len(parts), response["id"]))
    return ids


# ------------------------------------------------------------------ main


def ciclo(cpf, topic, state_path):
    """Um ciclo completo. True indica falha; o controle de avisos fica no JSON."""
    state = load_state(state_path)
    previous = state.get("report", "")
    try:
        report = collect(cpf)
        # Uma tela incompleta nao pode virar uma falsa remocao de todo o estoque.
        current_catalog_message(report)
    except FlowError as exc:
        print("FALHA: %s" % exc, file=sys.stderr)
        if topic and not state.get("failure_notified", False):
            notify(
                topic,
                "abecmed-watch quebrou",
                "Nao foi possivel consultar o catalogo. Pode ser uma falha temporaria "
                "ou uma mudanca no fluxo.\n\n%s" % exc,
                ["warning"],
            )
            state["failure_notified"] = True
            save_state(state_path, state)
        return True

    if state.get("failure_notified", False):
        print("voltou a funcionar")
        if topic:
            notify(topic, "abecmed-watch voltou", "Navegacao normalizada.", ["white_check_mark"])
        state["failure_notified"] = False
        save_state(state_path, state)

    if report == previous:
        print("%s  sem mudancas" % time.strftime("%H:%M"))
        return False

    if previous and only_flower_order_changed(previous, report):
        # O Typebot pode devolver os mesmos produtos em outra ordem. Atualizamos o
        # estado para acompanhar a ordem atual, mas isso nao e uma novidade real.
        state["report"] = report
        save_state(state_path, state)
        print("%s  sem mudancas (somente ordem das strains)" % time.strftime("%H:%M"))
        return False

    if not previous:
        title = "abecmed-watch ativo"
        body = "Primeira execucao, sem comparacao anterior.\n\n" + current_catalog_message(report)
        tags = ["seedling"]
    else:
        body = change_highlight(previous, report)
        if not any(catalog_changes(previous, report)):
            body = (
                "Mudou o texto ou outra secao do catalogo; as strains de flores continuam iguais.\n\n"
                + body
            )
        title = "ABECMED mudou"
        tags = ["bell"]

    notify(topic, title, body, tags)
    state["report"] = report
    save_state(state_path, state)
    print("%s  mudanca detectada, notificacao aceita pelo ntfy" % time.strftime("%H:%M"))
    return False


def main():
    parser = argparse.ArgumentParser(description="Monitor do catalogo da ABECMED")
    parser.add_argument(
        "--config", default=os.path.join(HERE, "config.ini"), help="arquivo de configuracao"
    )
    parser.add_argument(
        "--state", default=os.path.join(HERE, "estado.json"), help="arquivo de estado"
    )
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument(
        "--dry-run", action="store_true", help="imprime o relatorio, nao notifica nem salva"
    )
    modes.add_argument(
        "--notify-current",
        action="store_true",
        help="envia o estoque atual ao ntfy sem alterar o estado salvo",
    )
    modes.add_argument(
        "--loop",
        action="store_true",
        help="fica rodando, com intervalo sorteado entre cada verificacao",
    )
    args = parser.parse_args()

    # Ambiente ganha do arquivo: e assim que o GitHub Actions injeta os secrets.
    config = load_config(args.config)
    cpf = re.sub(r"\D", "", os.environ.get("ABECMED_CPF") or config.get("cpf", ""))
    topic = (os.environ.get("NTFY_TOPIC") or config.get("topico", "")).strip()

    def minutos(chave, padrao):
        try:
            return max(1, int(config.get(chave, padrao)))
        except (TypeError, ValueError):
            return padrao

    lo = minutos("intervalo_min", INTERVALO_MIN)
    hi = minutos("intervalo_max", INTERVALO_MAX)
    if hi < lo:
        lo, hi = hi, lo

    if not cpf:
        sys.exit(
            "erro: CPF nao configurado.\n"
            "  Rode ./configurar.sh (Linux/macOS) ou configurar.bat (Windows)."
        )
    if len(cpf) != 11:
        sys.exit("erro: CPF tem %d digitos, esperava 11. Rode o configurar de novo." % len(cpf))
    if not topic and not args.dry_run:
        sys.exit(
            "erro: topico do ntfy nao configurado.\n"
            "  Rode ./configurar.sh (Linux/macOS) ou configurar.bat (Windows),\n"
            "  ou use --dry-run para so testar sem notificar."
        )

    if args.dry_run:
        try:
            print(collect(cpf))
        except FlowError as exc:
            sys.exit("FALHA: %s" % exc)
        return

    if args.notify_current:
        try:
            report = collect(cpf)
            body = current_catalog_message(report)
            notify(topic, "Estoque atual ABECMED", body, ["herb"])
        except FlowError as exc:
            sys.exit("FALHA: %s" % exc)
        print("%s  estoque atual aceito pelo ntfy" % time.strftime("%H:%M"))
        return

    def check_once():
        try:
            return ciclo(cpf, topic, args.state)
        except FlowError as exc:
            print("FALHA: %s" % exc, file=sys.stderr)
            return True

    if not args.loop:
        quebrou = check_once()
        sys.exit(1 if quebrou else 0)

    print("Monitorando. Intervalo sorteado entre %d e %d minutos." % (lo, hi))
    print("Para parar, aperte Ctrl+C.\n")
    try:
        while True:
            check_once()
            espera = random.uniform(lo * 60, hi * 60)
            print("   proxima verificacao em %d min %02d s" % divmod(int(espera), 60)[0:2])
            time.sleep(espera)
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == "__main__":
    main()
