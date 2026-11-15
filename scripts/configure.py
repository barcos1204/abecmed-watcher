"""Configurador local do watcher. Nao consulta a associacao, GitHub ou ntfy."""

import configparser
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile


CONFIG = Path(__file__).resolve().parents[1] / "config.ini"


def ask_cpf(previous):
    hint = ", Enter mantém o atual" if previous else ""
    while True:
        answer = input(f"CPF do associado (11 dígitos{hint}): ").strip()
        value = answer or previous
        digits = re.sub(r"[.\s-]", "", value)
        if re.fullmatch(r"[0-9]{11}", digits):
            return digits if answer else previous
        print("Use os 11 dígitos do CPF, com ou sem pontuação.")


def ask_topic(previous):
    hint = "Enter mantém o atual; :novo sorteia outro" if previous else "Enter sorteia um canal"
    while True:
        answer = input(f"Tópico do ntfy ({hint}): ").strip()
        if not answer and previous:
            return previous
        if not answer or answer == ":novo":
            return "abecmed-" + secrets.token_hex(16)
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", answer):
            return answer
        print("Use de 1 a 64 letras sem acento, números, hífens ou sublinhados.")


def save_config(path, config):
    # mkstemp cria um arquivo privado no POSIX. Só troca o anterior após a escrita.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".abecmed-config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            config.write(output)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def configure(path):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with path.open(encoding="utf-8-sig") as existing:
            config.read_file(existing)
    except FileNotFoundError:
        pass
    if not config.has_section("abecmed"):
        config.add_section("abecmed")
    section = config["abecmed"]
    old_cpf, old_topic = section.get("cpf", ""), section.get("topico", "")
    cpf, topic = ask_cpf(old_cpf), ask_topic(old_topic)

    if (cpf, topic) == (old_cpf, old_topic):
        print("Configuração mantida; seu tópico não mudou.")
        return
    section["cpf"], section["topico"] = cpf, topic
    section.setdefault("intervalo_min", "7")
    section.setdefault("intervalo_max", "12")
    save_config(path, config)
    print("Configuração local salva. Não compartilhe o config.ini.")
    if topic != old_topic:
        print("No ntfy, toque em + e assine este tópico:", topic)
    else:
        print("Seu tópico não mudou.")


def main(path):
    try:
        configure(path)
    except (EOFError, KeyboardInterrupt):
        print("\nConfiguração cancelada.", file=sys.stderr)
        return 1
    except (OSError, UnicodeError, configparser.Error, NotImplementedError):
        # Uma mensagem de erro do parser pode conter o próprio CPF ou tópico.
        print("Não foi possível configurar. Confira o arquivo, as permissões e o gerador seguro.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    result = main(CONFIG)
    if os.name == "nt" and sys.stdin.isatty():  # Manter a janela do duplo clique visível.
        try:
            input("Pressione Enter para fechar.")
        except (EOFError, KeyboardInterrupt):
            pass
    sys.exit(result)
