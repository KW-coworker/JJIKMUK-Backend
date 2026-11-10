"""One fixed, journaled schema preparation on the existing backend host."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys

if __name__ == '__main__':
    source = Path(__file__).resolve()
    assert re.fullmatch('/opt/jjikmuk-initial-[a-f0-9]{16}/bin/initial_db_host.py', str(source))
    for p in [source, *source.parents]:
        s = p.lstat()
        assert not p.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022
    assert os.geteuid() == 0 and sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    sys.path.insert(0, str(source.parent))

from manifest import digest, make_manifest, require
from host import atomic_json, Host, http_check, secure
from initial_contract import config, OLD_ARGV, OLD_SHA, OLD_JAR
import initial_schema as schema
import readiness_probe as probe

JOURNAL_ROOT = Path('/var/lib/jjikmuk-backend-initial-db-stop-proof-20261110')
OBSERVED_PROTECTED = '3524793b8fa9ae80d15ab0e15405828d575e088f6c92f43a8eed58372e68da35'
OBSERVED_ENVIRONMENT = 'ad8ce08a545eb7311ebb39e69af76c0ea8d1e782fe6359eec77d94d004b91e92'
OBSERVED_PROPERTIES = 'f3126204c538099eec347ad1354481c8454e05853e3a83d7f4f7577cf19ae822'


def prepare(stage, binding):
    require(not JOURNAL_ROOT.exists() and not JOURNAL_ROOT.is_symlink(), 'INITIAL_DB_JOURNAL_EXISTS_NO_RETRY')
    require(not Path('/opt/jjikmuk-cd').exists() and not Path('/etc/jjikmuk-cd').exists(),
            'CD_ALREADY_INSTALLED')
    require(not Path('/var/lib/jjikmuk-operations').exists(), 'OPERATIONS_ALREADY_INITIALIZED')
    require(re.fullmatch('[a-f0-9]{40}', binding['commit']) and
            re.fullmatch('[a-f0-9]{64}', binding['jar_sha256']), 'INITIAL_DB_BINDING')
    jar = stage / 'backend.jar'
    candidate = make_manifest(jar, binding['commit'], '1', '1')
    require(candidate['jar_sha256'] == binding['jar_sha256'], 'INITIAL_JAR_CHANGED')
    schema.validate_source(candidate)
    inputs = probe.database_inputs()
    require(probe.jar_digest() == OLD_SHA, 'RUNNING_JAR_CHANGED')
    host = Host.__new__(Host)
    host.config = config()
    host.root = Path(host.config['root'])
    host.config['protected_paths'] = [p for p in host.config['protected_paths']
                                      if not p.startswith(('/opt/jjikmuk-cd', '/etc/jjikmuk-cd'))]
    protected = host.protected()
    host.require_protected_references(protected)
    environment = host.environment(int(inputs[0][0]), OLD_ARGV)
    require(hashlib.sha256(json.dumps(protected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            == OBSERVED_PROTECTED and environment == OBSERVED_ENVIRONMENT
            and hashlib.sha256(inputs[2]).hexdigest() == OBSERVED_PROPERTIES, 'OBSERVED_INPUTS_CHANGED')
    truststore = Path('/opt/food-chatbot/rds-institution-trust.p12')
    probe.trusted_ca()
    secure(truststore)
    require(0 < truststore.stat().st_size < 1024**2, 'JAVA_TRUSTSTORE_SIZE')
    trust_sha = digest(truststore)
    before = schema.metadata(stage)
    schema.verify_schema(candidate, before, False)
    for check in host.config['health_checks']:
        http_check(check)
    probe.unchanged(inputs)
    require(host.protected() == protected and digest(truststore) == trust_sha, 'INITIAL_INPUTS_CHANGED')
    schema.extract_runtime(jar, stage)
    JOURNAL_ROOT.mkdir(mode=0o700)
    os.chmod(JOURNAL_ROOT, 0o700)
    state = {'status': 'PREPARED', 'binding': binding, 'stage': str(stage),
             'protected': protected, 'environment_sha256': environment, 'candidate': candidate}
    state['java_truststore_sha256'] = trust_sha
    atomic_json(JOURNAL_ROOT / 'before-schema.json', before)
    atomic_json(JOURNAL_ROOT / 'state.json', state)
    state['status'] = 'DB_APPLY_INTENT'
    atomic_json(JOURNAL_ROOT / 'state.json', state)
    try:
        schema.apply(stage, inputs[4])
        after = schema.metadata(stage)
        atomic_json(JOURNAL_ROOT / 'after-schema.json', after)
        schema.verify_schema(candidate, after, True)
        schema.verify_preservation(before, after)
        probe.unchanged(inputs)
        require(probe.jar_digest() == OLD_SHA and host.protected() == protected, 'INITIAL_RUNTIME_CHANGED')
        for check in host.config['health_checks']:
            http_check(check)
        probe.unchanged(inputs)
        require(probe.jar_digest() == OLD_SHA and host.protected() == protected
                and digest(truststore) == trust_sha, 'FINAL_INITIAL_RUNTIME_CHANGED')
        state['status'] = 'DB_PREPARED'
        atomic_json(JOURNAL_ROOT / 'state.json', state)
        return {'status': 'SUCCEEDED', 'checks': {'v17_v20_applied': True, 'old_columns_indexes_preserved': True,
                'old_application_unchanged': True, 'free_health_checks_passed': True},
                'counts': {'migrations_applied': 4, 'service_restarts': 0, 'paid_ai_calls': 0},
                'hashes': {'candidate_jar': candidate['jar_sha256'],
                           'before_schema': digest(JOURNAL_ROOT / 'before-schema.json'),
                           'after_schema': digest(JOURNAL_ROOT / 'after-schema.json')}}
    except BaseException:
        state['status'] = 'STOPPED_KEEP_RECORDS_NO_RETRY'
        atomic_json(JOURNAL_ROOT / 'state.json', state)
        raise


if __name__ == '__main__':
    try:
        binding = json.loads(sys.stdin.read(16385))
        print(json.dumps(prepare(Path(__file__).resolve().parents[1], binding)))
    except Exception as error:
        code = str(error) if isinstance(error, ValueError) else type(error).__name__.upper()
        if not re.fullmatch('[A-Z][A-Z0-9_]{0,79}', code):
            code = 'INITIAL_DB_PREPARATION_FAILED'
        print(json.dumps({'status': 'STOPPED', 'codes': [code]}))
