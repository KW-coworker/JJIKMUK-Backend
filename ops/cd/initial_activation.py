"""One-time exact-main backend switch after DB preparation; no SQL writes."""
import hashlib,json,os,re,sys,time
from pathlib import Path
sys.dont_write_bytecode=True
if __name__=='__main__':
    source=Path(__file__).absolute()
    assert str(source)=='/opt/jjikmuk-cd/bin/initial_activation.py'
    for path in [source,*source.parents]:
        st=path.lstat()
        assert not path.is_symlink() and st.st_uid==0 and not st.st_mode&0o022
    sys.path.insert(0,str(source.parent))
from manifest import require,digest,make_manifest
from host import Host,atomic_json,secure,http_check,command,read_host_state
from initial_contract import config as expected_config,OLD_JAR,OLD_ARGV,OLD_SHA,DROPIN
from initial_profiles import verify_initial_profiles
from deploy import load_config
from coordination import locked,ROOT as COORDINATOR_ROOT
import initial_maintenance_host as maintenance

ROOT=Path('/opt/jjikmuk-cd')
SETTINGS=Path('/etc/jjikmuk-cd/config.json')
STATE=ROOT/'initial-activation.json'
FAILED=ROOT/'initial-activation-preserved'


def execute_transition(actions):
    actions.preflight()
    actions.intent()
    try:
        actions.configure()
        actions.switch()
        actions.verify()
        actions.enroll()
        actions.complete()
    except BaseException:
        actions.rollback()
        return 'ROLLED_BACK'
    return 'SUCCEEDED'


class Actions:
    def __init__(self,commit,jar_sha,guard,*,recover=False):
        self.commit,self.jar_sha,self.guard=commit,jar_sha,guard
        self.folder=ROOT/'releases'/f'{commit}-1-1'
        secure(self.folder/'backend.jar')
        require(digest(self.folder/'backend.jar')==jar_sha,'INITIAL_CANDIDATE_CHANGED')
        self.manifest=make_manifest(self.folder/'backend.jar',commit,'1','1')
        verify_initial_profiles(Path(OLD_JAR),self.folder/'backend.jar')
        self.prepared=maintenance.private_state()
        require(self.prepared['status']=='DB_PREPARED','INITIAL_DB_NOT_PREPARED')
        self.disabled=expected_config()
        self.config=expected_config()
        self.config['database']['expected_jdbc_url']=maintenance.observed_properties()['spring.datasource.url']
        require(self.config['database']['expected_jdbc_url'].startswith('jdbc:mysql://'),
                'INITIAL_JDBC_UNRESOLVED')
        self.config['enabled']=True
        self.host=Host.__new__(Host);self.host.config=self.config;self.host.root=ROOT
        self.dropin=('[Service]\nExecStart=\nExecStart='+' '.join(self.config['expected_argv'])+'\n').encode()
        if recover:
            self.state=read_host_state(STATE)
            require(self.state['commit']==commit and self.state['jar_sha256']==jar_sha
                    and self.state['status'] in {'SWITCH_INTENT','CONFIGURED','SWITCHED','VERIFIED','BASELINE_WRITTEN','SUCCEEDED'},
                    'INITIAL_RECOVERY_STATE_CHANGED')

    def record(self,status):
        self.state['status']=status
        atomic_json(STATE,self.state)

    def old_runtime(self):
        maintenance.require_inputs(self.prepared)
        before=maintenance.probe.database_inputs()
        old=maintenance.old_host()
        identity=old.identity()
        require(old.environment(int(before[0][0]),OLD_ARGV)==self.prepared['environment_sha256'],
                'INITIAL_OLD_ENVIRONMENT_CHANGED')
        for check in self.config['health_checks']:http_check(check)
        self.host.database(self.manifest)
        maintenance.probe.unchanged(before)
        require(bool(identity) and old.identity()==identity,'INITIAL_OLD_PROCESS_CHANGED')
        return identity

    def verify_old_recovery(self,previous_identity):
        deadline=time.monotonic()+240;healthy_since=None;observed_identity=None
        while True:
            try:
                identity=self.old_runtime()
                require(identity!=previous_identity,'INITIAL_OLD_PROCESS_NOT_RESTARTED')
                if identity!=observed_identity:
                    healthy_since=None;observed_identity=identity
                now=time.monotonic()
                require(now<deadline,'INITIAL_OLD_RECOVERY_HEALTH_FAILED')
                if healthy_since is None:healthy_since=now
                if now-healthy_since>=60:return
            except Exception:healthy_since=None
            require(time.monotonic()<deadline,'INITIAL_OLD_RECOVERY_HEALTH_FAILED')
            time.sleep(5)

    def preflight(self):
        require(not STATE.exists() and not STATE.is_symlink() and not FAILED.exists()
                and not FAILED.is_symlink(),'INITIAL_TRANSITION_ALREADY_RECORDED')
        for path in (ROOT/'baseline.json',ROOT/'current',ROOT/'current.next',Path(DROPIN)):
            require(not path.exists() and not path.is_symlink(),'INITIAL_TRANSITION_TARGET_EXISTS')
        require(load_config(require_baseline=False,require_enabled=False)==self.disabled,
                'INITIAL_DISABLED_CONFIG_CHANGED')
        secure(Path(DROPIN).parent)
        self.old_runtime()
        self.old_identity=maintenance.old_host().identity()
        self.state={'commit':self.commit,'jar_sha256':self.jar_sha,'old_identity':self.old_identity,
            'db_preparation_sha256':digest(maintenance.JOURNAL_ROOT/'state.json')}

    def intent(self):
        self.guard.record('SWITCH_INTENT')
        self.record('SWITCH_INTENT')

    def configure(self):
        atomic_json(SETTINGS,self.config)
        self.record('CONFIGURED')

    def switch(self):
        with Path(DROPIN).open('xb') as stream:
            stream.write(self.dropin);stream.flush();os.fsync(stream.fileno())
        os.chmod(DROPIN,0o644)
        atomic_json(self.folder/'manifest.json',self.manifest)
        self.release={'manifest':self.manifest,'protected':self.host.protected(),
            'environment_sha256':self.prepared['environment_sha256']}
        self.host.activate(self.release)
        command(['systemctl','daemon-reload'])
        self.host.restart()
        self.record('SWITCHED')

    def verify(self):
        self.host.verify(self.release,self.old_identity)
        require(maintenance.chatbot_runtime()==self.prepared['chatbot_runtime'],
                'INITIAL_CHATBOT_RUNTIME_CHANGED')
        self.record('VERIFIED')

    def enroll(self):
        require(not (ROOT/'baseline.json').exists(),'INITIAL_BASELINE_ALREADY_EXISTS')
        self.host.commit(self.release)
        self.record('BASELINE_WRITTEN')

    def complete(self):
        self.record('SUCCEEDED')
        self.guard.record('SUCCEEDED')

    def rollback(self):
        self.guard.record('ROLLBACK_INTENT')
        try:
            require(digest(maintenance.JOURNAL_ROOT/'state.json')==self.state['db_preparation_sha256'],
                    'INITIAL_PREPARATION_RECORD_CHANGED')
            require(read_host_state(SETTINGS) in (self.config,self.disabled),'INITIAL_CONFIG_DRIFT')
            require(not FAILED.exists() and not FAILED.is_symlink(),'INITIAL_ROLLBACK_ALREADY_ATTEMPTED')
            FAILED.mkdir(mode=0o700)
            drop=Path(DROPIN)
            if drop.exists() or drop.is_symlink():
                secure(drop);require(drop.read_bytes()==self.dropin,'INITIAL_DROPIN_DRIFT')
                os.replace(drop,FAILED/'dropin.conf')
            baseline=ROOT/'baseline.json'
            if baseline.exists():
                value=read_host_state(baseline)
                require(value['manifest']==self.manifest,'INITIAL_BASELINE_DRIFT')
                os.replace(baseline,FAILED/'baseline.json')
            atomic_json(SETTINGS,self.disabled)
            # Confirm the existing app inputs and DB compatibility before starting it.
            maintenance.require_inputs(self.prepared)
            self.host.database(self.manifest)
            previous_identity=self.host.identity()
            command(['systemctl','daemon-reload'])
            self.host.restart()
            self.verify_old_recovery(previous_identity)
            self.record('ROLLED_BACK')
            self.guard.record('ROLLED_BACK')
        except BaseException:
            try:command(['systemctl','stop',self.config['service']],90)
            finally:
                self.record('MANUAL_RECOVERY_REQUIRED')
                self.guard.record('MANUAL_RECOVERY_REQUIRED')
            raise


def run(commit,jar_sha,*,recover=False):
    require(os.geteuid()==0 and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode,
            'ISOLATED_ROOT_INITIAL_TRANSITION_REQUIRED')
    require(re.fullmatch('[a-f0-9]{40}',commit) and re.fullmatch('[a-f0-9]{64}',jar_sha),
            'INITIAL_TRANSITION_IDENTITY')
    operation=hashlib.sha256(('initial-backend:'+commit+':'+jar_sha).encode()).hexdigest()
    recovery_hash=None
    if recover:
        path=COORDINATOR_ROOT/'state.json';secure(path);raw=path.read_bytes();value=json.loads(raw)
        require(value['operation_id']==operation and value['status'] in
                {'SWITCH_INTENT','MUTATION_INTENT','ROLLBACK_INTENT','SUCCEEDED'},'INITIAL_COORDINATOR_RECOVERY_CHANGED')
        if value['status']!='SUCCEEDED':recovery_hash=hashlib.sha256(raw).hexdigest()
        operation=hashlib.sha256((operation+':recovery').encode()).hexdigest()
    with locked('installation',operation,recovery_sha256=recovery_hash) as guard:
        actions=Actions(commit,jar_sha,guard,recover=recover)
        if recover:
            actions.rollback();status='ROLLED_BACK'
        else:status=execute_transition(actions)
    return {'status':status,'checks':{'database_not_modified':True,'automatic_cd_not_enabled_by_host':True},
        'hashes':{'jar':jar_sha}}


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('activate','recover'))
    p.add_argument('--commit',required=True);p.add_argument('--jar-sha256',required=True)
    a=p.parse_args()
    try:print(json.dumps(run(a.commit,a.jar_sha256,recover=a.mode=='recover')))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,79}',str(error)) else 'INITIAL_TRANSITION_REQUIRES_REVIEW'
        print(json.dumps({'status':'STOPPED','codes':[code]}));raise SystemExit(1)
