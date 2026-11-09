"""Read-only commissioning checks while deployment is OFF; never enroll a baseline."""
import argparse
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True
from deploy import load_config
from host import Host, http_check, secure
from manifest import content_profile, digest, make_manifest, require, validate_manifest


def inspect_disabled(host, candidate, current):
    require(host.config['enabled'] is False, 'DISABLED_PREFLIGHT_ONLY')
    root=host.root
    require(not any((root/n).exists() or (root/n).is_symlink() for n in ('baseline.json','current','current.next')),
            'ALREADY_COMMISSIONED_OR_UNCERTAIN')
    validate_manifest(candidate)
    require(set(current)=={'jar','jar_sha256','argv'},'INITIAL_BASELINE_REQUIRED')
    require(current['argv'][-2:]==['-jar',current['jar']], 'INITIAL_ARGUMENTS_INVALID')
    # The old app JAR need not be root-owned; it is verified against the observed hash.
    require(digest(current['jar'])==current['jar_sha256'], 'INITIAL_JAR_CHANGED')
    old=content_profile(current['jar'])
    require(old['migrations']==candidate['migrations'] and old['configuration']==candidate['configuration'],
            'INITIAL_SCHEMA_OR_CONFIGURATION_CHANGE')
    before=host.protected()
    host.require_protected_references(before)
    def state():
        require(host.unit('ActiveState')=='active','SERVICE_NOT_ACTIVE')
        pid=int(host.unit('MainPID')); require(pid>0,'SERVICE_NO_PID')
        args=[x.decode() for x in Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0') if x]
        require(args==current['argv'],'INITIAL_ARGUMENTS_CHANGED')
        require(Path(f'/proc/{pid}/cwd').resolve()==Path(host.config['working_directory']), 'WORKING_DIRECTORY_CHANGED')
        require('-Dchatbot.developer-test-auto-consent=true' in args,'DEVELOPER_GRANT_DISABLED')
        environment=host.environment(pid,args)
        return (pid,host.identity(),environment)
    initial=state()
    host.database(candidate)
    for check in host.config['health_checks']:http_check(check)
    require(state()==initial and host.protected()==before and digest(current['jar'])==current['jar_sha256'],
            'PREFLIGHT_STATE_CHANGED')
    return {'status':'DISABLED_PREFLIGHT_PASSED','candidate_commit':candidate['commit'],
            'candidate_jar_sha256':candidate['jar_sha256'],'deployment':False,'restarts':0}


def main():
    p=argparse.ArgumentParser();p.add_argument('--commit',required=True);p.add_argument('--expected-jar-sha256',required=True)
    a=p.parse_args()
    import re
    require(re.fullmatch('[0-9a-f]{40}',a.commit) and re.fullmatch('[0-9a-f]{64}',a.expected_jar_sha256),'INVALID_ARTIFACT_IDENTITY')
    config=load_config(require_baseline=False,require_enabled=False)
    root=Path(config['root']);secure(root)
    folder=root/'releases'/(a.commit+'-1-1');secure(folder/'backend.jar')
    m=make_manifest(folder/'backend.jar',a.commit,'1','1')
    require(m['jar_sha256']==a.expected_jar_sha256,'CANDIDATE_HASH_MISMATCH')
    host=Host.__new__(Host);host.config=config;host.root=root
    print(json.dumps(inspect_disabled(host,m,config['initial_runtime'])))


if __name__=='__main__':
    try:main()
    except Exception:
        print(json.dumps({'status':'DISABLED_PREFLIGHT_FAILED_NO_DEPLOYMENT'}));raise SystemExit(1)
