"""Fixed CloudWatch metrics only; safe alongside a running catalog operation."""
from datetime import datetime,timedelta,timezone
import math,os
from bootstrap import need
from connection import REPO,HOSTS
from run import context,clients,save_local
from initial_db_runner import aws_client,DB
from catalog_progress import safe_error

METRICS=(('AWS/RDS','DBInstanceIdentifier',DB,(
    'CPUUtilization','CPUCreditBalance','FreeableMemory','ReadLatency','WriteLatency','DiskQueueDepth','ReadIOPS','WriteIOPS','FreeStorageSpace','EBSIOBalance%','EBSByteBalance%')),
    ('AWS/EC2','InstanceId',HOSTS['backend'],('CPUUtilization','CPUCreditBalance','EBSIOBalance%','EBSByteBalance%')))


def inspect(client,now):
    need(now.tzinfo is not None,'CATALOG_PERFORMANCE_CLOCK')
    results=[]
    for namespace,dimension,target,names in METRICS:
        for name in names:
            response=client.get_metric_statistics(Namespace=namespace,MetricName=name,
                Dimensions=[{'Name':dimension,'Value':target}],StartTime=now-timedelta(minutes=90),EndTime=now,
                Period=300,Statistics=['Average','Maximum','Minimum'])
            need(response.get('Label')==name and len(response.get('Datapoints',[]))<=20,'CATALOG_PERFORMANCE_RESPONSE')
            points=[]
            for row in response.get('Datapoints',[]):
                stamp=row['Timestamp'];values=[row[k] for k in ('Average','Maximum','Minimum')]
                need(isinstance(stamp,datetime) and stamp.tzinfo is not None and 0<=(now-stamp).total_seconds()<=5700 and
                     all(type(v) in (float,int) and math.isfinite(v) and 0<=v<2**63 for v in values),'CATALOG_PERFORMANCE_POINT')
                points.append({'epoch':int(stamp.timestamp()),'average':values[0],'maximum':values[1],'minimum':values[2]})
            results.append({'namespace':namespace,'metric':name,'points':sorted(points,key=lambda p:p['epoch']),
                            'status':'OBSERVED' if points else 'NO_DATA'})
    return {'status':'CATALOG_PERFORMANCE_OBSERVED','observed_at':now.isoformat(),'metrics':results,
            'checks':{'cloudwatch_only':True,'no_ssm_command':True,'no_database_connection':True,'no_setting_change':True}}


def main():
    ctx=context(os.environ['EXPECTED_SHA'],True)
    need(os.environ.get('GITHUB_WORKFLOW_REF')==REPO+'/.github/workflows/server-operations.yml@refs/heads/main' and
         os.environ.get('OPERATION_MODE')=='performance','CATALOG_PERFORMANCE_WORKFLOW')
    clients(True)  # Validate the same account/role and private operations bucket.
    result=inspect(aws_client('cloudwatch'),datetime.now(timezone.utc))
    result['context']=ctx;save_local('performance.json',result)
    print('CATALOG_PERFORMANCE_COLLECTED_READ_ONLY')


if __name__=='__main__':
    try:main()
    except Exception as error:
        save_local('performance-failure.json',{'code':safe_error(error)})
        print('CATALOG_PERFORMANCE_READ_STOPPED '+safe_error(error));raise SystemExit(1)
