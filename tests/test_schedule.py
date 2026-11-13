"""Cadencia com dados sinteticos; nenhuma chamada real ao GitHub."""

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
from unittest import mock

from scripts import check_schedule as schedule


def run(run_id, created, **overrides):
    data = {
        "id": run_id, "created_at": created, "event": "schedule", "head_branch": "main",
        "path": ".github/workflows/check.yml", "conclusion": "success",
    }
    data.update(overrides)
    return data


class ScheduleTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {}, clear=True))
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(mock.patch(
            "scripts.check_schedule.urllib.request.urlopen",
            side_effect=AssertionError("Rede proibida nos testes"),
        ))
        self.current = run(20, "2026-11-12T18:30:00Z")
        self.previous = run(19, "2026-11-12T18:20:00Z")

    def test_expected_interval_has_no_warning(self):
        message, warning = schedule.analyze(self.current, [self.current, self.previous])
        self.assertFalse(warning)
        self.assertIn("10.0 min", message)
        self.assertIn("nao comprova coleta ou entrega", message)

    def test_eight_hour_gap_has_warning(self):
        message, warning = schedule.analyze(self.current, [run(19, "2026-11-12T10:30:00Z")])
        self.assertTrue(warning)
        self.assertIn("480.0 min", message)
        self.assertIn("nao alerta durante uma parada total", message)

    def test_exact_warning_boundary_is_within_tolerance(self):
        _, warning = schedule.analyze(self.current, [run(19, "2026-11-12T18:00:00Z")])
        self.assertFalse(warning)

    def test_selects_latest_previous_run_even_if_history_unsorted(self):
        message, warning = schedule.analyze(self.current, [
            run(17, "2026-11-12T14:00:00Z"), self.previous, run(18, "2026-11-12T16:00:00Z"),
        ])
        self.assertFalse(warning)
        self.assertIn("run 19", message)

    def test_manual_other_branches_and_other_workflows_do_not_hide_gap(self):
        history = [
            run(10, "2026-11-12T17:00:00Z"),
            run(11, "2026-11-12T18:10:00Z", event="workflow_dispatch"),
            run(12, "2026-11-12T18:20:00Z", head_branch="feature"),
            run(13, "2026-11-12T18:25:00Z", path=".github/workflows/tests.yml"),
        ]
        message, warning = schedule.analyze(self.current, history)
        self.assertTrue(warning)
        self.assertIn("90.0 min", message)

    def test_future_runs_and_current_run_are_not_previous(self):
        message, _ = schedule.analyze(self.current, [
            self.current, run(21, "2026-11-12T18:40:00Z"), self.previous,
        ])
        self.assertIn("10.0 min", message)

    def test_rerun_uses_creation_not_attempt_time(self):
        current = dict(self.current, run_started_at="2026-11-13T08:00:00Z", run_attempt=2)
        message, warning = schedule.analyze(current, [self.previous])
        self.assertFalse(warning)
        self.assertIn("10.0 min", message)

    def test_no_previous_run_is_unknown_not_healthy(self):
        message, warning = schedule.analyze(self.current, [])
        self.assertFalse(warning)
        self.assertIn("Cadencia nao determinada", message)
        self.assertNotIn("dentro da tolerancia", message)

    def test_manual_run_does_not_measure_cron_cadence(self):
        message, warning = schedule.analyze(dict(self.current, event="workflow_dispatch"), [])
        self.assertFalse(warning)
        self.assertIn("Execucao manual", message)

    def test_timezone_required(self):
        with self.assertRaises(ValueError):
            schedule.timestamp("2026-11-12T18:20:00")

    def test_api_request_is_get_with_timeout(self):
        response = mock.MagicMock()
        response.__enter__.return_value = io.BytesIO(json.dumps(self.current).encode())
        with mock.patch("scripts.check_schedule.urllib.request.urlopen", return_value=response) as opener:
            result = schedule.get_json("/repos/example/watcher/actions/runs/20", "fictional-test-token")
        self.assertEqual(result, self.current)
        request = opener.call_args.args[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.get_header("Authorization"), "Bearer fictional-test-token")
        self.assertEqual(opener.call_args.kwargs["timeout"], 10)

    def test_missing_context_does_not_call_api(self):
        with mock.patch.object(schedule, "get_json") as api:
            schedule.main()
        api.assert_not_called()
        self.assertIn("indisponivel", self.stdout.getvalue())

    def test_main_writes_summary_and_only_reads_api(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = Path(directory) / "summary.md"
            with mock.patch.dict(os.environ, {
                "GITHUB_REPOSITORY": "example/watcher", "GITHUB_RUN_ID": "20",
                "GITHUB_STEP_SUMMARY": str(summary),
            }), mock.patch.object(schedule, "get_json", side_effect=[
                self.current, {"workflow_runs": [self.previous]},
            ]) as api:
                schedule.main()
            self.assertEqual(api.call_count, 2)
            self.assertIn("Cadencia do monitor", summary.read_text(encoding="utf-8"))
            self.assertIn("10.0 min", summary.read_text(encoding="utf-8"))
            self.assertNotIn("::warning::", self.stdout.getvalue())

    def test_api_failure_is_warning_without_secret_or_raw_response(self):
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/watcher", "GITHUB_RUN_ID": "20"}), \
             mock.patch.object(schedule, "get_json", side_effect=urllib.error.HTTPError(
                 "https://api.github.com", 403, "fictional-sensitive-detail", None, None,
             )):
            schedule.main()
        output = self.stdout.getvalue()
        self.assertIn("HTTP 403", output)
        self.assertIn("::warning::", output)
        self.assertNotIn("fictional-sensitive-detail", output)

    def test_invalid_api_data_is_warning_not_monitor_failure(self):
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "example/watcher", "GITHUB_RUN_ID": "20"}), \
             mock.patch.object(schedule, "get_json", side_effect=[self.current, {"workflow_runs": None}]):
            schedule.main()
        self.assertIn("cadencia nao determinada", self.stdout.getvalue())
        self.assertIn("::warning::", self.stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
