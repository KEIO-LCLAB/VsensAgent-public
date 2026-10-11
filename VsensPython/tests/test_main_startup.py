import importlib
import sys
import types
import unittest
from unittest.mock import patch


class TestMainStartup(unittest.TestCase):
    def test_should_run_with_gui_when_gui_available(self):
        import main

        with patch.object(main, "_gui_runtime_available", return_value=True):
            self.assertTrue(main._should_run_with_gui())

    def test_should_fallback_to_headless_when_gui_unavailable(self):
        import main

        with patch.object(main, "_gui_runtime_available", return_value=False):
            self.assertFalse(main._should_run_with_gui())

    def test_gui_runtime_check_handles_import_failure(self):
        import main

        original = sys.modules.get("monitor_gui")
        sys.modules.pop("monitor_gui", None)

        try:
            with patch("importlib.import_module", side_effect=ImportError("no gui")):
                self.assertFalse(main._gui_runtime_available())
        finally:
            if original is not None:
                sys.modules["monitor_gui"] = original

    def test_parse_args_accepts_custom_host_and_port(self):
        import main

        args = main._parse_args(["--headless", "--host", "0.0.0.0", "--port", "9001"])

        self.assertTrue(args.headless)
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9001)

    def test_run_server_uses_custom_host_and_port(self):
        import main

        with (
            patch("vsens_server.VsensWebSocketServer") as server_cls,
            patch("asyncio.run") as asyncio_run,
        ):
            main._run_server(host="0.0.0.0", port=9001)

        server_cls.assert_called_once_with(host="0.0.0.0", port=9001)
        asyncio_run.assert_called_once_with(server_cls.return_value.start.return_value)
