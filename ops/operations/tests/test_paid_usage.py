import json
from contextlib import closing, chdir
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import paid_usage_probe as probe
from build_paid_usage_plans import plan
from run import safe_report, load_plan
from connection import sha


class PaidUsageTests(unittest.TestCase):
    def test_chatbot_prior_and_current_calls_are_combined_without_writes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()/'ledger.sqlite3'
            with closing(sqlite3.connect(path)) as db:
                db.execute('CREATE TABLE budget(id INTEGER,cap INTEGER,prior INTEGER)')
                db.execute('INSERT INTO budget VALUES(1,1000,17)')
                db.execute('CREATE TABLE calls(id INTEGER,kind TEXT)')
                db.executemany('INSERT INTO calls VALUES(?,?)',[(1,'generation'),(2,'embedding')])
                db.commit()
            before = path.read_bytes()
            self.assertEqual(probe.chatbot_counts(path), {'limit':1000,'used':19,'remaining':981})
            self.assertEqual(path.read_bytes(), before)

    def test_missing_ledger_is_not_created(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()/'missing.sqlite3'
            with self.assertRaisesRegex(ValueError,'CHATBOT_LEDGER_PATH'):
                probe.chatbot_counts(path)
            self.assertFalse(path.exists())

    def test_counter_overflow_and_negative_prior_are_rejected(self):
        for cap, used in ((1000,1001),(1001,0),(1000,-1),(True,0)):
            with self.subTest(cap=cap,used=used), self.assertRaises(ValueError):
                probe.counters(cap,used)

    def test_ocr_counts_attempts_without_reading_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory).resolve()/'paid-attempt.claimed'
            marker.write_text('claimed failure is still charged')
            marker.with_name(marker.name+'.000002').touch()
            (marker.parent/'unrelated.txt').touch()
            self.assertEqual(probe.ocr_counts(marker,1000), {'limit':1000,'used':2,'remaining':998})

    def test_ocr_gap_and_malformed_marker_fail(self):
        for suffix in ('.000003','.junk','.000001','.001001'):
            with self.subTest(suffix=suffix), tempfile.TemporaryDirectory() as directory:
                marker = Path(directory).resolve()/'paid-attempt.claimed'
                marker.touch()
                marker.with_name(marker.name+suffix).touch()
                with self.assertRaises(ValueError):
                    probe.ocr_counts(marker,1000)

    def test_ocr_empty_and_exhausted_ledgers(self):
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory).resolve()/'paid-attempt.claimed'
            self.assertEqual(probe.ocr_counts(marker,2)['remaining'],2)
            marker.touch()
            marker.with_name(marker.name+'.000002').touch()
            self.assertEqual(probe.ocr_counts(marker,2)['remaining'],0)

    def test_process_change_rejects_result(self):
        ledger = Path('/fixed.sqlite3')
        environment = ('FOOD_CHATBOT_EXTERNAL_AI_STATE_DB='+str(ledger)+'\0').encode()
        with patch.object(probe,'CHAT_LEDGER',ledger), \
             patch.object(probe,'service_identity',side_effect=[('123',b'a'),('124',b'b')]), \
             patch('pathlib.Path.open',unittest.mock.mock_open(read_data=environment)), \
             patch.object(probe,'chatbot_counts',return_value={'limit':1000,'used':4,'remaining':996}):
            with self.assertRaisesRegex(ValueError,'CHATBOT_PROCESS_CHANGED'):
                probe.chatbot()

    def test_report_has_no_paths_or_environment(self):
        with patch.object(probe,'chatbot',return_value={'limit':1000,'used':4,'remaining':996}):
            result = probe.report('chatbot')
        self.assertEqual(safe_report(json.dumps(result)),result)
        self.assertEqual(set(result),{'status','checks','counts'})

    def test_plans_match_reviewed_probe_and_valid_contract(self):
        root = Path(__file__).resolve().parents[1]
        for kind in ('chatbot','ocr'):
            path = root/'plans'/('paid-usage-'+kind+'-20261112.json')
            self.assertEqual(json.loads(path.read_bytes()),plan(kind))
            relative = path.relative_to(root.parents[1]).as_posix()
            with chdir(root.parents[1]):
                checked, target = load_plan(relative,sha(path.read_bytes()))
                self.assertEqual(checked,plan(kind))
                self.assertEqual(target, 'i-0feac4ca32779b098' if kind == 'ocr' else 'i-06350403fe0400e1b')


if __name__ == '__main__':
    unittest.main()
