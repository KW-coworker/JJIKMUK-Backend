"""Read exact RDS storage configuration and fresh free space; no changes or SSM."""
from datetime import datetime,timezone
from connection import ACCOUNT,REGION,HOSTS
import re
from bootstrap import need
from maintenance_gate import Gate
from catalog_reapply_contract import REQUEST,RDS_RESERVE_BYTES,RDS_START_BYTES
from catalog_prewrite_retry import RUN
from initial_db_runner import aws_client,DB
from initial_contract import DB_HOST
from storage_metrics import observe


def report(db,metric):
    need(db.get('DBInstanceIdentifier')==DB and db.get('DBInstanceArn')==f'arn:aws:rds:{REGION}:{ACCOUNT}:db:{DB}' and
         db.get('Endpoint',{}).get('Address')==DB_HOST and db.get('Engine')=='mysql' and
         db.get('DBInstanceStatus') in ('available','modifying','storage-optimization') and
         db.get('StorageEncrypted') is True,'CATALOG_CAPACITY_TARGET')
    allocated=db.get('AllocatedStorage');maximum=db.get('MaxAllocatedStorage',0)
    need(type(allocated) is int and 20<=allocated<=1000 and type(maximum) is int and 0<=maximum<=65536,'CATALOG_CAPACITY_SIZE')
    need(db.get('StorageType') in ('gp2','gp3','io1','io2'),'CATALOG_CAPACITY_STORAGE_TYPE')
    counts={'allocated_gib':allocated,'autoscale_maximum_gib':maximum,
            'pending_storage_change':int('AllocatedStorage' in db.get('PendingModifiedValues',{})),
            'free_bytes':metric['counts']['latest_bytes'],'minimum_free_bytes':metric['counts']['window_minimum_bytes'],
            'reserve_bytes':RDS_RESERVE_BYTES,'starting_required_bytes':RDS_START_BYTES,
            'sample_epoch':metric['counts']['sample_epoch']}
    return {'status':'CATALOG_CAPACITY_OBSERVED','checks':{'read_only':True,'fresh_metric':True,
            'database_available':db['DBInstanceStatus']=='available'},'counts':counts,
            'codes':['STORAGE_'+db['StorageType'].upper(),'RDS_STATUS_'+db['DBInstanceStatus'].upper(),
                     'NO_STORAGE_CHANGE_OR_DB_CONNECTION']}


def inspect(api,ctx):
    need(ctx['request_id']==REQUEST,'CATALOG_CAPACITY_REQUEST')
    gate,_=Gate(api['s3']).read()
    need(gate is not None and gate['request_id']==REQUEST and gate['run_id']==RUN and gate['state']=='WORKING','CATALOG_CAPACITY_GATE')
    rows=aws_client('rds').describe_db_instances(DBInstanceIdentifier=DB)['DBInstances']
    need(len(rows)==1,'CATALOG_CAPACITY_INSTANCE_COUNT')
    metric=observe(aws_client('cloudwatch'),datetime.now(timezone.utc))
    result=report(rows[0],metric)
    host=root_volume(ec2_client())
    result['counts'].update(host['counts']);result['codes'].extend(host['codes'])
    return result


def ec2_client():
    import boto3
    from botocore.config import Config
    return boto3.client('ec2',region_name=REGION,
        config=Config(connect_timeout=10,read_timeout=30,retries={'total_max_attempts':1}))


def root_volume(ec2):
    """Observe the attached backend root volume; never change EBS or the host."""
    response=ec2.describe_instances(InstanceIds=[HOSTS['backend']])
    instances=[i for r in response['Reservations'] for i in r['Instances']]
    need(len(instances)==1 and instances[0]['InstanceId']==HOSTS['backend'] and
         instances[0].get('RootDeviceType')=='ebs','CATALOG_HOST_INSTANCE')
    instance=instances[0];root=instance['RootDeviceName']
    devices=[d for d in instance.get('BlockDeviceMappings',[]) if d['DeviceName']==root]
    need(len(devices)==1,'CATALOG_HOST_ROOT_MAPPING')
    volume_id=devices[0]['Ebs']['VolumeId']
    need(re.fullmatch(r'vol-(?:[a-f0-9]{8}|[a-f0-9]{17})',volume_id),'CATALOG_HOST_VOLUME_ID')
    volumes=ec2.describe_volumes(VolumeIds=[volume_id])['Volumes']
    need(len(volumes)==1 and volumes[0]['VolumeId']==volume_id,'CATALOG_HOST_VOLUME')
    volume=volumes[0];attached=volume.get('Attachments',[])
    need(volume.get('State')=='in-use' and len(attached)==1 and attached[0]['InstanceId']==HOSTS['backend']
         and attached[0]['Device']==root and attached[0]['State']=='attached','CATALOG_HOST_ATTACHMENT')
    need(type(volume.get('Size')) is int and 8<=volume['Size']<=1024 and
         volume.get('VolumeType') in ('gp2','gp3','io1','io2'),'CATALOG_HOST_VOLUME_SIZE')
    return {'counts':{'host_root_allocated_gib':volume['Size']},
            'codes':['HOST_ROOT_'+volume_id.replace('-','_').upper(),'HOST_ROOT_STORAGE_'+volume['VolumeType'].upper()]}
