"""Root-owned local CI fixture only: verify the pinned SDK without any AWS call."""
from pathlib import Path
import os
import sys
import tempfile
import zipfile

assert os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site
repo=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(repo/'ops/cd'))
from initial_guard import load_sdk

# Hosted runners can make /opt group-writable. Use the root-owned fixture tree;
# do not weaken the production path ownership check or change the runner's /opt.
with tempfile.TemporaryDirectory(prefix='jjikmuk-sdk-rehearsal-',dir='/root') as folder:
    stage=Path(folder);os.chmod(stage,0o755)
    vendor=stage/'vendor';vendor.mkdir(mode=0o755)
    with zipfile.ZipFile(repo/'build/catalog-maintenance/payload.zip') as archive:
        for name in archive.namelist():
            if name.startswith('vendor/') and (name.endswith('.whl') or name=='vendor/sdk-lock.json'):
                assert len(Path(name).parts)==2
                target=stage/name;target.write_bytes(archive.read(name));os.chmod(target,0o644)
    load_sdk(stage)
    import botocore.session
    session=botocore.session.get_session()
    assert {'GetObject','PutObject'} <= set(session.get_service_model('s3').operation_names)
    assert 'GetCallerIdentity' in session.get_service_model('sts').operation_names
    # A later phase rechecks the extracted files and rejects tampering.
    load_sdk(stage)
    target=stage/'sdk/botocore/__init__.py'
    target.write_bytes(target.read_bytes()+b'\n# synthetic tamper\n')
    try:
        load_sdk(stage)
    except ValueError as error:
        assert str(error)=='INITIAL_SDK_EXPANSION_CHANGED'
    else:
        raise AssertionError('modified SDK accepted')
print('PINNED_ISOLATED_SDK_MODELS_AND_TAMPER_REJECTION_PASSED_NO_AWS_CALLS')
