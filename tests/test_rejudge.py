from copy import deepcopy
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'evals'))
from rejudge import rejudge


class RejudgeTests(unittest.TestCase):
    def setUp(self):
        self.case = {'id': 'A6', 'question': 'q', 'expected': 'e',
                     'requires_tools': ['get_incident_details']}
        self.item = {'id': 'A6', 'question': 'q', 'expected': 'e',
                     'result': {'status': 'completed', 'answer': 'unchanged', 'trace': []},
                     'grade': {'score': None, 'status': 'unscored'}}
        self.report = {'config': {'judge_provider': 'deepseek', 'judge_model': 'deepseek-flash'},
                       'cases': [self.item]}

    @patch('rejudge.grade_case', return_value={'score': 80, 'status': 'scored'})
    def test_preserves_original_answers_and_uses_full_case_definition(self, grade):
        original = deepcopy(self.report)
        save = Mock()
        judge = Mock()
        revised = rejudge(self.report, {'A6': self.case}, ['A6'], judge, save)
        self.assertEqual(self.report, original)
        self.assertEqual(revised['cases'][0]['result'], self.item['result'])
        grade.assert_called_once_with(self.case, self.item['result'], judge)
        self.assertEqual(revised['summary']['score_0_100'], 80)
        self.assertEqual(revised['cases'][0]['rejudge_history'][0]['previous_grade'],
                         self.item['grade'])
        save.assert_called_once_with(revised)

    @patch('rejudge.grade_case')
    def test_rejects_scored_case_or_changed_dataset_before_api_call(self, grade):
        self.item['grade']['score'] = 10
        with self.assertRaises(ValueError):
            rejudge(self.report, {'A6': self.case}, ['A6'], Mock(), Mock())
        self.item['grade']['score'] = None
        self.case['expected'] = 'changed'
        with self.assertRaises(ValueError):
            rejudge(self.report, {'A6': self.case}, ['A6'], Mock(), Mock())
        grade.assert_not_called()
