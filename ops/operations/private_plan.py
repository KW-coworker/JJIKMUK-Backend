"""Public approval envelope: private OCR/SQL bytes never enter GitHub plans."""
from datetime import datetime,timezone
import base64
import json
import re
from connection import HOSTS,BUCKET,canonical,sha
from bootstrap import need


def validate(envelope):
    need(type(envelope) is dict and set(envelope)=={'format','component','operation','approval_id','request_id',
        'sha256','bytes','version','expires','recovery_sha256'},'PRIVATE_ENVELOPE_SCHEMA')
    need(envelope['format']==1 and envelope['component'] in ('ocr','db','backend','chatbot')
         and envelope['operation'] in ('inspect','install','deploy','verify','rollback'),'PRIVATE_ENVELOPE_SCOPE')
    for key,pattern in [('approval_id','[A-Z0-9][A-Z0-9_-]{7,79}'),('request_id','[a-f0-9]{32}'),
        ('sha256','[a-f0-9]{64}'),('version','[A-Za-z0-9._~+/-]{1,1024}')]:
        need(type(envelope[key]) is str and re.fullmatch(pattern,envelope[key]) and envelope[key]!='null','PRIVATE_ENVELOPE_IDENTITY')
    need(type(envelope['bytes']) is int and 0<envelope['bytes']<=4*1024**3,'PRIVATE_PACKAGE_SIZE')
    need(type(envelope['expires']) is int and 0<envelope['expires']-int(datetime.now(timezone.utc).timestamp())<=86400,'PRIVATE_APPROVAL_EXPIRED')
    recovery=envelope['recovery_sha256']
    need(recovery is None or (type(recovery) is str and re.fullmatch('[a-f0-9]{64}',recovery)),'PRIVATE_RECOVERY_IDENTITY')
    return envelope


def plan(envelope):
    validate(envelope)
    encoded=base64.b64encode(canonical(envelope)).decode()
    root='/opt/jjikmuk-operations' if envelope['component']=='ocr' else '/opt/jjikmuk-cd'
    script="/usr/bin/python3 -B "+root+"/bin/private_runner.py <<'JJIKMUK_PRIVATE_ENVELOPE'\n"+encoded+"\nJJIKMUK_PRIVATE_ENVELOPE"
    return {'format':1,'component':envelope['component'],'operation':envelope['operation'],
        'approval_id':envelope['approval_id'],'approved':True,'document':{'schemaVersion':'2.2',
        'description':'Run only the separately approved immutable private package','parameters':{},
        'mainSteps':[{'action':'aws:runShellScript','name':'report','inputs':{'timeoutSeconds':'1800','runCommand':[script]}}]}}
