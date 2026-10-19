import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

SCRIPT_DIR = Path(__file__).resolve().parents[1] / 'scripts'
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import desktop_launcher as desktop


class DesktopLauncherTests(unittest.TestCase):
    def test_python313_and314_supported(self):
        self.assertIn((3, 13), desktop.SUPPORTED)
        self.assertIn((3, 14), desktop.SUPPORTED)
        self.assertNotIn((3, 12), desktop.SUPPORTED)

    def test_missing_file_reports_stage_and_solution(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(desktop, 'ROOT', Path(folder)):
            controller = desktop.Controller(lambda *a: None)
            with self.assertRaises(desktop.StartupError) as caught:
                controller.prepare()
            self.assertEqual(caught.exception.stage, '项目文件')
            self.assertIn('完整解压', caught.exception.solution)

    def test_unsupported_python_has_clear_error(self):
        with patch.object(desktop.sys, 'version_info', (3, 12)), self.assertRaises(desktop.StartupError) as caught:
            desktop.Controller(lambda *a: None).prepare()
        self.assertEqual(caught.exception.stage, 'Python环境')

    def test_no_browser_after_environment_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[]
            controller=desktop.Controller(lambda *a: events.append(a))
            with patch.object(desktop, 'RUNTIME', Path(folder)), \
                 patch.object(controller, 'prepare', side_effect=desktop.StartupError('依赖安装', '安装失败', '检查网络')), \
                 patch.object(desktop.webbrowser, 'open') as browser:
                controller.log_path=Path(folder)/'test.log'
                controller.launch()
                browser.assert_not_called()
                self.assertIn(('error', ('依赖安装','安装失败','检查网络')), events)
                self.assertTrue(controller.log_path.read_text().strip())
            controller.log.close()

    def test_reuses_verified_service_and_opens_automatically(self):
        with tempfile.TemporaryDirectory() as folder:
            events=[]
            controller=desktop.Controller(lambda *a: events.append(a))
            controller.log_path=Path(folder)/'test.log'
            with patch.object(desktop, 'RUNTIME', Path(folder)), patch.object(controller, 'prepare'), \
                 patch.object(desktop, 'existing_service', return_value='http://127.0.0.1:8501'), \
                 patch.object(desktop.subprocess, 'Popen') as spawn, \
                 patch.object(desktop.webbrowser, 'open', return_value=True) as browser:
                controller.launch()
                spawn.assert_not_called()
                browser.assert_called_once_with('http://127.0.0.1:8501')
                self.assertIn(('ready', 'http://127.0.0.1:8501'), events)
            controller.log.close()

    def test_unrelated_process_is_not_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            state=Path(folder)/'state.json'
            state.write_text(json.dumps({'project':str(desktop.ROOT),'pid':123,'port':8501}))
            with patch.object(desktop, 'STATE', state), patch.object(desktop, 'matching_process', return_value=False), \
                 patch.object(desktop, 'healthy') as health:
                self.assertIsNone(desktop.existing_service())
                health.assert_not_called()

    def test_command_failure_is_classified(self):
        controller=desktop.Controller(lambda *a: None)
        controller.log=MagicMock()
        process=MagicMock()
        process.wait.return_value=1
        process.poll.return_value=1
        with patch.object(desktop.subprocess, 'Popen', return_value=process), self.assertRaises(desktop.StartupError) as caught:
            controller.command(['python','-m','pip'], '依赖安装', '失败', '检查网络')
        self.assertEqual(caught.exception.stage, '依赖安装')

    def test_loopback_health_bypasses_proxy(self):
        response=MagicMock()
        response.status=200
        response.read.return_value=b'ok'
        opener=MagicMock()
        opener.open.return_value.__enter__.return_value=response
        with patch.object(desktop, 'build_opener', return_value=opener), patch.object(desktop, 'ProxyHandler') as proxy:
            self.assertTrue(desktop.healthy('http://127.0.0.1:8501'))
            proxy.assert_called_once_with({})


if __name__=='__main__':
    unittest.main()
