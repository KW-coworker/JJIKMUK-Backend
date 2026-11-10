"""Fixed institution inputs for the one-time backend commissioning.

No passwords or JDBC URL values belong in this source. They are read on the host.
"""
import copy

OLD_JAR = '/opt/jjikmuk-github/releases/20261103-developer-test-consent/backend.jar'
OLD_SHA = 'e3dc8ec36dca14dd7d9edfde1c6ed5e5a083073d7b6f00e62159af7f8382f2f1'
OLD_ARGV = ['/usr/bin/java', '-Xms128m', '-Xmx768m',
            '-Dchatbot.developer-test-auto-consent=true', '-jar', OLD_JAR]
PROPS = '/home/ubuntu/JJIKMUK-Backend/application-local.properties'
DB_HOST = 'jjikmuk-dev-db.cp22o82i4ex5.ap-northeast-2.rds.amazonaws.com'
DROPIN = '/etc/systemd/system/jjikmuk-backend.service.d/zzzzzzzzz-backend-cd-20261110.conf'
ENV_FILES = [
    '/home/ubuntu/ocr-proxy-secrets/backend.env',
    '/etc/food-chatbot/backend-proxy.env',
    '/etc/food-chatbot/external-ai-proxy-20261015.env',
    '/etc/jjikmuk-institution/backend.env',
    '/etc/jjikmuk-search/fulltext-20261029.env',
    '/etc/jjikmuk-mail/smtp-20261101.env',
]
PUBLIC = 'https://43.203.42.36'
CONFIG = {
    'enabled': False,
    'runtime_contract': {'flyway_enabled': False, 'sql_init_mode': 'never'},
    'root': '/opt/jjikmuk-cd', 'service': 'jjikmuk-backend.service',
    'region': 'ap-northeast-2', 'bucket': 'jjikmuk-operations-076767081522-apne2',
    'prefix': 'artifacts/backend', 'aws': '/opt/jjikmuk-cd/tools/aws-cli/aws',
    'working_directory': '/home/ubuntu/JJIKMUK-Backend',
    'initial_runtime': {'jar': OLD_JAR, 'jar_sha256': OLD_SHA, 'argv': OLD_ARGV},
    'expected_argv': OLD_ARGV[:-1] + ['/opt/jjikmuk-cd/current/backend.jar'],
    'db_python': '/usr/bin/python3.12', 'db_user': 'ubuntu',
    'database': {'properties_file': PROPS, 'host': DB_HOST, 'name': 'jjikmuk',
                 'expected_jdbc_url': 'HOST_ONLY_EXISTING_JDBC',
                 'ca_file': '/opt/food-chatbot/rds-global-bundle.pem'},
    'protected_paths': [
        '/etc/jjikmuk-cd/config.json', '/opt/jjikmuk-cd/bin',
        '/opt/jjikmuk-cd/vendor', '/opt/jjikmuk-cd/tools',
        '/etc/systemd/system/jjikmuk-backend.service',
        '/etc/systemd/system/jjikmuk-backend.service.d', PROPS,
        '/opt/food-chatbot/rds-global-bundle.pem',
    ] + ENV_FILES,
    'health_checks': [
        {'kind': 'local', 'url': 'http://127.0.0.1:8080/api/products/filters', 'status': 200, 'json_data': True},
        {'kind': 'chatbot', 'url': 'http://127.0.0.1:8000/ready', 'status': 200},
        {'kind': 'public', 'url': PUBLIC + '/api/products/filters', 'status': 200, 'json_data': True},
        # Anonymous detail does not record the authenticated user's SCAN history.
        {'kind': 'product', 'url': PUBLIC + '/api/products/id/1', 'status': 200, 'json_data': True},
        {'kind': 'ocr', 'url': 'http://10.76.10.209:8081/health', 'status': 200},
        {'kind': 'anonymous', 'url': PUBLIC + '/api/chat', 'status': 401},
    ],
}


def config():
    return copy.deepcopy(CONFIG)
