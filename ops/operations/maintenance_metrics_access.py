"""Generate the minimal reviewed policy extension; never calls AWS."""
import json
import sys
from connection import permissions, template

METRICS_STATEMENT = {
    'Sid': 'ReadSeoulRdsMaintenanceMetrics', 'Effect': 'Allow',
    'Action': 'cloudwatch:GetMetricStatistics', 'Resource': '*',
    'Condition': {'StringEquals': {'aws:RequestedRegion': 'ap-northeast-2'}}}


def extended_policy():
    value = permissions(True)
    value['Statement'].append(METRICS_STATEMENT)
    return value


def extended_template():
    # Original connection/recovery templates stay reproducible at their consumed hashes.
    value = template()
    value['Resources']['ExecutePolicy']['Properties']['PolicyDocument'] = extended_policy()
    return value


if __name__ == '__main__':
    if sys.argv[1:] == ['--policy']:
        value = extended_policy()
    elif sys.argv[1:] == ['--template']:
        value = extended_template()
    else:
        raise SystemExit('Use --policy or --template; this tool does not apply changes')
    print(json.dumps(value, indent=2))
