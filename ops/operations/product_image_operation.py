"""Entrypoint copied into an approved private package together with input.json."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import zipfile

sys.dont_write_bytecode = True


def main():
    folder = Path(__file__).resolve().parent
    sys.path[:0] = [str(folder), '/opt/jjikmuk-cd/bin']
    from product_image_patch import apply, require, validate
    from database_probe import load_vendor, properties
    from deploy import load_config
    from host import Host, secure
    from manifest import digest

    require(os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site, 'IMAGE_PATCH_RUNTIME')
    signal.alarm(180)
    spec = json.loads((folder/'input.json').read_bytes())
    require(set(spec) == {'items', 'backend_commit', 'codec_class_sha256'}, 'IMAGE_PATCH_SPEC')
    validate(spec['items'])
    require(len(spec['items']) == 1 and spec['items'][0]['product_id'] == 12086 and
            spec['items'][0]['barcode'] == '8801045295206' and
            spec['backend_commit'] == '70dc1a70fff94dd0bee30f34638a15add23c0f26', 'IMAGE_PATCH_APPROVED_TARGET')
    config = load_config()
    host = Host(config)
    require(host.baseline['manifest']['commit'] == spec['backend_commit'], 'IMAGE_PATCH_BACKEND_CHANGED')
    host.runtime(host.baseline)
    identity = host.unit('InvocationID')
    # Reuse the exact application helpers from the running, verified original JAR.
    runtime = folder/'runtime'
    runtime.mkdir(mode=0o700)
    jar = host.release_path(host.baseline)/'backend.jar'
    with zipfile.ZipFile(jar) as archive:
        for info in archive.infolist():
            prefix = 'BOOT-INF/classes/' if info.filename.startswith('BOOT-INF/classes/') and info.filename.endswith('.class') else 'BOOT-INF/lib/' if info.filename.startswith('BOOT-INF/lib/') and info.filename.endswith('.jar') else None
            if prefix is None:
                continue
            name = Path(info.filename.removeprefix(prefix))
            require(not name.is_absolute() and '..' not in name.parts, 'IMAGE_PATCH_JAR_PATH')
            target = runtime/('classes' if prefix == 'BOOT-INF/classes/' else 'lib')/name
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(archive.read(info))
            os.chmod(target, 0o600)
    codec_class = Path('/opt/jjikmuk-catalog-2181e6fd7c0fba39/bin/java/CatalogCodec.class')
    secure(codec_class)
    require(digest(codec_class) == spec['codec_class_sha256'], 'IMAGE_PATCH_CODEC_CLASS')

    def codec(values):
        raw = json.dumps(values, ensure_ascii=False, allow_nan=False).encode()+b'\n'
        require(len(raw) <= 8*1024**2, 'IMAGE_PATCH_CODEC_SIZE')
        result = subprocess.run(['/usr/bin/java', '-Xms32m', '-Xmx192m', '-cp',
            str(runtime/'classes')+':'+str(runtime/'lib/*')+':'+str(codec_class.parent), 'CatalogCodec'],
            input=raw, capture_output=True, timeout=20, cwd='/', env={'PATH':'/usr/bin:/bin', 'LANG':'C.UTF-8'})
        require(result.returncode == 0 and not result.stderr and len(result.stdout) <= 8*1024**2, 'IMAGE_PATCH_CODEC_FAILED')
        return json.loads(result.stdout)

    def save(name, value):
        with (folder/name).open('x', encoding='utf-8') as stream:
            os.chmod(stream.name, 0o600)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        fd = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    db = config['database']
    props = properties(db['properties_file'])
    require(props['spring.datasource.url'] == db['expected_jdbc_url'] and db['name'] == 'jjikmuk' and
            db['host'] == 'jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com', 'IMAGE_PATCH_DATABASE')
    load_vendor()
    import pymysql
    connection = pymysql.connect(host=db['host'], port=3306, database=db['name'],
        user=props['spring.datasource.username'], password=props['spring.datasource.password'],
        ssl_ca=db['ca_file'], ssl_verify_cert=True, ssl_verify_identity=True,
        connect_timeout=5, read_timeout=30, write_timeout=10, autocommit=False, local_infile=False, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor)
    operation = os.environ['JJIKMUK_OPERATION_ID']
    try:
        counts = apply(connection, spec['items'], codec, lambda x: save('before.json', x),
                       lambda x: save('commit-intent.json', x), 'image-patch-'+operation[:32])
    finally:
        if connection.open:
            connection.close()
    require(host.unit('InvocationID') == identity, 'IMAGE_PATCH_SERVICE_RESTARTED')
    host.runtime(host.baseline)
    save('counts.json', counts)
    save('result.json', {'status':'VERIFIED', 'operation_id':operation,
        'checks':{'requested_images_updated':True, 'other_product_fields_unchanged':True,
                  'before_values_saved':True, 'same_service_running':True}})


if __name__ == '__main__':
    main()
