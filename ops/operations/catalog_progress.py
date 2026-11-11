"""Bounded, non-sensitive progress. This never decides whether DB work is safe."""
import json
import os
from pathlib import Path
import re
import time

STAGES={'PREPARING','SERVICE_CHECK','SERVICE_FREEZE','METADATA','VERIFY_ORIGINAL',
        'PRESERVATION','BASELINE','RELEASE_PREPARE','FROZEN','SNAPSHOT_WAIT','SNAPSHOT_READY',
        'PRODUCT_APPLY','PRODUCT_VERIFY','SERVICE_VERIFY','RECOVERY','RECOVERY_VERIFY','DONE','FAILED'}
FIELDS={'format','run_id','commit','archive_sha256','phase','stage','done','total',
        'started_epoch','written_epoch','advanced_epoch','error_code'}


def safe_error(error):
    if isinstance(error,ValueError) and re.fullmatch(r'(CATALOG|REAPPLY|MAINTENANCE|INITIAL|SNAPSHOT|PROGRESS)_[A-Z0-9_]{1,80}',str(error)):
        return str(error)
    response=getattr(error,'response',{})
    detail=response.get('Error',{}) if isinstance(response,dict) else {}
    code=detail.get('Code','') if isinstance(detail,dict) else ''
    if re.fullmatch('[A-Za-z][A-Za-z0-9]{0,70}',code):return 'AWS_'+code.upper()
    name=type(error).__name__.upper()
    return name if re.fullmatch('[A-Z0-9_]{1,100}',name) else 'UNEXPECTED_EXCEPTION'


def valid(value,identity):
    if not isinstance(value,dict) or set(value)!=FIELDS:raise ValueError('PROGRESS_FIELDS')
    if type(value['format']) is not int or value['format']!=1 or any(value[k]!=identity[k] for k in ('run_id','commit','archive_sha256','phase')):
        raise ValueError('PROGRESS_IDENTITY')
    if value['stage'] not in STAGES:raise ValueError('PROGRESS_STAGE')
    for key in ('done','started_epoch','written_epoch','advanced_epoch'):
        if type(value[key]) is not int or not 0<=value[key]<2**53:raise ValueError('PROGRESS_NUMBER')
    if value['total'] is not None and (type(value['total']) is not int or not value['done']<=value['total']<=10_000_000):
        raise ValueError('PROGRESS_TOTAL')
    if value['done']>10_000_000 or not value['started_epoch']<=value['advanced_epoch']<=value['written_epoch']:
        raise ValueError('PROGRESS_ORDER')
    if not isinstance(value['error_code'],str) or not re.fullmatch('[A-Z0-9_]{0,100}',value['error_code']):
        raise ValueError('PROGRESS_ERROR_CODE')
    return value


def identity(binding,phase):
    value={k:binding[k] for k in ('run_id','commit','archive_sha256')};value['phase']=phase
    if not re.fullmatch('[1-9][0-9]{0,19}',value['run_id']) or not re.fullmatch('[a-f0-9]{40}',value['commit']) or not re.fullmatch('[a-f0-9]{64}',value['archive_sha256']) or phase not in ('freeze','apply','recover'):
        raise ValueError('PROGRESS_BINDING')
    return value


def read_fixed(stage,expected):
    """No coordinator lock, SQL, arbitrary paths or free-form log contents."""
    stage=Path(stage)
    if str(stage)!='/opt/jjikmuk-catalog-'+expected['archive_sha256'][:16]:raise ValueError('PROGRESS_PATH')
    path=stage/('progress-'+expected['phase']+'.json')
    for p in (Path('/opt'),stage,path):
        if p.is_symlink():raise ValueError('PROGRESS_OWNER')
        if not p.exists():return None
        s=p.lstat()
        if p.is_symlink() or s.st_uid!=0 or s.st_mode&0o022:raise ValueError('PROGRESS_OWNER')
    if not path.is_file() or path.stat().st_size>8192:raise ValueError('PROGRESS_SIZE')
    raw=path.read_bytes()
    if len(raw)>8192:raise ValueError('PROGRESS_SIZE')
    return valid(json.loads(raw),expected)


class Progress:
    def __init__(self,stage,binding,phase,*,clock=time.time):
        self.identity=identity(binding,phase);self.clock=clock
        self.path=Path(stage)/('progress-'+phase+'.json');self.last_write=0;self.failed=False
        now=int(clock())
        self.value={'format':1,**self.identity,'stage':'PREPARING','done':0,'total':None,
                    'started_epoch':now,'written_epoch':now,'advanced_epoch':now,'error_code':''}
        self.update('PREPARING')

    def update(self,stage=None,done=None,total=None,error_code=''):
        try:
            now=int(self.clock());changed=False;urgent=False
            if stage is not None:
                row={'stage':stage,'done':0 if done is None else done,'total':total,'error_code':error_code}
                changed=any(self.value[k]!=v for k,v in row.items())
                urgent=self.value['stage']!=stage or self.value['error_code']!=error_code
                self.value.update(row)
            if changed:self.value['advanced_epoch']=now
            self.value['written_epoch']=now
            valid(self.value,self.identity)
            if not urgent and self.last_write and now-self.last_write<10:return
            temporary=self.path.with_suffix('.tmp')
            fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|getattr(os,'O_NOFOLLOW',0),0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(self.value,stream,separators=(',',':'));stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,self.path);os.chmod(self.path,0o600);self.last_write=now
        except Exception:
            self.failed=True  # Display failure must not interrupt a DB commit or recovery.
