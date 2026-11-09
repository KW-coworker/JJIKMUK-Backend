"""Narrow, observed Spring overrides; values never leave the host process."""
import re
from manifest import require

MAIL = {'SPRING_MAIL_USERNAME', 'SPRING_MAIL_PASSWORD'}
DDL = {'SPRING_JPA_HIBERNATE_DDL_AUTO', 'SPRING_JPA_HIBERNATE_DDLAUTO'}
ALLOWED = MAIL | DDL | {'SPRING_FLYWAY_ENABLED', 'SPRING_SQL_INIT_MODE'}


def validate_overrides(values, props, expected):
    require(isinstance(expected,dict) and set(expected)=={'flyway_enabled','sql_init_mode'}
            and type(expected['flyway_enabled']) is bool and expected['sql_init_mode']=='never',
            'UNREVIEWED_RUNTIME_CONTRACT')
    names=[k for k in values if re.sub('[^a-z0-9]','',k.lower()).startswith('spring')]
    require(all(k in ALLOWED for k in names), 'UNSUPPORTED_SPRING_ENV_OVERRIDE')
    require(len([k for k in DDL if k in values])<=1, 'AMBIGUOUS_DDL_OVERRIDE')
    flyway=values.get('SPRING_FLYWAY_ENABLED',props.get('spring.flyway.enabled','true'))
    require(flyway in {'true','false'} and (flyway=='true')==expected['flyway_enabled'],
            'FLYWAY_CONTRACT_CHANGED')
    sql=values.get('SPRING_SQL_INIT_MODE',props.get('spring.sql.init.mode'))
    require(sql=='never', 'SQL_INITIALIZATION_NOT_DISABLED')
    require(all(values[k]=='validate' for k in DDL if k in values), 'DDL_MODE_NOT_VALIDATE')
    # Mail credentials are only retained in the existing full environment hash.
    # They do not authorize datasource/profile/config/other Spring overrides.
    return {'flyway_enabled':flyway=='true','sql_init_mode':'never'}
