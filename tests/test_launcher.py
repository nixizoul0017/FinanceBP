"""Check launcher failure handling and readiness before browser navigation."""
import importlib.util
from pathlib import Path
import socket
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('portable_launcher', Path(__file__).resolve().parents[1] / 'scripts/manage.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def test_busy_port_is_skipped(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            port = occupied.getsockname()[1]
            chosen = launcher.available_port(port)
            self.assertGreater(chosen, port)
            with socket.socket() as free:
                free.bind(('127.0.0.1', chosen))

    def test_exit_before_ready_is_reported(self):
        process = MagicMock()
        process.poll.return_value = 1
        with self.assertRaisesRegex(RuntimeError, '已退出'):
            launcher.wait_ready(process, 'http://127.0.0.1:8501')

    def test_readiness_timeout_is_reported(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(launcher.time, 'monotonic', side_effect=[0, 2]):
            with self.assertRaisesRegex(RuntimeError, '未在90秒'):
                launcher.wait_ready(process, 'http://127.0.0.1:8501', timeout=1)

    def test_failed_start_does_not_open_browser_and_stops_child(self):
        process = MagicMock()
        process.poll.return_value = None
        with patch.object(launcher, 'available_port', return_value=8502), \
             patch.object(launcher.subprocess, 'Popen', return_value=process), \
             patch.object(launcher, 'wait_ready', side_effect=RuntimeError('启动失败')), \
             patch.object(launcher, 'stop_process') as stop, \
             patch.object(launcher.webbrowser, 'open') as browser:
            with self.assertRaisesRegex(RuntimeError, '启动失败'):
                launcher.start(8501, False)
            browser.assert_not_called()
            stop.assert_called_once_with(process)

    @unittest.skipUnless(launcher.os.name == 'nt', 'Windows process tree')
    def test_windows_stops_owned_children(self):
        process=MagicMock()
        process.poll.return_value=None
        process.pid=1234
        with patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
            launcher.stop_process(process)
        self.assertEqual(run.call_args.args[0], ['taskkill','/PID','1234','/T','/F'])

    def test_browser_opens_after_readiness(self):
        process = MagicMock()
        process.wait.return_value = 0
        process.poll.return_value = 0
        events = []
        with patch.object(launcher, 'available_port', return_value=8502), \
             patch.object(launcher.subprocess, 'Popen', return_value=process), \
             patch.object(launcher, 'wait_ready', side_effect=lambda *a: events.append('ready')), \
             patch.object(launcher.webbrowser, 'open', side_effect=lambda *a: events.append('browser') or True):
            launcher.start(8501, False)
        self.assertEqual(events, ['ready', 'browser'])

    def test_verification_failure_propagates(self):
        with patch.object(launcher, 'ensure_environment'), \
             patch.object(launcher, 'run', side_effect=launcher.subprocess.CalledProcessError(1, 'stage11.py')):
            with self.assertRaises(launcher.subprocess.CalledProcessError):
                launcher.perform('Verify')


if __name__ == '__main__':
    unittest.main()
