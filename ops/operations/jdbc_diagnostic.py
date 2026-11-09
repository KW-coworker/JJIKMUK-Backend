"""Observe fixed JDBC option names only; no connection, writes or acceptance decision."""
import json
import os
import re
from urllib.parse import parse_qsl, urlsplit

import readiness_probe as probe


def option_report(url):
    target = urlsplit(url.removeprefix('jdbc:'))
    probe.need(url.startswith('jdbc:mysql://') and target.hostname == probe.DB_HOST and
               (target.port or 3306) == 3306 and target.path == '/jjikmuk' and
               not target.username and not target.password and not target.fragment,
               'DATABASE_TARGET_REJECTED')
    pairs = parse_qsl(target.query, keep_blank_values=True, strict_parsing=True,
                     max_num_fields=64)
    counts = {}
    invalid = 0
    names = []
    for key, _ in pairs:
        # Values, entire URLs and malformed names are never reported or hashed.
        if not re.fullmatch('[A-Za-z][A-Za-z0-9_.-]{0,59}', key, flags=re.ASCII):
            invalid += 1
            continue
        names.append(key)
        public = 'jdbc.option.' + key
        counts[public] = counts.get(public, 0) + 1
    counts.update(jdbc_pairs=len(pairs), invalid_option_names=invalid,
                  duplicate_option_names=len(names) - len(set(names)),
                  case_variant_names=len(set(names)) - len({n.lower() for n in names}),
                  database_connections=0, database_queries=0,
                  application_writes=0, service_restarts=0)
    return {'status': 'OK', 'counts': counts,
            'checks': {'deployment_ready': False, 'option_names_complete': invalid == 0,
                       'file_options_only': True},
            'codes': ['OPTION_NAMES_ONLY_NO_DATABASE_CONNECTION',
                      'OBSERVATION_ONLY_NOT_DEPLOYMENT_APPROVAL']}


def observe():
    probe.need(os.geteuid() == 0 and probe.jar_digest() == probe.JAR_SHA, 'RUNNING_JAR_CHANGED')
    state = probe.backend_identity()
    env, _ = probe.environment(state[0])
    raw = probe.read(probe.PROPS, 65536)
    props = probe.properties(raw)
    report = option_report(props.get('spring.datasource.url', ''))
    probe.need(probe.backend_identity() == state and probe.environment(state[0])[0] == env and
               probe.read(probe.PROPS, 65536) == raw and probe.jar_digest() == probe.JAR_SHA,
               'INPUTS_CHANGED_DURING_OBSERVATION')
    report['checks']['observation_stable'] = True
    return report


def main():
    try:
        report = observe()
        raw = json.dumps(report)
        probe.need(len(raw.encode()) <= 12000, 'REPORT_LIMIT')
        print(raw)
    except probe.ProbeStop as error:
        print(json.dumps({'status': 'PREFLIGHT_FAILED', 'codes': [str(error)]}))
    except Exception:
        print('{"status":"PREFLIGHT_FAILED","codes":["JDBC_DIAGNOSTIC_FAILED_DETAILS_WITHHELD"]}')


if __name__ == '__main__':
    main()
