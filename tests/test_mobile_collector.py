import contextlib
import io
import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

import jamf_mobile_influx as app


def page(*versions, total=None):
    result = {"results": [{"general": {"osVersion": v}} for v in versions]}
    if total is not None:
        result["totalCount"] = total
    return result


class MobileCollectorTests(unittest.TestCase):
    def setUp(self):
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_normalization(self):
        for raw, expected in [
            ("15.4.0", "15.4"),
            ("26.5.0.0", "26.5"),
            ("27.0", "27.0"),
            ("27.0.0", "27.0"),
            ("15.7.9", "15.7.9"),
            (None, "Unknown"),
            ("", "Unknown"),
            (" unknown ", "Unknown"),
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(app.normalize_version(raw), expected)

    @patch.object(app, "JAMF_PAGE_SIZE", 2)
    @patch.object(app, "get_jamf_token", return_value="fake-token")
    def test_pagination_and_token_propagation(self, _):
        with patch.object(
            app,
            "get_inventory_page",
            side_effect=[
                (page("15.4.0", "15.4", total=3), "refreshed"),
                (page(None, total=3), "refreshed"),
            ],
        ) as fetch:
            counts, total = app.collect_os_versions()
        self.assertEqual(counts, {"15.4": 2, "Unknown": 1})
        self.assertEqual(total, 3)
        self.assertEqual(fetch.call_args_list[1].args, ("refreshed", 1))

    @patch.object(app, "JAMF_PAGE_SIZE", 500)
    @patch.object(app, "get_jamf_token", return_value="fake-token")
    def test_server_page_cap_uses_total(self, _):
        with patch.object(
            app,
            "get_inventory_page",
            side_effect=[(page("27.0", total=2), "t"), (page("15.4", total=2), "t")],
        ):
            self.assertEqual(app.collect_os_versions()[1], 2)

    @patch.object(app, "JAMF_PAGE_SIZE", 1)
    @patch.object(app, "get_jamf_token", return_value="fake-token")
    def test_incomplete_inventory_rejected(self, _):
        with patch.object(
            app,
            "get_inventory_page",
            side_effect=[(page("27.0", total=2), "t"), (page(total=2), "t")],
        ):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                app.collect_os_versions()

    @patch.object(app, "JAMF_PAGE_SIZE", 1)
    @patch.object(app, "get_jamf_token", return_value="fake-token")
    def test_changed_total_rejected(self, _):
        with patch.object(
            app,
            "get_inventory_page",
            side_effect=[(page("27.0", total=2), "t"), (page("15.4", total=3), "t")],
        ):
            with self.assertRaisesRegex(RuntimeError, "changed"):
                app.collect_os_versions()

    def test_refresh_once(self):
        expired = MagicMock(status_code=401)
        success = MagicMock(status_code=200, ok=True)
        success.json.return_value = page("27.0")
        with patch.object(app.requests, "get", side_effect=[expired, success]) as get:
            with patch.object(
                app, "get_jamf_token", return_value="new-token"
            ) as refresh:
                result, token = app.get_inventory_page("expired", 0)
        self.assertTrue(get.call_args.args[0].endswith("/pro/v2/mobile-devices/detail"))
        self.assertEqual(get.call_args.kwargs["params"]["section"], "GENERAL")
        self.assertEqual(get.call_args.kwargs["params"]["sort"], "mobileDeviceId:asc")
        self.assertIn("X-Environment-Id", get.call_args.kwargs["headers"])
        refresh.assert_called_once()
        self.assertEqual(get.call_count, 2)
        self.assertEqual(token, "new-token")
        self.assertEqual(result, page("27.0"))

    def test_http_errors_do_not_include_response_body(self):
        failed = MagicMock(status_code=403, ok=False, text="sensitive-body")
        with patch.object(app.requests, "post", return_value=failed):
            with self.assertRaises(RuntimeError) as error:
                app.get_jamf_token()
        self.assertNotIn("sensitive-body", str(error.exception))
        with patch.object(app.requests, "get", return_value=failed):
            with self.assertRaises(RuntimeError) as error:
                app.get_inventory_page("fake", 0)
        self.assertNotIn("sensitive-body", str(error.exception))

    def test_invalid_envelope_rejected(self):
        response = MagicMock(ok=True, status_code=200)
        response.json.return_value = {"unexpected": []}
        with patch.object(app.requests, "get", return_value=response):
            with self.assertRaisesRegex(RuntimeError, "invalid inventory"):
                app.get_inventory_page("fake", 0)

    def test_state_roundtrip_and_corruption(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "known_versions.json"
            with patch.object(app, "STATE_FILE", state):
                self.assertEqual(app.load_known_versions(), set())
                app.save_known_versions({"15.4.0", "15.4", "27.0"})
                self.assertEqual(app.load_known_versions(), {"15.4", "27.0"})
                self.assertFalse(state.with_suffix(".tmp").exists())
                for invalid in ["{", "{}", '{"versions":"15.4"}', '{"versions":[15]}']:
                    state.write_text(invalid)
                    with self.assertRaises(RuntimeError):
                        app.load_known_versions()

    def test_write_has_zero_counts_shared_timestamp_and_summary(self):
        with patch.object(app, "InfluxDBClient") as client:
            timestamp, known = app.write_to_influx(Counter({"27.0": 2}), 2, {"15.4"})
        records = client.return_value.__enter__.return_value.write_api.return_value.write.call_args.kwargs[
            "record"
        ]
        lines = [record.to_line_protocol() for record in records]
        self.assertTrue(all(line.startswith("jamf_mobile_") for line in lines))
        self.assertTrue(all("platform=mobile" in line for line in lines))
        self.assertEqual(len(lines), 3)
        self.assertEqual(len({line.rsplit(" ", 1)[1] for line in lines}), 1)
        self.assertTrue(
            any("version=15.4 " in line and "count=0i" in line for line in lines)
        )
        self.assertIn("total_devices=2i", lines[-1])
        self.assertIn("known_versions=2i", lines[-1])
        self.assertEqual(known, {"15.4", "27.0"})
        self.assertIsNotNone(timestamp.tzinfo)

    @patch.object(app, "validate_environment")
    @patch.object(app, "collect_os_versions", return_value=(Counter({"27.0": 1}), 1))
    def test_dry_run_never_reads_or_writes_state_or_influx(self, *_):
        with (
            patch("sys.argv", ["jamf_mobile_influx.py", "--dry-run"]),
            patch.object(app, "load_known_versions") as load,
            patch.object(app, "save_known_versions") as save,
            patch.object(app, "write_to_influx") as write,
        ):
            app.main()
            load.assert_not_called()
            save.assert_not_called()
            write.assert_not_called()

    @patch.object(app, "validate_environment")
    @patch.object(app, "collect_os_versions", return_value=(Counter({"27.0": 1}), 1))
    @patch.object(app, "load_known_versions", return_value={"15.4"})
    def test_failed_write_preserves_state(self, *_):
        with (
            patch("sys.argv", ["jamf_mobile_influx.py"]),
            patch.object(app, "save_known_versions") as save,
            patch.object(
                app, "write_to_influx", side_effect=RuntimeError("write failed")
            ),
        ):
            with self.assertRaises(RuntimeError):
                app.main()
            save.assert_not_called()

    @patch.object(app, "validate_environment")
    @patch.object(app, "collect_os_versions", return_value=(Counter(), 0))
    def test_empty_fleet_never_writes(self, *_):
        with (
            patch("sys.argv", ["jamf_mobile_influx.py"]),
            patch.object(app, "write_to_influx") as write,
        ):
            with self.assertRaisesRegex(RuntimeError, "zero mobile devices"):
                app.main()
            write.assert_not_called()

    def test_invalid_page_size(self):
        for size in [0, -1, "not-a-number"]:
            with patch.object(app, "JAMF_PAGE_SIZE", size):
                with self.assertRaisesRegex(RuntimeError, "positive integer"):
                    app.validate_environment(dry_run=True)


if __name__ == "__main__":
    unittest.main()
