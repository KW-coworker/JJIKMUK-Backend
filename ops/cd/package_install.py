"""Prepare a reviewable main-source install archive. No AWS calls or host installation."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import zipfile
from manifest import digest,require,make_manifest

CLI_NAME='awscli-exe-linux-x86_64-2.39.6.zip'
CLI_SHA='7a121264f2637a3b90767aaf5bdd43ee88b8c925a931d0479fa2ce22b1a2fa76'
WHEEL_NAME='pymysql-1.2.3-py3-none-any.whl'
WHEEL_SHA='14f1c68e2ed859243ae5ca41ffbe677027fc46bc136a9f0be8a4e928e5e7415a'


def formal_main(repo,commit):
    def git(*args):return subprocess.check_output(['git','-C',str(repo),*args],text=True).strip()
    require(re.fullmatch('[a-f0-9]{40}',commit),'INVALID_COMMIT')
    require(git('rev-parse','HEAD')==commit==git('rev-parse','refs/remotes/origin/main'),'FORMAL_MAIN_REQUIRED')
    require(not git('status','--porcelain'),'SOURCE_NOT_CLEAN')
    # A reviewer must refresh origin/main and approve this exact SHA; no fetch here.


def package(repo,dependencies,jar,config_path,commit,output):
    formal_main(repo,commit)
    require(not output.exists(),'OUTPUT_EXISTS')
    config=json.loads(config_path.read_bytes())
    require(config['enabled'] is False,'DISABLED_CONFIG_REQUIRED')
    require('REPLACE_' not in json.dumps(config) and 'REQUIRES_OBSERVATION' not in json.dumps(config),'UNRESOLVED_CONFIG')
    require(digest(dependencies/CLI_NAME)==CLI_SHA and digest(dependencies/WHEEL_NAME)==WHEEL_SHA,'DEPENDENCY_HASH')
    candidate=make_manifest(jar,commit,'1','1')
    files=[]
    with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as out:
        def add(name,data,executable=False):
            require(name not in {x['path'] for x in files},'DUPLICATE_PAYLOAD_FILE')
            out.writestr(name,data)
            files.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'executable':executable})
        add('config.json',config_path.read_bytes())
        for f in sorted((repo/'ops/cd').glob('*.py')):add('bin/'+f.name,f.read_bytes())
        for name in ('install_coordinator.py','private_runner.py','private_plan.py','connection.py','bootstrap.py',
                     'readiness_probe.py','readiness_paths.py','fulltext_definition.py'):
            add('bin/'+name,(repo/'ops/operations'/name).read_bytes())
        add('vendor/'+WHEEL_NAME,(dependencies/WHEEL_NAME).read_bytes())
        with zipfile.ZipFile(dependencies/CLI_NAME) as cli:
            seen=set()
            for i in cli.infolist():
                if not i.filename.startswith('aws/dist/') or i.is_dir():continue
                name=i.filename.removeprefix('aws/dist/');p=PurePosixPath(name)
                require(not p.is_absolute() and '..' not in p.parts and str(p)==name and name not in seen,'CLI_PATH')
                require(not stat.S_ISLNK(i.external_attr>>16),'CLI_SYMLINK')
                seen.add(name);add('tools/aws-cli/'+name,cli.read(i),bool((i.external_attr>>16)&0o111))
        add('releases/'+commit+'-1-1/backend.jar',jar.read_bytes())
        m={'format':1,'repository':'KW-coworker/JJIKMUK-Backend','source_ref':'refs/heads/main','commit':commit,
           'candidate_jar_sha256':candidate['jar_sha256'],'files':files}
        raw=json.dumps(m,sort_keys=True,separators=(',',':')).encode()
        out.writestr('install-manifest.json',raw)
    require(output.stat().st_size<=256*1024*1024,'ARCHIVE_LIMIT')
    return {'archive_sha256':digest(output),'archive_bytes':output.stat().st_size,
            'manifest_sha256':hashlib.sha256(raw).hexdigest(),'commit':commit,'files':len(files)}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--dependencies',required=True);p.add_argument('--jar',required=True)
    p.add_argument('--config',required=True);p.add_argument('--commit',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    try:print(json.dumps(package(Path(__file__).resolve().parents[2],Path(a.dependencies),Path(a.jar),Path(a.config),a.commit,Path(a.output))))
    except Exception:
        print(json.dumps({'status':'PACKAGE_STOPPED_NO_AWS_CALLS'}));raise SystemExit(1)
