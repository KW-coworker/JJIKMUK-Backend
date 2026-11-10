from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
from connection import canonical, permissions, sha, template
from control import dispatch, approve_environment
from fulltext_definition import summarize
from maintenance_metrics_access import extended_policy, extended_template, METRICS_STATEMENT
from storage_metrics import observe
from run import safe_report


class MaintenanceMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 10, 7, 10, tzinfo=timezone.utc)
        self.client = MagicMock()
        self.rows = [{'Timestamp': self.now - timedelta(seconds=n), 'Minimum': 12_000_000_000,
                      'Unit': 'Bytes'} for n in (60, 120, 180)]
        self.client.get_metric_statistics.return_value = {'Label': 'FreeStorageSpace', 'Datapoints': self.rows}

    def test_fixed_read_and_freshness(self):
        report = observe(self.client, self.now)
        self.assertEqual(report['counts']['sample_age_seconds'], 60)
        self.assertEqual(report, safe_report(json.dumps(report)))
        call = self.client.get_metric_statistics.call_args.kwargs
        self.assertEqual(call['Namespace'], 'AWS/RDS')
        self.assertEqual(call['MetricName'], 'FreeStorageSpace')
        self.assertEqual(call['Dimensions'], [{'Name':'DBInstanceIdentifier','Value':'jjikmuk-dev-db'}])
        self.assertEqual(call['Statistics'], ['Minimum'])

    def test_stale_missing_duplicate_gap_future_and_bad_numbers_fail(self):
        bad = [[], self.rows[:1], [self.rows[0], self.rows[0]],
               [dict(r, Timestamp=self.now-timedelta(seconds=240+i*60)) for i,r in enumerate(self.rows[:2])],
               [self.rows[0], dict(self.rows[1], Timestamp=self.now-timedelta(seconds=240))],
               [dict(self.rows[0], Timestamp=self.now+timedelta(seconds=1)), self.rows[1]]]
        for field, value in [('Minimum', float('nan')), ('Minimum', -1), ('Minimum', True),
                             ('Minimum', 2**63), ('Unit', 'Gigabytes'), ('Timestamp', datetime(2026,11,10))]:
            bad.append([dict(self.rows[0], **{field:value}), self.rows[1]])
        for rows in bad:
            self.client.get_metric_statistics.return_value['Datapoints'] = rows
            with self.subTest(rows=rows), self.assertRaises(ValueError): observe(self.client, self.now)

    def test_low_value_is_reported_and_not_mislabeled_safe(self):
        self.rows[0]['Minimum'] = 0
        report = observe(self.client, self.now)
        self.assertEqual(report['counts']['window_minimum_bytes'], 0)
        self.assertEqual(report['checks'], {'fresh_metric': True})

    def test_cloudwatch_minute_rounded_start_is_accepted(self):
        now = self.now + timedelta(seconds=59)
        self.rows.append(dict(self.rows[0], Timestamp=self.now-timedelta(minutes=5)))
        observe(self.client, now)
        self.assertEqual(self.client.get_metric_statistics.call_args.kwargs['StartTime'],
                         self.now-timedelta(minutes=5))

    def test_extension_preserves_all_other_policy_and_resources(self):
        self.assertEqual(extended_policy()['Statement'][:-1], permissions(True)['Statement'])
        self.assertEqual(extended_policy()['Statement'][-1], METRICS_STATEMENT)
        before, after = template(), extended_template()
        after['Resources']['ExecutePolicy']['Properties']['PolicyDocument'] = permissions(True)
        self.assertEqual(before, after)
        self.assertEqual(METRICS_STATEMENT['Action'], 'cloudwatch:GetMetricStatistics')
        root=Path(__file__).resolve().parents[1]
        self.assertEqual(json.loads((root/'maintenance-metrics-policy.json').read_bytes()), extended_policy())

    def test_definition_tokens_keep_only_scoped_index(self):
        ddl='CREATE TABLE products (\n FULLTEXT KEY `ft_products_search_keywords` (`search_keywords`) /*!50100 WITH PARSER `ngram` */  ,\n unrelated_secret_column varchar(10)\n)'
        result=summarize(ddl)
        self.assertTrue(result['checks']['normalized_exact_ngram_definition'])
        self.assertNotIn('unrelated_secret', json.dumps(result))
        self.assertEqual(result, safe_report(json.dumps(result)))
        self.assertFalse(summarize(ddl.replace('ngram','mecab'))['checks']['normalized_exact_ngram_definition'])
        with self.assertRaises(ValueError): summarize(ddl.replace('search_keywords','different_column'))

    def test_storage_dispatch_requires_confirmation(self):
        api=MagicMock();api.call.return_value={'object':{'sha':'a'*40}}
        inputs={'mode':'storage','expected_sha':'a'*40,'request_id':'b'*32,'confirm':False}
        request={'workflow':'server-operations.yml','inputs':inputs,'approval':{'status':'APPROVED','input_sha256':sha(canonical(inputs))}}
        with tempfile.TemporaryDirectory() as td,self.assertRaisesRegex(ValueError,'WRITE_CONFIRMATION_REQUIRED'):
            dispatch(api,request,Path(td)/'intent.json')

    def test_storage_environment_is_bound_to_request(self):
        api=MagicMock()
        approval={'status':'APPROVED','run_id':'123','expected_sha':'a'*40,'request_id':'b'*32,'mode':'storage'}
        api.call.side_effect=[{'path':'.github/workflows/server-operations.yml','head_branch':'main','head_sha':'a'*40,
            'display_title':'Server operations storage at '+'a'*40+' ['+'b'*32+']'},
            [{'environment':{'name':'production','id':1},'current_user_can_approve':True}],{}]
        approve_environment(api,'123',approval)
        self.assertEqual(api.call.call_args.args[1], 'POST')


if __name__ == '__main__': unittest.main()
