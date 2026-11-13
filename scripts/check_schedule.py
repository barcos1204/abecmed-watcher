#!/usr/bin/env python3
"""Diagnostico somente leitura da cadencia. Nao agenda nem dispara consultas."""

from datetime import datetime
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request


API = "https://api.github.com"
WORKFLOW_PATH = ".github/workflows/check.yml"
EXPECTED_MINUTES = 10
WARNING_MINUTES = 30


def get_json(path, token):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "abecmed-watch-cadence"}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(API + path, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("horario sem fuso")
    return parsed


def analyze(current, runs):
    """Compara criacoes de runs, nao usa updated_at do estoque como heartbeat."""
    if current.get("event") != "schedule":
        return "Execucao manual: nao mede a frequencia do cron.", False
    if current.get("path", "").split("@", 1)[0] != WORKFLOW_PATH or current.get("head_branch") != "main":
        raise ValueError("workflow/branch inesperado")
    current_time = timestamp(current["created_at"])
    candidates = []
    for run in runs:
        if (
            run.get("id") == current["id"]
            or run.get("event") != "schedule"
            or run.get("head_branch") != "main"
            or run.get("path", "").split("@", 1)[0] != WORKFLOW_PATH
        ):
            continue
        created = timestamp(run["created_at"])
        if created < current_time:
            candidates.append((created, run))
    if not candidates:
        return (
            "Nao foi localizado um disparo anterior comparavel nas 100 execucoes recentes. "
            "Cadencia nao determinada.", False,
        )
    previous_time, previous = max(candidates, key=lambda item: item[0])
    gap = (current_time - previous_time).total_seconds() / 60
    late = gap > WARNING_MINUTES
    previous_id = int(previous["id"])
    message = (
        "Intervalo entre disparos registrados: %.1f min.\n\n"
        "- Intervalo solicitado: %d min.\n"
        "- Limite de aviso: acima de %d min.\n"
        "- Disparo anterior: %s (run %d).\n"
        "- Disparo atual: %s.\n\n"
    ) % (gap, EXPECTED_MINUTES, WARNING_MINUTES,
         previous_time.isoformat(), previous_id, current_time.isoformat())
    if late:
        message += "ATENCAO: houve uma lacuna de agendamento acima do limite.\n\n"
    else:
        message += "Intervalo dentro da tolerancia neste par de execucoes.\n\n"
    message += (
        "Este diagnostico mede disparos do Actions, nao comprova coleta ou entrega no ntfy. "
        "Ele so roda quando o workflow roda: nao alerta durante uma parada total. "
        "A causa de lacunas nao pode ser determinada apenas por estes horarios."
    )
    return message, late


def publish_diagnostic(message, warning=False):
    print(message)
    if warning:
        print("::warning::Verifique o diagnostico de agendamento no resumo desta execucao.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as output:
            output.write("## Cadencia do monitor\n\n" + message + "\n")


def main():
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or not run_id.isdigit():
        publish_diagnostic("Diagnostico indisponivel: faltam os dados da execucao do Actions.", True)
        return
    token = os.environ.get("GITHUB_TOKEN", "")
    try:
        current = get_json("/repos/%s/actions/runs/%s" % (repository, run_id), token)
        if str(current["id"]) != run_id:
            raise ValueError("execucao diferente da solicitada")
        query = urllib.parse.urlencode({
            "branch": "main", "event": "schedule", "per_page": 100, "exclude_pull_requests": "true",
        })
        history = get_json("/repos/%s/actions/runs?%s" % (repository, query), token)
        runs = history["workflow_runs"]
        if not isinstance(runs, list):
            raise ValueError("historico invalido")
        message, warning = analyze(current, runs)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # Sem resposta bruta, token, CPF ou topico nos logs; nao falha a consulta.
        code = " (HTTP %s)" % exc.code if isinstance(exc, urllib.error.HTTPError) else ""
        message = "Diagnostico de agendamento indisponivel%s; cadencia nao determinada." % code
        warning = True
    publish_diagnostic(message, warning)


if __name__ == "__main__":
    main()
