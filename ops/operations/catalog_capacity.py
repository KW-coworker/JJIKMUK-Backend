"""Read exact RDS storage configuration and fresh free space; no changes or SSM."""
from datetime import datetime,timezone
from connection import ACCOUNT,REGION
from bootstrap import need
from maintenance_gate import Gate
from catalog_state_inspection import REQUEST,RUN
from initial_db_runner import aws_client,DB
from initial_contract import DB_HOST
from storage_metrics import observe


def report(db,metric):
    need(db.get('DBInstanceIdentifier')==DB and db.get('DBInstanceArn')==f'arn:aws:rds:{REGION}:{ACCOUNT}:db:{DB}' and
         db.get('Endpoint',{}).get('Address')==DB_HOST and db.get('Engine')=='mysql' and
         db.get('DBInstanceStatus')=='available' and db.get('StorageEncrypted') is True,'CATALOG_CAPACITY_TARGET')
    allocated=db.get('AllocatedStorage');maximum=db.get('MaxAllocatedStorage',0)
    need(type(allocated) is int and 20<=allocated<=1000 and type(maximum) is int and 0<=maximum<=65536,'CATALOG_CAPACITY_SIZE')
    need(db.get('StorageType') in ('gp2','gp3','io1','io2'),'CATALOG_CAPACITY_STORAGE_TYPE')
    counts={'allocated_gib':allocated,'autoscale_maximum_gib':maximum,
            'pending_storage_change':int('AllocatedStorage' in db.get('PendingModifiedValues',{})),
            'free_bytes':metric['counts']['latest_bytes'],'minimum_free_bytes':metric['counts']['window_minimum_bytes'],
            'reserve_bytes':5*1024**3,'sample_epoch':metric['counts']['sample_epoch']}
    return {'status':'CATALOG_CAPACITY_OBSERVED','checks':{'read_only':True,'fresh_metric':True},'counts':counts,
            'codes':['STORAGE_'+db['StorageType'].upper(),'NO_STORAGE_CHANGE_OR_DB_CONNECTION']}


def inspect(api,ctx):
    need(ctx['request_id']==REQUEST,'CATALOG_CAPACITY_REQUEST')
    gate,_=Gate(api['s3']).read()
    need(gate is not None and gate['request_id']==REQUEST and gate['run_id']==RUN and gate['state']=='WORKING','CATALOG_CAPACITY_GATE')
    rows=aws_client('rds').describe_db_instances(DBInstanceIdentifier=DB)['DBInstances']
    need(len(rows)==1,'CATALOG_CAPACITY_INSTANCE_COUNT')
    metric=observe(aws_client('cloudwatch'),datetime.now(timezone.utc))
    return report(rows[0],metric)
