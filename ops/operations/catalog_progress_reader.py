"""Short read-only SSM probes observe a running host command without its lock."""
import json,time
from pathlib import Path
from connection import ACCOUNT,HOSTS,canonical,sha
from run import DOCUMENT_PREFIX
from catalog_progress import identity,valid,safe_error


def document(binding,phase):
    expected=identity(binding,phase)
    source=Path(__file__).with_name('catalog_progress.py').read_text(encoding='utf-8')
    stage='/opt/jjikmuk-catalog-'+binding['archive_sha256'][:16]
    code=source+'\nprint(json.dumps({"progress":read_fixed('+repr(stage)+','+repr(expected)+')}))\n'
    return {'schemaVersion':'2.2','description':'Read only fixed catalog progress; no SQL or coordinator lock',
            'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'20',
            'runCommand':["/usr/bin/python3.12 -I -S -B - <<'JJIKMUK_PROGRESS_READ'\n"+code+'JJIKMUK_PROGRESS_READ']}}]}


class Reader:
    def __init__(self,ssm,binding,phase,reporter,*,clock=time.monotonic,sleep=time.sleep):
        self.ssm,self.binding,self.phase,self.reporter=ssm,binding,phase,reporter
        self.clock,self.sleep=clock,sleep;self.expected=identity(binding,phase)
        self.doc=document(binding,phase);self.name=DOCUMENT_PREFIX+sha(canonical(self.doc))
        self.pending=None;self.last=-1000;self.disabled=False;self.closed=False;self.prepared=False;self.previous_stage=None

    def prepare(self):
        try:info=self.ssm.describe_document(Name=self.name)['Document']
        except Exception as error:
            if getattr(error,'response',{}).get('Error',{}).get('Code')!='InvalidDocument':raise
            info=self.ssm.create_document(Name=self.name,Content=canonical(self.doc).decode(),DocumentType='Command',DocumentFormat='JSON')['DocumentDescription']
        actual=self.ssm.get_document(Name=self.name,DocumentVersion='1',DocumentFormat='JSON')
        assert info['Owner']==ACCOUNT and info['LatestVersion']=='1' and json.loads(actual['Content'])==self.doc
        self.hash=info['Hash'];self.prepared=True

    def read_pending(self):
        rows=self.ssm.list_command_invocations(CommandId=self.pending,InstanceId=HOSTS['backend'],Details=True)['CommandInvocations']
        if not rows:return
        assert len(rows)==1
        if rows[0]['Status'] in ('Pending','InProgress','Delayed','Cancelling'):return
        cid=self.pending;self.pending=None
        if rows[0]['Status']!='Success':raise ValueError('PROGRESS_READ_FAILED')
        r=self.ssm.get_command_invocation(CommandId=cid,InstanceId=HOSTS['backend'],PluginName='report')
        assert r['CommandId']==cid and r['InstanceId']==HOSTS['backend'] and r['DocumentName']==self.name
        assert r['Status']=='Success' and r['ResponseCode']==0 and not r['StandardErrorContent']
        raw=r['StandardOutputContent'];assert len(raw)<8192
        result=json.loads(raw);assert set(result)=={'progress'}
        value=result['progress']
        if value is None:return
        valid(value,self.expected)
        self.reporter.emit(value['stage'],done=value['done'],total=value['total'],written=value['written_epoch'],
            advanced=value['advanced_epoch'],error_code=value['error_code'],force=value['stage']!=self.previous_stage)
        self.previous_stage=value['stage']

    def __call__(self,*,send=True):
        if self.closed:return
        try:
            if self.pending:self.read_pending()
            if not send or self.disabled or self.pending or self.clock()-self.last<60:return
            if not self.prepared:self.prepare()
            self.last=self.clock()
            # This observation command is never retried after an uncertain send.
            with (self.reporter.folder/'catalog-progress-reads.jsonl').open('a',encoding='utf-8') as f:
                f.write(json.dumps({'phase':self.phase,'document':self.name,'state':'SEND_INTENT','at':int(time.time())})+'\n')
            result=self.ssm.send_command(InstanceIds=[HOSTS['backend']],DocumentName=self.name,DocumentVersion='1',
                DocumentHash=self.hash,DocumentHashType='Sha256',Parameters={},TimeoutSeconds=120,
                MaxConcurrency='1',MaxErrors='0',CloudWatchOutputConfig={'CloudWatchOutputEnabled':False},
                Comment='jjikmuk-progress:'+self.binding['run_id']+':'+self.phase)
            self.pending=result['Command']['CommandId']
        except Exception as error:
            self.disabled=True;self.reporter.unavailable(error)

    def close(self):
        # Never consume the snapshot/recovery budget waiting for a display read.
        # Its only action is reading one progress file (20s script / 120s delivery).
        # A subsequent host mutation uses Runtime.drain, including any pending read.
        self.closed=True;self.disabled=True
