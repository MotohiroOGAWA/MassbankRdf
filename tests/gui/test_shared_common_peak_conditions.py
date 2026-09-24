from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

import pandas as pd

from massbank_rdf.gui.session_store import TemporarySessionStore
from massbank_rdf.gui.workflows.common_peak_annotation.input_page import create_app as common_app
from massbank_rdf.gui.workflows.molecular_network.input_page import create_app as network_app
from massbank_rdf.gui.workflows.molecular_network.processor import _annotate_unknown_clusters
from massbank_rdf.services.common_peak_annotation.common_peak_finder import PeakRecord, find_common_peaks
from massbank_rdf.services.common_peak_annotation.common_peak_annotator import annotate_common_peaks_with_massbank
from massbank_rdf.services.common_peak_annotation.settings import build_common_peak_settings
from massbank_rdf.services.molecular_network import common_cluster_peaks


class SharedCommonPeakTest(unittest.TestCase):
    def test_both_ui_callbacks_save_identical_common_settings(self):
        stores = [TemporarySessionStore(), TemporarySessionStore()]
        common = common_app(stores[0])
        network = network_app(stores[1])
        common_run = next(f for f in common.fns.values() if f.fn and f.fn.__name__ == '_run_and_save')
        network_run = next(f for f in network.fns.values() if f.fn and f.fn.__name__ == 'run')
        for a, b in zip(common_run.inputs[1:9], network_run.inputs[5:13]):
            for key in ('label', 'value', 'minimum', 'maximum', 'choices', 'info'):
                self.assertEqual(getattr(a, key, None), getattr(b, key, None))
        settings = [0.02, 0.1, 7, 2, 25, 4, 0.6, 'Negative']
        request = SimpleNamespace(request=SimpleNamespace(cookies={
            'common_peak_session_id': 'common', 'molecular_network_session_id': 'network',
        }))
        values = [c.value for c in common_run.inputs]
        values[0] = '100 10\n200 20'
        values[1:9] = settings
        common_run.fn(*values, request=request)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'spectra.data'
            path.write_text('Name: A\nIONMODE: Negative\nNum Peaks: 2\n100 10\n200 20\n')
            values = [c.value for c in network_run.inputs]
            values[0] = [str(path)]
            values[1] = pd.DataFrame([{'sample_class': 'Sample'}])
            values[5:13] = settings
            network_run.fn(*values, request=request)
        expected = stores[0].get('common')['summary']
        payload = stores[1].get('network')
        self.assertEqual(expected, payload['molecular_network_job']['common_peak_settings'])
        self.assertEqual(payload['msp_batch_job']['top_n'], 25)
        self.assertEqual(payload['msp_batch_job']['min_matched_peaks'], 4)

    def test_detector_matches_shared_ranking_and_grouping(self):
        spectra = {'a': ([100, 100.009, 100.018, 200], [100, 30, 20, 1]),
                   'b': ([100.005, 200], [1000, 10])}
        records = [PeakRecord(i, name, list(zip(*peaks))) for i, (name, peaks) in enumerate(spectra.items(), 1)]
        expected = find_common_peaks(records, mz_tolerance=0.01, minimum_relative_intensity=0.05)
        result = common_cluster_peaks(spectra, spectra, minimum_presence_fraction=0, max_peaks=10)
        pd.testing.assert_frame_equal(result[expected.columns], expected)
        self.assertEqual(result['intensity'].tolist(), expected['record_count'].tolist())
        filtered = common_cluster_peaks(spectra, spectra, minimum_presence_fraction=1, max_peaks=1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]['record_count'], 2)

    def test_network_annotation_uses_shared_search_ranking_and_limit(self):
        module = 'massbank_rdf.services.common_peak_annotation.common_peak_annotator'
        key = 'AAAAAAAAAAAAAA-BBBBBBBBBB-C'
        db = Mock()
        db.search_record_ids_by_cosine_similarity_sql.return_value = pd.DataFrame([
            {'id': 1, 'cosine_score': 0.9, 'matched_peak_count': 2},
            {'id': 2, 'cosine_score': 0.2, 'matched_peak_count': 1},
        ])
        db.get_records_by_ids_dataframe.return_value = pd.DataFrame([
            {'id': 1, 'inchikey': key, 'accession_id': 'TEST'}])
        scores = Mock()
        scores.scores_for_inchikeys.return_value = pd.DataFrame([{'inchikey': key, 'kg_metadata_count': 10}])
        kg = Mock()
        kg.search_evidence_by_inchikeys.return_value = ({'metadata': {}, 'features': []}, {})
        settings = build_common_peak_settings(0.01, 0.05, 10, 1, 50, 1, 0.5, '')
        spectra = {'a': ([100, 200], [100, 30]), 'b': ([100.005, 300], [1000, 10])}
        assignments = pd.DataFrame([{'node_id': n, 'cluster_id': 'c'} for n in spectra])
        with patch(module + '.MassBankDatabase', return_value=db), patch(module + '.KgMetadataScoreService', return_value=scores):
            direct = annotate_common_peaks_with_massbank(
                find_common_peaks([PeakRecord(i, n, list(zip(*p))) for i, (n, p) in enumerate(spectra.items())], mz_tolerance=0.01, minimum_relative_intensity=0.05),
                **{k: v for k, v in settings.items() if k != 'minimum_relative_intensity'},
            )['massbank_hits']
            result, common, _, _ = _annotate_unknown_clusters(
                assignments, spectra, pd.DataFrame(), pd.DataFrame(),
                {'common_peak_settings': settings, 'common_presence_fraction': 0}, {}, kg,
            )
            for name in spectra:
                pd.testing.assert_frame_equal(result.loc[result.spectrum_uid == name, direct.columns].reset_index(drop=True), direct)
            call = db.search_record_ids_by_cosine_similarity_sql.call_args.kwargs
            self.assertIsNone(call['ion_mode'])
            self.assertIsNone(call['precursor_mz'])
            self.assertEqual(call['intensity_list'].tolist(), common['record_count'].tolist())
            kg.search_evidence_by_inchikeys.assert_called_once()
            db.reset_mock()
            _annotate_unknown_clusters(assignments, spectra, pd.DataFrame(), pd.DataFrame([{'spectrum_uid': 'a', 'selected_for_kg': True}]), {'common_peak_settings': settings, 'common_presence_fraction': 0}, {}, kg)
            db.search_record_ids_by_cosine_similarity_sql.assert_not_called()

    def test_invalid_shared_settings_are_rejected(self):
        for index, value in ((0, float('nan')), (1, 1.1), (2, 0), (4, 1.5), (6, -1)):
            args = [0.01, 0.05, 10, None, 50, 3, 0.5, 'Positive']
            args[index] = value
            with self.subTest(index=index), self.assertRaises(ValueError):
                build_common_peak_settings(*args)
