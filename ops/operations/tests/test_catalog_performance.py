import unittest
from datetime import datetime,timedelta,timezone
from unittest.mock import Mock,patch
from pathlib import Path
import catalog_performance as metrics


class PerformanceTests(unittest.TestCase):
    def test_only_fixed_cloudwatch_targets_are_read_and_empty_is_unknown(self):
        now=datetime.now(timezone.utc);client=Mock()
        def response(**kw):return {'Label':kw['MetricName'],'Datapoints':[] if kw['MetricName']=='EBSIOBalance%' else
            [{'Timestamp':now-timedelta(minutes=5),'Average':1.0,'Maximum':2.0,'Minimum':0.5,'Unit':'DO_NOT_EXPORT'}]}
        client.get_metric_statistics.side_effect=response;result=metrics.inspect(client,now)
        self.assertEqual(len(result['metrics']),15)
        self.assertEqual([r['status'] for r in result['metrics']].count('NO_DATA'),2)
        self.assertTrue(all(c[0]=='get_metric_statistics' for c in client.mock_calls))
        for call in client.get_metric_statistics.call_args_list:
            self.assertEqual(len(call.kwargs['Dimensions']),1)
            self.assertIn(call.kwargs['Dimensions'][0]['Value'],(metrics.DB,metrics.HOSTS['backend']))
        self.assertNotIn('Unit',result['metrics'][0]['points'][0])

    def test_invalid_metric_time_or_number_is_not_a_valid_observation(self):
        now=datetime.now(timezone.utc);client=Mock()
        for change in ({'Average':float('nan')},{'Timestamp':now+timedelta(seconds=1)}):
            row={'Timestamp':now,'Average':1,'Maximum':2,'Minimum':0};row.update(change)
            client.get_metric_statistics.return_value={'Label':'CPUUtilization','Datapoints':[row]}
            with self.assertRaisesRegex(ValueError,'PERFORMANCE_POINT'):metrics.inspect(client,now)

    def test_parallel_group_is_exclusive_to_metrics_and_mutation_modes_keep_original_group(self):
        text=(Path(metrics.__file__).parents[2]/'.github/workflows/server-operations.yml').read_text(encoding='utf-8')
        self.assertIn("inputs.mode == 'performance' && 'jjikmuk-performance-read' || 'backend-production-deployment'",text)
        self.assertIn("if: inputs.mode == 'performance'\n        run: python3 -B ops/operations/catalog_performance.py",text)
        self.assertIn("if: inputs.mode == 'storage'\n        run: python3 -B ops/operations/storage_metrics.py",text)


if __name__=='__main__':unittest.main()
