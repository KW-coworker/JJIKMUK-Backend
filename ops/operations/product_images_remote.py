"""Embedded fixed SSM loader; immutable staged input, one slice, existing host lock."""
def execute(request):
    import hashlib,json,os,subprocess,sys
    from pathlib import Path
    sys.dont_write_bytecode=True;sys.path.insert(0,'/opt/jjikmuk-cd/bin')
    from coordination import ROOT,locked,secure
    from connection import canonical,sha
    from bootstrap import need
    need(set(request)=={'seed_operation','package_sha256','index','input_sha256'},'IMAGES_REMOTE_FIELDS')
    need(all(type(request[k]) is str and len(request[k])==64 and all(c in '0123456789abcdef' for c in request[k]) for k in ('seed_operation','package_sha256','input_sha256')),'IMAGES_REMOTE_HASHES')
    need(type(request['index']) is int and 0<=request['index']<100,'IMAGES_REMOTE_INDEX')
    stage=ROOT/('private-'+request['seed_operation']);payload=stage/'payload'
    for p in (ROOT,stage,payload,stage/'package.zip'):secure(p)
    def digest(path):
        h=hashlib.sha256()
        with path.open('rb') as f:
            for block in iter(lambda:f.read(1024**2),b''):h.update(block)
        return h.hexdigest()
    need(digest(stage/'package.zip')==request['package_sha256'],'IMAGES_STAGE_ARCHIVE')
    # The archived manifest binds original code/input. Runtime/journals are separate outputs.
    import zipfile
    with zipfile.ZipFile(stage/'package.zip') as z:manifest=json.loads(z.read('package.json'))
    for name,record in manifest['files'].items():
        path=payload/name;secure(path)
        need(path.stat().st_size==record['bytes'],'IMAGES_STAGE_SIZE')
        need(digest(path)==record['sha256'],'IMAGES_STAGE_FILE')
    spec=json.loads((payload/'input.json').read_bytes())
    need(spec['input_sha256']==request['input_sha256'] and request['index']<len(spec['slices']),'IMAGES_STAGE_BINDING')
    seed=json.loads((payload/'result.json').read_bytes())
    need(seed['status']=='VERIFIED' and seed['operation_id']==request['seed_operation'],'IMAGES_STAGE_NOT_VERIFIED')
    operation=sha(canonical(request))
    with locked('db',operation) as guard:
        folder=payload/'slices'/f'{request["index"]:03d}';folder.mkdir(mode=0o700)
        guard.record('MUTATION_INTENT')
        with (folder/'private.log').open('xb') as log:
            os.chmod(log.name,0o600)
            result=subprocess.run(['/usr/bin/python3','-I','-S','-B',str(payload/'operation.py'),'apply',str(request['index'])],
                cwd=folder,stdout=log,stderr=log,timeout=1250,env={'PATH':'/usr/bin:/bin','HOME':'/root','JJIKMUK_OPERATION_ID':operation})
        need(result.returncode==0,'IMAGES_SLICE_FAILED_KEEP_COMPLETED')
        path=folder/'result.json';secure(path);need(path.stat().st_size<=4096,'IMAGES_RESULT_SIZE')
        value=json.loads(path.read_bytes())
        need(value['status']=='VERIFIED' and value['operation_id']==operation and value['checks'] and all(v is True for v in value['checks'].values()),'IMAGES_SLICE_UNVERIFIED')
        guard.record('VERIFIED')
        return {'status':'VERIFIED','checks':value['checks'],'counts':value['counts'],'hashes':{'operation_id':operation}}
