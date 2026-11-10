"""Build exact main, install disabled, switch once, and collect verified recovery."""
import hashlib,json,os,sys,urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cd'))
from bootstrap import need
from connection import REPO,ACCOUNT,BUCKET,HOSTS,canonical,sha
from run import context,clients,execute,collect,save_local
from package_install import package,CLI_NAME,CLI_SHA,WHEEL_NAME,WHEEL_SHA
from initial_contract import config
from initial_db_runner import check_database,aws_client,WHEEL_URL
from bootstrap_document import document as install_document
from initial_activation_document import document as activation_document

WORKFLOW=REPO+'/.github/workflows/backend-initial-activation.yml@refs/heads/main'
FOLDER=Path('build/initial-cd')


def validate_context():
    ctx=context(os.environ['EXPECTED_SHA'],True)
    need(os.environ.get('GITHUB_WORKFLOW_REF')==WORKFLOW and os.environ.get('CD_ENABLED')=='false',
         'INITIAL_ACTIVATION_WORKFLOW_ONLY_CD_DISABLED')
    return ctx


def download(url,target,expected,limit):
    h=hashlib.sha256();size=0
    with urllib.request.urlopen(url,timeout=60) as response,target.open('xb') as output:
        need(response.url==url,'INITIAL_DEPENDENCY_REDIRECT')
        while True:
            raw=response.read(1024**2)
            if not raw:break
            size+=len(raw);need(size<=limit,'INITIAL_DEPENDENCY_SIZE')
            h.update(raw);output.write(raw)
    need(h.hexdigest()==expected,'INITIAL_DEPENDENCY_HASH')


def prepare():
    ctx=validate_context();repo=Path.cwd();FOLDER.mkdir()
    dependencies=FOLDER/'dependencies';dependencies.mkdir()
    download('https://awscli.amazonaws.com/'+CLI_NAME,dependencies/CLI_NAME,CLI_SHA,128*1024**2)
    download(WHEEL_URL,dependencies/WHEEL_NAME,WHEEL_SHA,46740)
    settings=FOLDER/'config.json';settings.write_bytes(canonical(config()))
    jars=[p for p in (repo/'build/libs').glob('*.jar') if not p.name.endswith('-plain.jar')]
    need(len(jars)==1,'ONE_BOOT_JAR_REQUIRED')
    result=package(repo,dependencies,jars[0],settings,ctx['commit'],FOLDER/'payload.zip')
    result['jar_sha256']=sha(jars[0].read_bytes())
    result['installer_sha256']=sha((repo/'ops/cd/install_disabled.py').read_bytes())
    (FOLDER/'package.json').write_bytes(canonical(result))
    print('EXACT_MAIN_INSTALL_PACKAGE_PREPARED_NO_AWS_CHANGES')


def run_phases(phase):
    installed=phase('install');need(installed.get('success'),'INITIAL_DISABLED_INSTALL_FAILED_KEEP_FILES')
    result=phase('activate')
    if result.get('success'):return result
    if result.get('report',{}).get('status')=='ROLLED_BACK':
        raise ValueError('INITIAL_BACKEND_ROLLED_BACK')
    recovered=phase('recover')
    need(recovered.get('report',{}).get('status')=='ROLLED_BACK','INITIAL_BACKEND_RECOVERY_REQUIRES_REVIEW')
    raise ValueError('INITIAL_BACKEND_ROLLED_BACK')


def check_phase_context(ctx,name):
    need(name in ('install','activate','recover'),'INITIAL_PHASE_REJECTED')
    # A newer main blocks a new switch, but cannot block recovery of the already
    # pinned payload, request and host state from the original process.
    if name!='recover':need(validate_context()==ctx,'INITIAL_CONTEXT_CHANGED')


def main():
    ctx=validate_context();api=clients(True)
    save_local('rds-preflight.json',check_database(aws_client('rds')))
    meta=json.loads((FOLDER/'package.json').read_bytes());archive=FOLDER/'payload.zip'
    need(meta['commit']==ctx['commit'] and sha(archive.read_bytes())==meta['archive_sha256'],
         'INITIAL_PACKAGE_CHANGED')
    key='operations/bootstrap/'+meta['archive_sha256']+'/payload.zip'
    save_local('package.json',meta)
    api['s3'].put_object(Bucket=BUCKET,Key=key,Body=archive.read_bytes(),ServerSideEncryption='AES256',
        ExpectedBucketOwner=ACCOUNT,IfNoneMatch='*',ContentType='application/zip')
    def phase(name):
        check_phase_context(ctx,name)
        doc=(install_document(BUCKET,key,meta['archive_sha256'],meta['manifest_sha256'],meta['installer_sha256'],ctx['commit'])
             if name=='install' else activation_document(meta,name))
        plan={'format':1,'component':'backend','operation':'install' if name=='install' else 'deploy',
              'approved':True,'approval_id':'USER_SCHEMA_AND_CD_COMPLETION_20261110','document':doc}
        save_local(name+'-plan.json',plan)
        try:
            result=execute(api,ctx,plan,sha(canonical(plan)),HOSTS['backend'],output_prefix=name+'-')
            path=Path('operation-results/'+name+'-result.json')
        except Exception:
            # Find the original command and wait; never resend an uncertain command.
            intent_path=Path('operation-results/'+name+'-intent.json')
            if not intent_path.exists():raise
            intent=json.loads(intent_path.read_bytes())
            result=collect(api,intent['operation_id'],output_prefix=name+'-')
            path=Path('operation-results/'+name+'-collected.json')
        result['report']=json.loads(path.read_bytes()).get('report',{})
        return result
    print(json.dumps(run_phases(phase)))


if __name__=='__main__':
    try:
        if sys.argv[1:] == ['prepare']:prepare()
        elif sys.argv[1:] == ['run']:main()
        else:raise ValueError('INITIAL_RUNNER_MODE')
    except Exception as error:
        import re
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[A-Z][A-Z0-9_]{0,100}',str(error)) else type(error).__name__
        print(json.dumps({'status':'STOPPED_KEEP_RECORDS_NO_REPLAY','code':code}));raise SystemExit(1)
