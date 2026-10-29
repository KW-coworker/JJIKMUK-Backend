"""Anonymous GET-only staging probe. No login, deployment or mutating HTTP requests.
Server-side access/search logging may still occur when a GET reaches the server.
"""
import argparse
import hashlib
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HOST='https://jjikmuk-backend-dev.tail198441.ts.net'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True);args=parser.parse_args()
    result={'checkedAt':datetime.now(timezone.utc).isoformat(),'baseUrl':HOST,'scope':'ANONYMOUS_GET_ONLY',
            'deploymentChanged':False,'authenticatedRequests':0,'checks':[]}
    paths=['/api/products/filters','/api/products/classifications',
           '/api/products/search?'+urllib.parse.urlencode({'keyword':'두유','analysisMode':'none'}),
           '/api/products/safe-recommendations?analysisMode=none&limit=1','/api/users/me']
    first_barcode=None
    for path in paths:
        started=time.monotonic();entry={'method':'GET','path':path}
        try:
            req=urllib.request.Request(HOST+path,headers={'Accept':'application/json','User-Agent':'JJIKMUK-read-only-contract-audit'},method='GET')
            try:response=urllib.request.urlopen(req,timeout=10)
            except urllib.error.HTTPError as e:response=e
            with response:
                raw=response.read(2*1024*1024)
                entry.update(status=response.status,bodySha256=hashlib.sha256(raw).hexdigest(),
                  versionHeaders={k:v for k,v in response.headers.items() if k.lower() in ['x-app-version','x-build-sha','x-git-commit','x-release-version']})
                try:
                    data=json.loads(raw);entry['topLevelKeys']=list(data) if isinstance(data,dict) else None
                    if path.startswith('/api/products/filters') or path.startswith('/api/products/classifications'):
                        entry['catalog']=data
                    elif path.startswith('/api/products/search'):
                        entries=data.get('data',[]) if isinstance(data,dict) else []
                        entry['returnedCount']=len(entries) if isinstance(entries,list) else None
                        if isinstance(entries,list) and entries:
                            sample=entries[0];product=sample.get('product',{})
                            first_barcode=product.get('barcode')
                            entry['sample']={'itemKeys':list(sample),'barcode':first_barcode,'productName':product.get('productName'),
                              'analysis':sample.get('analysis'),'analysisSelection':sample.get('analysisSelection')}
                    else:entry['errorCode']=data.get('code');entry['message']=data.get('message')
                except (ValueError,AttributeError):entry['responseIsJson']=False
        except (urllib.error.URLError,TimeoutError,OSError) as e:
            entry['networkError']=str(e);result['checks'].append(entry);break
        entry['elapsedMs']=round((time.monotonic()-started)*1000);result['checks'].append(entry)
        if first_barcode and not any('/variants?' in p for p in paths):
            paths.append('/api/products/'+urllib.parse.quote(first_barcode,safe='')+'/variants?analysisMode=none')
    result['exactDeployedCommit']='UNVERIFIABLE_WITHOUT_RELEASE_METADATA'
    out=Path(args.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'checks':[{k:v for k,v in c.items() if k in ['method','path','status','networkError','elapsedMs']} for c in result['checks']]},ensure_ascii=False))

if __name__=='__main__':main()
