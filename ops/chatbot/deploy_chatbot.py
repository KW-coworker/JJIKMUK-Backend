"""Fixed installed chatbot deploy entry. No arbitrary shell/path parameters."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,'/opt/jjikmuk-cd/bin')
from coordination import locked
from engine import deploy
from host import secure
from package import need,canonical
from chat_host import ChatHost
from notices import REASONS


def request(env):
    result={}
    for key,name,pattern in [('commit','ReleaseCommit','[a-f0-9]{40}'),('run_id','RunId','[1-9][0-9]{0,19}'),
        ('attempt','RunAttempt','[1-9][0-9]{0,3}'),('archive_sha256','ArchiveSha256','[a-f0-9]{64}'),
        ('archive_version','ArchiveVersion','[A-Za-z0-9._~+/-]{1,1024}'),('manifest_version','ManifestVersion','[A-Za-z0-9._~+/-]{1,1024}')]:
        value=env.get('SSM_'+name,'');need(re.fullmatch(pattern,value) and value!='null','CHATBOT_PARAMETER')
        result[key]=value
    result['run_key']=result['run_id']+'-'+result['attempt']
    return result


def main():
    need(os.geteuid()==0,'ROOT_LINUX_REQUIRED')
    path=Path('/etc/jjikmuk-chatbot-cd/config.json');secure(path)
    c=json.loads(path.read_bytes())
    need(c['enabled'] is True and c['root']=='/opt/jjikmuk-chatbot' and c['service']=='food-chatbot-team.service'
         and c['region']=='ap-northeast-2' and c['bucket']=='jjikmuk-operations-076767081522-apne2','CHATBOT_NOT_COMMISSIONED')
    needed=[str(path),'/opt/jjikmuk-chatbot/bin','/opt/jjikmuk-cd/bin',c['venv'],c['rag_index'],c['rag_documents'],c['database']['properties_file'],c['database']['ca_file']]
    need(all(p in c['protected_paths'] for p in needed),'CHATBOT_PROTECTION_INCOMPLETE')
    need(c['venv'].startswith('/opt/food-chatbot/venv-') and c['db_user'] not in ('','root'),'CHATBOT_RUNTIME_NOT_REVIEWED')
    need({x['kind'] for x in c['health_checks']}>= {'local','public','backend','anonymous'},'CHATBOT_HEALTH_INCOMPLETE')
    need(any(x['url']=='http://127.0.0.1:8000/ready' and x['status']==200 for x in c['health_checks']),'CHATBOT_READY_REQUIRED')
    req=request(os.environ)
    with locked('chatbot',hashlib.sha256(canonical(req)).hexdigest()) as guard:
        host=ChatHost(c);host.coordinator=guard
        try:result=deploy(host,req)
        except Exception as error:
            if guard.status!='PREPARING':raise
            guard.record('REJECTED');result={'status':'REJECTED'}
            host.failure_reason=str(error) if str(error) in REASONS else 'REVIEW_REQUIRED'
        print(json.dumps({'status':result['status'],'reason':getattr(host,'failure_reason','REVIEW_REQUIRED')}))
        return 0 if result['status']=='SUCCEEDED' else 1


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception:
        print(json.dumps({'status':'STOP_REVIEW_REQUIRED'}));raise SystemExit(1)
