"""Fixed no-SQL/no-install observation of old runtime and free HTTP checks."""
import hashlib
import json
from pathlib import Path
import re

import readiness_probe as probe
from initial_contract import config, OLD_ARGV, OLD_JAR, OLD_SHA, ENV_FILES
from host import Host, http_check
from manifest import content_profile


def sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def observe(expected):
    inputs = probe.database_inputs()
    probe.need(probe.jar_digest() == OLD_SHA, 'INITIAL_JAR_CHANGED')
    host = Host.__new__(Host)
    host.config = config()
    host.root = Path(host.config['root'])
    host.config['protected_paths'] = [p for p in host.config['protected_paths']
                                      if not p.startswith(('/opt/jjikmuk-cd', '/etc/jjikmuk-cd'))]
    before = host.protected()
    host.require_protected_references(before)
    files = host.unit('EnvironmentFiles')
    probe.need(re.findall(r'(/[^\s]+) \(ignore_errors=(?:yes|no)\)', files) == ENV_FILES,
               'INITIAL_ENV_FILE_SET_CHANGED')
    environment = host.environment(int(inputs[0][0]), OLD_ARGV)
    old = content_profile(OLD_JAR)
    report = {'status': 'OK', 'checks': {}, 'hashes': {}, 'counts': {}, 'codes': []}
    report['hashes'].update(old_profile=sha(old), protected_inputs=sha(before),
                             process_environment=environment, properties=probe.digest(inputs[2]))
    report['counts']['old_migrations'] = len(old['migrations'])
    report['counts']['old_configurations'] = len(old['configuration'])
    report['checks']['old_migrations_are_main_prefix'] = all(x in expected['migrations'] for x in old['migrations'])
    report['checks']['configuration_same_as_main'] = old['configuration'] == expected['configuration']
    for i, (name, value) in enumerate(sorted(old['configuration'].items())):
        report['hashes']['old_config_' + str(i)] = value
        report['hashes']['old_config_path_' + str(i)] = hashlib.sha256(name.encode()).hexdigest()
    for check in host.config['health_checks']:
        try:
            http_check(check)
            report['checks']['health_' + check['kind']] = True
        except Exception:
            report['checks']['health_' + check['kind']] = False
    for name in ('/opt/jjikmuk-cd', '/etc/jjikmuk-cd', '/var/lib/jjikmuk-operations'):
        report['checks'][name.rsplit('/', 1)[1] + '_absent'] = not Path(name).exists()
    probe.unchanged(inputs)
    probe.need(probe.jar_digest() == OLD_SHA and host.protected() == before, 'OBSERVATION_CHANGED')
    report['checks']['observation_stable'] = True
    return report
