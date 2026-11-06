"""Testes offline: o CPF de zeros e o topico test-topic sao dados ficticios."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import bot


def report(*items, text="Produtos disponíveis"):
    return bot.render([
        ("MENU", "", ["Óleos", "Flores"]),
        ("FLORES", text, list(items)),
    ])


class OfflineTest(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch(
            "bot.urllib.request.urlopen", side_effect=AssertionError("Rede proibida nos testes")
        ))
        self.stdout = self.enterContext(contextlib.redirect_stdout(io.StringIO()))
        self.enterContext(contextlib.redirect_stderr(io.StringIO()))


class CatalogTests(OfflineTest):
    def test_three_disjoint_plain_text_groups(self):
        message = bot.change_highlight(report("Mantida", "Saiu"), report("Nova", "Mantida"))
        self.assertEqual(message, (
            "Novidades:\n- Nova\n\nEm estoque:\n- Mantida\n\nSem estoque:\n- Saiu"
        ))
        self.assertNotIn("**", message)
        self.assertNotIn("\u0336", message)

    def test_only_additions(self):
        self.assertEqual(bot.change_highlight(report("A"), report("A", "B")), (
            "Novidades:\n- B\n\nEm estoque:\n- A\n\nSem estoque:\n- Nenhuma."
        ))

    def test_only_removals(self):
        self.assertEqual(bot.change_highlight(report("A", "B"), report("A")), (
            "Novidades:\n- Nenhuma.\n\nEm estoque:\n- A\n\nSem estoque:\n- B"
        ))

    def test_removals_are_not_accumulated(self):
        first, second, third = report("A", "B"), report("B", "C"), report("C", "D")
        self.assertIn("Sem estoque:\n- A", bot.change_highlight(first, second))
        self.assertIn("Sem estoque:\n- B", bot.change_highlight(second, third))
        self.assertNotIn("- A", bot.change_highlight(second, third))

    def test_duplicate_options_appear_once(self):
        message = bot.change_highlight(report("A", "B", "B"), report("A", "A", "C", "C"))
        for item in ("A", "B", "C"):
            self.assertEqual(message.count("- " + item), 1)

    def test_price_change_keeps_literal_labels(self):
        old, new = "[R$ 50] — A", "[R$ 55] — A"
        self.assertEqual(bot.catalog_changes(report(old), report(new)), ([new], [old]))

    def test_reordering_is_not_a_catalog_change(self):
        old, new = report("A", "B"), report("B", "A")
        self.assertTrue(bot.only_flower_order_changed(old, new))
        self.assertEqual(bot.catalog_changes(old, new), ([], []))

    def test_text_change_is_not_mistaken_for_reordering(self):
        self.assertFalse(bot.only_flower_order_changed(report("A"), report("A", text="Novo aviso")))

    def test_section_options_do_not_include_other_sections(self):
        text = report("A") + "\n== OLEO ==\nopcoes: B | C"
        self.assertEqual(bot.section_options(text, "FLORES"), ["A"])

    def test_current_stock_does_not_claim_any_change(self):
        self.assertEqual(bot.current_catalog_message(report("A", "B")), (
            "Estoque atual de strains:\n\n- A\n- B"
        ))

    def test_empty_current_stock_is_not_treated_as_confirmed(self):
        with self.assertRaises(bot.FlowError):
            bot.current_catalog_message(report())


class NotificationTests(OfflineTest):
    def test_utf8_messages_preserve_all_lines_and_fit_byte_limit(self):
        message = "Novidades:\n" + "- 🌿 Açúcar — [R$ 85]\n" * 250
        parts = bot.message_parts(message)
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), message)
        self.assertTrue(all(len(part.encode("utf-8")) <= bot.MAX_MSG for part in parts))
        self.assertTrue(all(part.endswith("\n") for part in parts))

    def test_single_long_line_preserves_unicode(self):
        message = "🌿á漢" * 1000
        parts = bot.message_parts(message, limit=37)
        self.assertEqual("".join(parts), message)
        self.assertTrue(all(0 < len(part.encode("utf-8")) <= 37 for part in parts))

    def test_exact_byte_boundary(self):
        self.assertEqual(bot.message_parts("á" * 5, limit=10), ["á" * 5])

    def test_empty_message_rejected(self):
        with self.assertRaises(bot.FlowError):
            bot.message_parts("\n  ")

    def test_too_small_byte_limit_rejected(self):
        with self.assertRaises(ValueError):
            bot.message_parts("A", limit=3)

    def test_plain_text_publish_and_acceptance_id(self):
        with mock.patch("bot.post_json", return_value={
            "id": "fake-id", "event": "message", "topic": "test-topic",
        }) as post:
            self.assertEqual(bot.notify("test-topic", "Titulo", "Mensagem", ["bell"]), ["fake-id"])
        self.assertEqual(post.call_args.args[1], {
            "topic": "test-topic", "title": "Titulo", "message": "Mensagem", "tags": ["bell"],
        })
        self.assertIsNone(post.call_args.kwargs["headers"]["Origin"])
        self.assertIn("fake-id", self.stdout.getvalue())
        self.assertNotIn("test-topic", self.stdout.getvalue())

    def test_invalid_acceptance_is_not_success(self):
        for response in (None, [], {}, {"id": "x"},
                         {"id": 123, "event": "message", "topic": "test-topic"},
                         {"id": "x", "event": "open", "topic": "test-topic"},
                         {"id": "x", "event": "message", "topic": "wrong"},
                         {"id": "", "event": "message", "topic": "test-topic"}):
            with self.subTest(response=response), mock.patch("bot.post_json", return_value=response):
                with self.assertRaises(bot.FlowError):
                    bot.notify("test-topic", "Titulo", "Mensagem", [])

    def test_multipart_titles_are_numbered(self):
        message = "- 🌿 Açúcar\n" * 500
        with mock.patch("bot.post_json", return_value={
            "id": "fake-id", "event": "message", "topic": "test-topic",
        }) as post:
            ids = bot.notify("test-topic", "Titulo", message, [])
        self.assertGreater(len(ids), 1)
        payloads = [call.args[1] for call in post.call_args_list]
        self.assertEqual("".join(payload["message"] for payload in payloads), message)
        for number, payload in enumerate(payloads, 1):
            self.assertEqual(payload["title"], "Titulo (%d/%d)" % (number, len(payloads)))

    def test_isolated_trailing_newline_is_not_published(self):
        with mock.patch("bot.post_json", return_value={
            "id": "fake-id", "event": "message", "topic": "test-topic",
        }) as post:
            bot.notify("test-topic", "Titulo", "x" * bot.MAX_MSG + "\n", [])
        post.assert_called_once()
        self.assertEqual(post.call_args.args[1]["message"], "x" * bot.MAX_MSG)

    def test_partial_multipart_failure_does_not_advance_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "estado.json"
            bot.save_state(state_path, {"report": report("Antiga")})
            original = state_path.read_bytes()
            large_report = report(*("Strain %d — 🌿" % number for number in range(500)))
            with mock.patch("bot.collect", return_value=large_report), mock.patch("bot.post_json", side_effect=[
                {"id": "first-part", "event": "message", "topic": "test-topic"},
                bot.FlowError("falha na segunda parte"),
            ]) as post:
                with self.assertRaises(bot.FlowError):
                    bot.ciclo("00000000000", "test-topic", state_path)
            self.assertEqual(post.call_count, 2)
            self.assertEqual(state_path.read_bytes(), original)


class NavigationTests(OfflineTest):
    @staticmethod
    def buttons(*items):
        return {"input": {"type": "choice input", "items": [{"content": item} for item in items]}}

    def test_consent_patient_cpf_menu_thc_catalog(self):
        start = dict(self.buttons("Estou ciente"), sessionId="test-session")
        responses = [
            start, self.buttons("Sou paciente", "Outros"), {"input": {"type": "text input"}},
            self.buttons("Óleos", "Flores"), self.buttons("THC", "CBD"),
            self.buttons("[R$ 85] — Strain A", "[R$ 50] — Strain B"),
        ]
        with mock.patch("bot.discover_typebot", return_value="test-bot"), \
             mock.patch("bot.post_json", side_effect=responses) as post:
            result = bot.collect("00000000000")
        selections = [call.args[1]["message"]["text"] for call in post.call_args_list[1:]]
        self.assertEqual(selections, ["Estou ciente", "Sou paciente", "000.000.000-00", "Flores", "THC"])
        self.assertEqual(bot.section_options(result, "FLORES"), [
            "[R$ 85] — Strain A", "[R$ 50] — Strain B",
        ])

    def test_direct_catalog_without_thc_step(self):
        responses = [
            dict(self.buttons("Sou paciente"), sessionId="test-session"),
            {"input": {"type": "text input"}}, self.buttons("Flores"),
            self.buttons("Strain A"),
        ]
        with mock.patch("bot.discover_typebot", return_value="test-bot"), \
             mock.patch("bot.post_json", side_effect=responses):
            result = bot.collect("00000000000")
        self.assertEqual(bot.section_options(result, "FLORES"), ["Strain A"])


class StateFixture(OfflineTest):
    def setUp(self):
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.state_path = self.directory / "estado.json"


class StateTests(StateFixture):
    def test_missing_state(self):
        self.assertEqual(bot.load_state(self.state_path), {})

    def test_atomic_save_round_trip_and_legacy_compatibility(self):
        original = {"report": report("A"), "custom": "preservar"}
        bot.save_state(self.state_path, original)
        state = bot.load_state(self.state_path)
        self.assertEqual(state["report"], original["report"])
        self.assertEqual(state["custom"], "preservar")
        self.assertIn("updated_at", state)
        self.assertNotIn("updated_at", original)

    def test_malformed_state_is_preserved(self):
        self.state_path.write_text("{incompleto", encoding="utf-8")
        with self.assertRaises(bot.FlowError):
            bot.load_state(self.state_path)
        self.assertEqual(self.state_path.read_text(encoding="utf-8"), "{incompleto")

    def test_wrong_state_types_rejected(self):
        for state in ([], None, {"report": []}, {"failure_notified": "false"}):
            with self.subTest(state=state):
                self.state_path.write_text(json.dumps(state), encoding="utf-8")
                with self.assertRaises(bot.FlowError):
                    bot.load_state(self.state_path)

    def test_failed_atomic_replace_keeps_previous_file(self):
        bot.save_state(self.state_path, {"report": report("A")})
        original = self.state_path.read_bytes()
        with mock.patch("bot.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(bot.FlowError):
                bot.save_state(self.state_path, {"report": report("B")})
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(list(self.directory.glob(".estado-*.tmp")), [])


class CycleTests(StateFixture):
    def setUp(self):
        super().setUp()
        self.old = report("A", "B")
        bot.save_state(self.state_path, {"report": self.old})
        self.collect = self.enterContext(mock.patch("bot.collect", return_value=self.old))
        self.notify = self.enterContext(mock.patch("bot.notify"))

    def cycle(self):
        return bot.ciclo("00000000000", "test-topic", self.state_path)

    def test_unchanged_has_no_notification_or_write(self):
        original = self.state_path.read_bytes()
        with mock.patch("bot.save_state", wraps=bot.save_state) as save:
            self.assertFalse(self.cycle())
        save.assert_not_called()
        self.notify.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_reordering_updates_snapshot_without_notification(self):
        self.collect.return_value = report("B", "A")
        self.assertFalse(self.cycle())
        self.notify.assert_not_called()
        self.assertEqual(bot.load_state(self.state_path)["report"], report("B", "A"))

    def test_stock_change_saved_after_notification(self):
        self.collect.return_value = report("B", "C")

        def accepted(*args):
            self.assertEqual(bot.load_state(self.state_path)["report"], self.old)

        self.notify.side_effect = accepted
        self.assertFalse(self.cycle())
        self.assertEqual(self.notify.call_args.args[2], bot.change_highlight(self.old, report("B", "C")))
        self.assertEqual(bot.load_state(self.state_path)["report"], report("B", "C"))

    def test_failed_notification_does_not_advance_state(self):
        original = self.state_path.read_bytes()
        self.collect.return_value = report("B", "C")
        self.notify.side_effect = bot.FlowError("ntfy indisponivel")
        with self.assertRaises(bot.FlowError):
            self.cycle()
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_initial_message_is_a_snapshot_not_a_claim_of_new_stock(self):
        self.state_path.unlink()
        self.assertFalse(self.cycle())
        body = self.notify.call_args.args[2]
        self.assertIn("sem comparacao anterior", body)
        self.assertNotIn("Novidades:", body)
        self.assertNotIn("== MENU ==", body)

    def test_text_only_change_keeps_flow_text_out_of_stock_list(self):
        self.collect.return_value = report("A", "B", text="Novo aviso")
        self.assertFalse(self.cycle())
        body = self.notify.call_args.args[2]
        self.assertIn("strains de flores continuam iguais", body)
        self.assertIn("Em estoque:\n- A\n- B", body)
        self.assertNotIn("opcoes:", body)

    def test_failure_alert_is_persisted_across_independent_cycles(self):
        self.collect.side_effect = bot.FlowError("fluxo alterado")
        self.assertTrue(self.cycle())
        self.assertTrue(self.cycle())
        self.notify.assert_called_once()
        state = bot.load_state(self.state_path)
        self.assertTrue(state["failure_notified"])
        self.assertEqual(state["report"], self.old)

    def test_failed_failure_alert_can_be_retried(self):
        self.collect.side_effect = bot.FlowError("fluxo alterado")
        self.notify.side_effect = bot.FlowError("ntfy indisponivel")
        with self.assertRaises(bot.FlowError):
            self.cycle()
        self.assertFalse(bot.load_state(self.state_path).get("failure_notified", False))
        self.notify.side_effect = None
        self.assertTrue(self.cycle())
        self.assertEqual(self.notify.call_count, 2)

    def test_first_run_failure_does_not_create_fake_catalog(self):
        self.state_path.unlink()
        self.collect.side_effect = bot.FlowError("fluxo alterado")
        self.assertTrue(self.cycle())
        self.assertNotIn("report", bot.load_state(self.state_path))
        self.assertTrue(bot.load_state(self.state_path)["failure_notified"])

    def test_incomplete_catalog_is_failure_not_mass_removal(self):
        self.collect.return_value = report()
        self.assertTrue(self.cycle())
        self.assertEqual(self.notify.call_args.args[1], "abecmed-watch quebrou")
        self.assertEqual(bot.load_state(self.state_path)["report"], self.old)

    def test_recovery_is_notified_once_and_resets_failure_marker(self):
        bot.save_state(self.state_path, {"report": self.old, "failure_notified": True})
        self.assertFalse(self.cycle())
        self.assertFalse(self.cycle())
        self.notify.assert_called_once()
        self.assertEqual(self.notify.call_args.args[1], "abecmed-watch voltou")
        self.assertFalse(bot.load_state(self.state_path)["failure_notified"])
        self.collect.side_effect = bot.FlowError("nova falha")
        self.assertTrue(self.cycle())
        self.assertEqual(self.notify.call_count, 2)

    def test_recovery_publish_failure_keeps_marker(self):
        bot.save_state(self.state_path, {"report": self.old, "failure_notified": True})
        self.notify.side_effect = bot.FlowError("ntfy indisponivel")
        with self.assertRaises(bot.FlowError):
            self.cycle()
        self.assertTrue(bot.load_state(self.state_path)["failure_notified"])

    def test_manual_snapshot_does_not_change_baseline(self):
        original = self.state_path.read_bytes()
        self.collect.return_value = report("Nova")
        with mock.patch.dict("os.environ", {"ABECMED_CPF": "00000000000", "NTFY_TOPIC": "test-topic"}), \
             mock.patch("sys.argv", ["bot.py", "--notify-current", "--state", str(self.state_path)]):
            bot.main()
        self.assertEqual(self.state_path.read_bytes(), original)
        self.assertEqual(self.notify.call_args.args[2], "Estoque atual de strains:\n\n- Nova")

    def test_dry_run_has_no_notification_or_write(self):
        original = self.state_path.read_bytes()
        with mock.patch.dict("os.environ", {"ABECMED_CPF": "00000000000"}), \
             mock.patch("sys.argv", ["bot.py", "--dry-run", "--state", str(self.state_path)]):
            bot.main()
        self.notify.assert_not_called()
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_conflicting_cli_modes_rejected(self):
        with mock.patch("sys.argv", ["bot.py", "--dry-run", "--notify-current"]):
            with self.assertRaises(SystemExit) as raised:
                bot.main()
        self.assertEqual(raised.exception.code, 2)
        self.collect.assert_not_called()

    def test_invalid_state_stops_before_collection_or_notification(self):
        self.state_path.write_text("{incompleto", encoding="utf-8")
        with self.assertRaises(bot.FlowError):
            self.cycle()
        self.collect.assert_not_called()
        self.notify.assert_not_called()

    def test_recovery_and_new_stock_both_notified(self):
        bot.save_state(self.state_path, {"report": self.old, "failure_notified": True})
        self.collect.return_value = report("B", "C")
        self.assertFalse(self.cycle())
        self.assertEqual(self.notify.call_count, 2)
        self.assertEqual(self.notify.call_args_list[0].args[1], "abecmed-watch voltou")
        self.assertIn("Novidades:\n- C", self.notify.call_args_list[1].args[2])
        self.assertEqual(bot.load_state(self.state_path)["report"], report("B", "C"))

    def test_notification_failure_exits_with_error(self):
        self.collect.return_value = report("B", "C")
        self.notify.side_effect = bot.FlowError("ntfy indisponivel")
        with mock.patch.dict("os.environ", {"ABECMED_CPF": "00000000000", "NTFY_TOPIC": "test-topic"}), \
             mock.patch("sys.argv", ["bot.py", "--state", str(self.state_path)]):
            with self.assertRaises(SystemExit) as raised:
                bot.main()
        self.assertEqual(raised.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
