"""Read metadata of the one recovered attempt; never create/retry a snapshot or command."""
from connection import ACCOUNT,REGION,HOSTS,canonical,sha
from bootstrap import need
from maintenance_gate import Gate
from run import read_object
from initial_db_runner import aws_client,DB
from catalog_reapply_contract import REQUEST

RUN='42973951751'
COMMIT='2e7b02f80b4b552a37f320364c2c3036d029a49c'
COMMANDS={'freeze':'c58df09a-1710-4f5c-9ee8-216c577ce108','recover':'211166d9-e6b2-4b06-877c-bba50de9fd61'}
RECOVERY='54270b7fd55008fe46d93d5d6329793a26dd92cb4029c6532c8017c23f27387c'


def snapshot_status(rds):
    name='jjikmuk-ops-initial-db-'+RUN
    try:rows=rds.describe_db_snapshots(DBSnapshotIdentifier=name)['DBSnapshots']
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code')=='DBSnapshotNotFound':return {'status':'ABSENT'}
        raise
    need(len(rows)==1,'CATALOG_STATUS_SNAPSHOT_COUNT');row=rows[0]
    need(row['DBSnapshotIdentifier']==name and row['DBInstanceIdentifier']==DB and row['Encrypted'] is True and
         row['SnapshotType']=='manual' and row['DBSnapshotArn']==f'arn:aws:rds:{REGION}:{ACCOUNT}:snapshot:{name}',
         'CATALOG_STATUS_SNAPSHOT_IDENTITY')
    need(row['Status'] in ('creating','available','failed'),'CATALOG_STATUS_SNAPSHOT_STATE')
    percent=row.get('PercentProgress');need(type(percent) is int and 0<=percent<=100,'CATALOG_STATUS_PERCENT')
    result={'status':row['Status'],'percent':percent}
    for key in ('SnapshotCreateTime','OriginalSnapshotCreateTime'):
        if key in row:result[key]=row[key].isoformat()
    return result


def inspect(api,ctx):
    need(ctx['request_id']==REQUEST,'CATALOG_STATUS_REQUEST')
    gate,_=Gate(api['s3']).read()
    need(gate is not None and gate['request_id']==REQUEST and gate['run_id']==RUN and gate['commit']==COMMIT and
         gate['state']=='WORKING','CATALOG_STATUS_GATE')
    recovery=read_object(api['s3'],'receipts/'+RECOVERY+'/result.json')
    need(recovery['command_id']==COMMANDS['recover'] and recovery['status']=='Success' and recovery['response_code']==0 and
         recovery['report']['status']=='VERIFIED' and all(v is True for v in recovery['report']['checks'].values()),
         'CATALOG_STATUS_RECOVERY')
    commands={}
    for phase,cid in COMMANDS.items():
        row=api['ssm'].get_command_invocation(CommandId=cid,InstanceId=HOSTS['backend'],PluginName='report')
        need(row['CommandId']==cid and row['InstanceId']==HOSTS['backend'] and row['Status']=='Success' and
             row['ResponseCode']==0,'CATALOG_STATUS_COMMAND')
        commands[phase]={k:row[k] for k in ('Status','ExecutionStartDateTime','ExecutionEndDateTime','ExecutionElapsedTime')}
    try:intent=read_object(api['s3'],'receipts/initial-db/'+RUN+'/snapshot-intent.json')
    except Exception as error:
        if getattr(error,'response',{}).get('Error',{}).get('Code')!='NoSuchKey':raise
        intent=None
    if intent is not None:
        need(intent=={'snapshot':'jjikmuk-ops-initial-db-'+RUN,'commit':COMMIT,'request_id':REQUEST},'CATALOG_STATUS_SNAPSHOT_INTENT')
    return {'status':'CATALOG_ATTEMPT_METADATA_COLLECTED','run_id':RUN,'gate':gate,'commands':commands,
            'snapshot_intent':'PRESENT' if intent is not None else 'ABSENT',
            'snapshot':snapshot_status(aws_client('rds')),'recovery_receipt_sha256':sha(canonical(recovery)),
            'checks':{'metadata_only':True,'no_new_ssm_command':True,'no_db_connection':True,'no_snapshot_creation':True}}
