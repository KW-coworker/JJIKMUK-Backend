"""Only service reference paths may leave the commissioning probe; never values."""
import re
from pathlib import PurePosixPath


def checked_path(value):
    if not isinstance(value, str) or not re.fullmatch(r'/[A-Za-z0-9_.@+/-]{1,239}', value):
        raise ValueError('READINESS_PATH_REJECTED')
    p = PurePosixPath(value)
    roots = ('/etc/', '/opt/food-chatbot/', '/opt/jjikmuk-github/',
             '/opt/jjikmuk-chatbot/', '/home/ubuntu/JJIKMUK-Backend/', '/usr/', '/lib/')
    if (str(p) != value or '..' in p.parts or not any(value == r[:-1] or value.startswith(r) for r in roots)
            or any(x.lower() in {'.aws', '.ssh', 'local_secrets', 'shadow', 'gshadow'} for x in p.parts)):
        raise ValueError('READINESS_PATH_REJECTED')
    return value


def checked_paths(values):
    if not isinstance(values, dict) or len(values) > 80:
        raise ValueError('READINESS_PATH_LIMIT')
    pattern = r'(backend|chatbot)\.(working_directory|executable|executable_resolved|dotenv|rag_index|rag_docs|fragment|env_[0-9]{1,2}|dropin_[0-9]{1,2})'
    for key, value in values.items():
        if not re.fullmatch(pattern, key):
            raise ValueError('READINESS_PATH_KEY')
        checked_path(value)
    return values
