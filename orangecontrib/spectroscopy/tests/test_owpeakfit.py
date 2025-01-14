import unittest
from collections import OrderedDict
from functools import reduce

import Orange
import lmfit
import numpy as np
from Orange.widgets.data.utils.preprocess import DescriptionRole
from Orange.widgets.tests.base import WidgetTest
from orangewidget.tests.base import GuiTest

from orangecontrib.spectroscopy.data import getx
from orangecontrib.spectroscopy.preprocess import Cut, LinearBaseline
from orangecontrib.spectroscopy.tests.spectral_preprocess import wait_for_preview
from orangecontrib.spectroscopy.widgets.gui import MovableVline
from orangecontrib.spectroscopy.widgets.owpeakfit import OWPeakFit, fit_peaks, PREPROCESSORS, \
    create_model, prepare_params, unique_prefix, create_composite_model, pack_model_editor
from orangecontrib.spectroscopy.widgets.peak_editors import ParamHintBox, VoigtModelEditor, \
    PseudoVoigtModelEditor, ExponentialGaussianModelEditor, PolynomialModelEditor

COLLAGEN = Orange.data.Table("collagen")[0:3]
COLLAGEN_2 = LinearBaseline()(Cut(lowlim=1500, highlim=1700)(COLLAGEN))
COLLAGEN_1 = LinearBaseline()(Cut(lowlim=1600, highlim=1700)(COLLAGEN_2))


class TestOWPeakFit(WidgetTest):

    def setUp(self):
        self.widget = self.create_widget(OWPeakFit)
        self.data = COLLAGEN_1

    def test_load_unload(self):
        self.send_signal("Data", Orange.data.Table("iris.tab"))
        self.send_signal("Data", None)

    def test_allint_indv(self):
        for p in PREPROCESSORS:
            with self.subTest(msg=f"Testing model {p.name}"):
                settings = None
                if p.viewclass == PolynomialModelEditor:
                    continue
                if p.viewclass == ExponentialGaussianModelEditor:
                    settings = {'storedsettings':
                                {'name': '',
                                 'preprocessors':
                                 [('orangecontrib.spectroscopy.widgets.owwidget.eg',
                                   {'center': OrderedDict([('value', 1650.0)]),
                                    'sigma': OrderedDict([('value', 5.0),
                                                          ('max', 20.0)]),
                                    'gamma': OrderedDict([('value', 1.0),
                                                          ('vary', False)]),
                                    })]}}
                elif p.viewclass == PseudoVoigtModelEditor:
                    settings = {'storedsettings':
                                {'name': '',
                                 'preprocessors':
                                 [('orangecontrib.spectroscopy.widgets.owwidget.pv',
                                   {'center': OrderedDict([('value', 1650.0)]),
                                    'fraction': OrderedDict([('vary', False)]),
                                    })]}}
                self.widget = self.create_widget(OWPeakFit, stored_settings=settings)
                self.send_signal("Data", self.data)
                if settings is None:
                    self.widget.add_preprocessor(p)
                wait_for_preview(self.widget)

    def test_outputs(self):
        self.widget = self.create_widget(OWPeakFit)
        self.send_signal("Data", self.data)
        self.widget.add_preprocessor(PREPROCESSORS[0])
        wait_for_preview(self.widget)
        self.widget.unconditional_commit()
        self.wait_until_finished()
        fit_params = self.get_output(self.widget.Outputs.fit_params)
        fits = self.get_output(self.widget.Outputs.fits)
        residuals = self.get_output(self.widget.Outputs.residuals)
        data = self.get_output(self.widget.Outputs.annotated_data)
        # fit_params
        self.assertEqual(len(fit_params), len(self.data))
        np.testing.assert_array_equal(fit_params.Y, self.data.Y)
        np.testing.assert_array_equal(fit_params.metas, self.data.metas)
        # fits
        self.assertEqual(len(fits), len(self.data))
        self.assert_domain_equal(fits.domain, self.data.domain)
        np.testing.assert_array_equal(fits.Y, self.data.Y)
        np.testing.assert_array_equal(fits.metas, self.data.metas)
        # residuals
        self.assertEqual(len(residuals), len(self.data))
        self.assert_domain_equal(residuals.domain, self.data.domain)
        np.testing.assert_array_equal(residuals.X, fits.X - self.data.X)
        np.testing.assert_array_equal(residuals.Y, self.data.Y)
        np.testing.assert_array_equal(residuals.metas, self.data.metas)
        # annotated data
        self.assertEqual(len(data), len(self.data))
        np.testing.assert_array_equal(data.X, self.data.X)
        np.testing.assert_array_equal(data.Y, self.data.Y)
        join_metas = np.asarray(np.hstack((self.data.metas, fit_params.X)), dtype=object)
        np.testing.assert_array_equal(data.metas, join_metas)

    def test_saving_models(self):
        settings = self.widget.settingsHandler.pack_data(self.widget)
        self.assertEqual([], settings['storedsettings']['preprocessors'])
        self.widget.add_preprocessor(PREPROCESSORS[0])
        settings = self.widget.settingsHandler.pack_data(self.widget)
        self.assertEqual(PREPROCESSORS[0].qualname,
                         settings['storedsettings']['preprocessors'][0][0])
        self.widget = self.create_widget(OWPeakFit, stored_settings=settings)
        vc = self.widget.preprocessormodel.item(0).data(DescriptionRole).viewclass
        self.assertEqual(PREPROCESSORS[0].viewclass, vc)


class TestPeakFit(unittest.TestCase):

    def setUp(self):
        self.data = COLLAGEN_2

    def test_fit_peaks(self):
        model = lmfit.models.VoigtModel(prefix="v1_")
        params = model.make_params(center=1655)
        out = fit_peaks(self.data, model, params)
        assert len(out) == len(self.data)

    def test_table_output(self):
        pcs = [1547, 1655]
        mlist = [lmfit.models.VoigtModel(prefix=f"v{i}_") for i in range(len(pcs))]
        model = reduce(lambda x, y: x + y, mlist)
        params = model.make_params()
        for i, center in enumerate(pcs):
            p = f"v{i}_"
            dx = 20
            params[p + "center"].set(value=center, min=center-dx, max=center+dx)
            params[p + "sigma"].set(max=50)
            params[p + "amplitude"].set(min=0.0001)
        out_result = model.fit(self.data.X[0], params, x=getx(self.data))
        out_table = fit_peaks(self.data, model, params)
        out_row = out_table[0]
        self.assertEqual(out_row.x.shape[0], len(pcs) + len(out_result.var_names) + 1)
        attrs = [a.name for a in out_table.domain.attributes[:4]]
        self.assertEqual(attrs, ["v0 area", "v0 amplitude", "v0 center", "v0 sigma"])
        self.assertNotEqual(0, out_row["v0 area"].value)
        self.assertEqual(out_result.best_values["v0_amplitude"], out_row["v0 amplitude"].value)
        self.assertEqual(out_result.best_values["v0_center"], out_row["v0 center"].value)
        self.assertEqual(out_result.best_values["v0_sigma"], out_row["v0 sigma"].value)
        self.assertEqual(out_result.redchi, out_row["Reduced chi-square"].value)
        self.assertEqual(out_row.id, self.data.ids[0])


class TestBuildModel(GuiTest):

    def test_model_from_editor(self):
        self.editor = VoigtModelEditor()
        self.editor.set_hint('center', value=1655)
        self.editor.edited.emit()

        m = self.editor.createinstance(prefix=unique_prefix(self.editor, 0))
        self.assertIsInstance(m, self.editor.model)
        editor_params = self.editor.parameters()
        for name, hints in editor_params.items():
            m.set_param_hint(name, **hints)
        params = m.make_params()
        self.assertEqual(params['v0_center'], 1655)


class ModelEditorTest(WidgetTest):
    EDITOR = None

    def setUp(self):
        self.widget = self.create_widget(OWPeakFit)
        if self.EDITOR is not None:
            self.editor = self.add_editor(self.EDITOR, self.widget)
            self.data = COLLAGEN_1
            self.send_signal(self.widget.Inputs.data, self.data)
        else:
            # Test adding all the editors
            for p in self.widget.PREPROCESSORS:
                self.add_editor(p.viewclass, self.widget)

    def wait_for_preview(self):
        wait_for_preview(self.widget)

    def add_editor(self, cls, widget):  # type: (Type[T], object) -> T
        widget.add_preprocessor(pack_model_editor(cls))
        editor = widget.flow_view.widgets()[-1]
        self.process_events()
        return editor

    def get_model_single(self):
        m_def = self.widget.preprocessormodel.item(0)
        return create_model(m_def, 0)

    def get_params_single(self, model):
        m_def = self.widget.preprocessormodel.item(0)
        return prepare_params(m_def, model)


class TestVoigtEditor(ModelEditorTest):
    EDITOR = VoigtModelEditor

    def test_no_interaction(self):
        self.widget.unconditional_commit()
        self.wait_until_finished()
        self.assertIsInstance(self.editor, self.EDITOR)
        m = self.get_model_single()
        self.assertIsInstance(m, self.EDITOR.model)

    def test_create_model(self):
        m = self.get_model_single()
        params = self.get_params_single(m)
        for p in self.editor.parameters():
            self.assertIn(f"{m.prefix}{p}", params)

    def test_set_param(self):
        e = self.editor
        p = e.parameters()['center'].copy()
        p.update({'value': 1623, 'min': 1603, 'max': 1643})
        e.set_param_hints('center', p)
        e.edited.emit()
        p_set = e.parameters()['center']
        self.assertIsInstance(p_set, OrderedDict)
        self.assertEqual(p_set['value'], 1623)
        self.assertEqual(p_set['min'], 1603)
        self.assertEqual(p_set['max'], 1643)

    def test_set_center(self):
        e = self.editor
        e.set_hint('center', value=1655)
        e.edited.emit()
        m = self.get_model_single()
        params = self.get_params_single(m)
        c_p = f'{m.prefix}center'
        self.assertEqual(1655, params[c_p].value)

    def test_only_spec_lines(self):
        self.editor.activateOptions()
        model_lines = self.editor.model_lines()
        lines = [l.label.toPlainText().strip() for l in self.widget.curveplot.markings
                 if isinstance(l, MovableVline)]
        for ml in model_lines:
            self.assertIn(ml, lines)
        no_lines = [p for p in self.editor.model_parameters() if p not in model_lines]
        for nl in no_lines:
            self.assertNotIn(nl, lines)

    def test_move_line(self):
        self.editor.activateOptions()
        l = self.widget.curveplot.markings[0]
        self.assertIsInstance(l, MovableVline)
        l.setValue(1673)
        l.sigMoved.emit(l.value())
        self.assertEqual(1673, self.editor.parameters()['center']['value'])


class TestVoigtEditorMulti(ModelEditorTest):

    def setUp(self):
        self.pcs = [1547, 1655]
        self.widget = self.create_widget(OWPeakFit)
        self.editors = [self.add_editor(VoigtModelEditor, self.widget)
                        for _ in range(len(self.pcs))]
        self.data = COLLAGEN_2
        self.send_signal(self.widget.Inputs.data, self.data)

    def matched_models(self):
        mlist = [lmfit.models.VoigtModel(prefix=f"v{i}_") for i in range(len(self.pcs))]
        model = reduce(lambda x, y: x + y, mlist)
        params = model.make_params()
        for i, center in enumerate(self.pcs):
            p = f"v{i}_"
            dx = 20
            params[p + "center"].set(value=center, min=center - dx, max=center + dx)
            params[p + "sigma"].set(max=50)
            params[p + "amplitude"].set(min=0.0001)
            # Set editor to same values
            e = self.editors[i]
            e_params = e.parameters()
            e_params['center'].update({'value': center, 'min': center - dx, 'max': center + dx})
            e_params['sigma']['max'] = 50
            e_params['amplitude']['min'] = 0.0001
            e.setParameters(e_params)
            e.edited.emit()
        return model, params

    def test_same_params(self):
        model, params = self.matched_models()
        m_def = [self.widget.preprocessormodel.item(i)
                 for i in range(self.widget.preprocessormodel.rowCount())]
        ed_model, ed_params = create_composite_model(m_def)

        self.assertEqual(model.name, ed_model.name)
        self.assertEqual(set(params), set(ed_params))
        for k, v in params.items():
            self.assertEqual(v, ed_params[k])

    def test_same_output(self):
        model, params = self.matched_models()

        out_fit = fit_peaks(self.data, model, params)

        self.widget.unconditional_commit()
        self.wait_until_finished()
        out = self.get_output(self.widget.Outputs.fit_params)

        self.assertEqual(out_fit.domain.attributes, out.domain.attributes)
        np.testing.assert_array_equal(out_fit.X, out.X)

    def test_saving_model_params(self):
        model, params = self.matched_models()
        settings = self.widget.settingsHandler.pack_data(self.widget)
        self.widget = self.create_widget(OWPeakFit, stored_settings=settings)
        m_def = [self.widget.preprocessormodel.item(i)
                 for i in range(self.widget.preprocessormodel.rowCount())]
        sv_model, sv_params = create_composite_model(m_def)

        self.assertEqual(model.name, sv_model.name)
        self.assertEqual(set(params), set(sv_params))


class TestParamHintBox(GuiTest):

    def test_defaults(self):
        hb = ParamHintBox()
        defaults = {
            'value': 0,
            'vary': 'limits',
            'min': float('-inf'),
            'max': float('-inf'),
            'delta': 1,
            'expr': "",
        }
        e_vals = {
            'value': hb.val_e.value(),
            'vary': hb.vary_e.currentText(),
            'min': hb.min_e.value(),
            'max': hb.max_e.value(),
            'delta': hb.delta_e.value(),
            'expr': hb.expr_e.text(),
        }
        self.assertEqual(defaults, e_vals)
        self.assertEqual(OrderedDict([('value', 0.0)]), hb.param_hints())

    def test_keep_delta(self):
        hb = ParamHintBox()
        hb.vary_e.setCurrentText('delta')
        self.assertEqual('delta', hb.vary_e.currentText())
        self.assertEqual((-1, 1), (hb.min_e.value(), hb.max_e.value()))
        hb.vary_e.setCurrentText('limits')
        self.assertEqual((-1, 1), (hb.min_e.value(), hb.max_e.value()))
        hb.vary_e.setCurrentText('delta')
        self.assertEqual((-1, 1), (hb.min_e.value(), hb.max_e.value()))

    def test_delta_update_limits(self):
        hb = ParamHintBox()
        hb.vary_e.setCurrentText('delta')
        self.assertEqual((-1, 1), (hb.min_e.value(), hb.max_e.value()))
        hb.setValues(value=10)
        self.assertEqual((9, 11), (hb.min_e.value(), hb.max_e.value()))
        hb.vary_e.setCurrentText('limits')
        self.assertEqual((9, 11), (hb.min_e.value(), hb.max_e.value()))

    def test_delta_restore_from_saved_hints(self):
        hb = ParamHintBox()
        hb.setValues(value=15.3, min=10.3, max=20.3)
        self.assertEqual('delta', hb.vary_e.currentText())
        self.assertEqual(5.0, hb.delta_e.value())

    def test_expr_change_to_vary(self):
        init = OrderedDict([('expr', "test")])
        hb = ParamHintBox(init_hints=init)
        self.assertEqual(init, hb.param_hints())
        hb.vary_e.setCurrentText('delta')
        self.assertEqual('delta', hb.vary_e.currentText())
        self.assertEqual("", hb.param_hints()['expr'])
        hb.vary_e.setCurrentText('expr')
        self.assertEqual('expr', hb.vary_e.currentText())
        self.assertEqual(init, hb.param_hints())

    def test_expr_set_hint(self):
        hb = ParamHintBox(init_hints=OrderedDict([('expr', "test")]))
        hb.setValues(expr="")
        self.assertEqual('limits', hb.vary_e.currentText())
        self.assertEqual("", hb.param_hints()['expr'])
