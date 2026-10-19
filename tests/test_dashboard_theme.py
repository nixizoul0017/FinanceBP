"""Display changes must preserve financial inputs, chart data and frozen reports."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest
from test_filter_apply import apply_filters

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from dashboard import theme
from test_stage9 import simple_history


class PalettePreferenceTests(unittest.TestCase):
    def test_preferences_round_trip_and_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'runtime/preferences.json'
            self.assertEqual(theme.load_preference(path),'navy')
            for key in theme.PALETTES:
                self.assertTrue(theme.save_preference(key,path))
                self.assertEqual(theme.load_preference(path),key)

    def test_corrupt_or_untrusted_preference_uses_default(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preferences.json'
            for contents in ('{bad','[]','{"theme": ["teal"]}','{"theme": "</style>"}'):
                path.write_text(contents,encoding='utf-8')
                self.assertEqual(theme.load_preference(path),'navy')

    def test_failed_save_does_not_raise_or_leave_temp_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'existing-directory'
            path.mkdir()
            self.assertFalse(theme.save_preference('teal',path))
            self.assertEqual(list(Path(folder).glob('.ui-preference-*')),[])

    def test_invalid_palette_is_not_written(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'preferences.json'
            self.assertFalse(theme.save_preference('unknown',path))
            self.assertFalse(path.exists())
            self.assertEqual(theme.palette('unknown').key,'navy')

    def test_financial_direction_colors_are_stable(self):
        self.assertEqual(len({p.success for p in theme.PALETTES.values()}),1)
        self.assertEqual(len({p.danger for p in theme.PALETTES.values()}),1)
        for key,palette in theme.PALETTES.items():
            self.assertIn(f'data-finance-theme="{key}"',theme.theme_css(palette))
            self.assertIn(palette.primary,theme.theme_css(palette))


class DashboardThemeTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory()
        self.preference=Path(self.directory.name)/'preferences.json'
        self.preference_patch=patch.object(theme,'PREFERENCE_PATH',self.preference)
        self.preference_patch.start()

    def tearDown(self):
        self.preference_patch.stop()
        self.directory.cleanup()

    def start(self):
        app=AppTest.from_file(ROOT/'app.py',default_timeout=120)
        app.session_state['ui_theme']='navy'
        app.session_state['source']='小样本核对'
        app.run()
        self.assertFalse(app.exception)
        return app

    def test_color_switch_keeps_filters_cache_and_chart_values(self):
        app=self.start()
        app.multiselect('product_filter').set_value(['P001'])
        app.selectbox('display_unit').set_value('万元')
        app.run()
        apply_filters(app)
        original=app.session_state['engine']
        before=json.loads(app.get('plotly_chart')[0].proto.spec)['data']
        values=[(m.label,m.value) for m in app.metric]
        keys=set(app.session_state['pack_cache'])
        for key,palette in theme.PALETTES.items():
            app.radio('ui_theme').set_value(key).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.multiselect('product_filter').value,['P001'])
            self.assertEqual(app.selectbox('display_unit').value,'万元')
            self.assertIs(app.session_state['engine'],original)
            self.assertEqual(set(app.session_state['pack_cache']),keys)
            self.assertEqual([(m.label,m.value) for m in app.metric],values)
            after=json.loads(app.get('plotly_chart')[0].proto.spec)['data']
            self.assertEqual(after[0]['line']['color'],palette.primary)
            for old,new in zip(before,after):
                self.assertEqual(old['x'],new['x'])
                self.assertEqual(old['y'],new['y'])
            self.assertEqual(theme.load_preference(self.preference),key)
        fresh=AppTest.from_file(ROOT/'app.py',default_timeout=120).run()
        self.assertEqual(fresh.radio('ui_theme').value,'plum')

    def test_all_palettes_render_all_nine_pages(self):
        facts=simple_history()
        facts.metadata['row_counts']={name:len(frame) for name,frame in facts.tables.items()}
        with patch('etl.sources.load_facts',return_value=facts):
            app=self.start()
            for key in theme.PALETTES:
                app.radio('ui_theme').set_value(key).run()
                for page in ('经营总览','月度趋势','维度分析','预算工作台','预算比较','预测与情景','对账与跟进','点评与月报','数据与下载'):
                    app.button('nav_' + page).click().run()
                    self.assertFalse(app.exception,(key,page,[item.message for item in app.exception]))
                    self.assertEqual(app.session_state['page'],page)
                    self.assertEqual(app.button('nav_' + page).proto.type,'primary')
                    self.assertEqual(app.radio('ui_theme').value,key)
                    if page=='预算比较':
                        bridge=json.loads(app.get('plotly_chart')[0].proto.spec)['data'][0]
                        self.assertEqual(bridge['increasing']['marker']['color'],theme.palette(key).success)
                        self.assertEqual(bridge['decreasing']['marker']['color'],theme.palette(key).danger)
                        self.assertEqual(bridge['totals']['marker']['color'],theme.palette(key).primary)

    def test_report_snapshot_and_assumptions_survive_color_change(self):
        with patch('etl.sources.load_facts',return_value=simple_history()):
            app=self.start()
            app.button('nav_点评与月报').click().run()
            app.number_input('report_price_change').set_value(3.0)
            app.button('FormSubmitter:report_generation-生成点评与Excel月报').click().run()
            generated=app.session_state['report_generated']
            for key in ('teal','plum','navy'):
                app.radio('ui_theme').set_value(key).run()
                self.assertFalse(app.exception)
                self.assertEqual(app.number_input('report_price_change').value,3.0)
                retained=app.session_state['report_generated']
                self.assertEqual(retained['excel'],generated['excel'])
                self.assertEqual(retained['report']['report_id'],generated['report']['report_id'])

    def test_navigation_and_report_shortcut_preserve_scope(self):
        app=self.start()
        app.multiselect('product_filter').set_value(['P001'])
        app.selectbox('display_unit').set_value('万元')
        app.run()
        apply_filters(app)
        original=app.session_state['engine']
        before=[(m.label,m.value) for m in app.metric]
        for destination in ('月度趋势','维度分析','预算比较','数据与下载'):
            app.button('nav_' + destination).click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.session_state['page'],destination)
            self.assertEqual(app.multiselect('product_filter').value,['P001'])
            self.assertIs(app.session_state['engine'],original)
        app.button('open_report').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['page'],'点评与月报')
        app.button('nav_经营总览').click().run()
        self.assertEqual([(m.label,m.value) for m in app.metric],before)
        self.assertEqual(app.selectbox('display_unit').value,'万元')

    def test_demo_default_unit_and_explicit_yuan_display(self):
        with patch('etl.sources.load_facts',return_value=simple_history()):
            app=AppTest.from_file(ROOT/'app.py',default_timeout=120).run()
            self.assertFalse(app.exception)
            self.assertEqual(app.selectbox('display_unit').value,'万元')
            self.assertEqual(app.metric[0].value,'0.95')
            engine=app.session_state['engine']
            app.selectbox('display_unit').set_value('元').run()
            apply_filters(app)
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value,'9,500.00')
            self.assertIs(app.session_state['engine'],engine)


if __name__=='__main__':
    unittest.main()
