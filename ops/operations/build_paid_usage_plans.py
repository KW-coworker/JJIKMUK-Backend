"""Generate the two fixed read commands requested by the user on 2026-11-12."""
import json
from pathlib import Path


def plan(kind):
    root = Path(__file__).parent
    source = (root/'paid_usage_probe.py').read_text(encoding='utf-8')
    return {'format':1, 'component':kind, 'operation':'inspect',
            'approval_id':'USER_READ_PAID_USAGE_20261112', 'approved':True,
            'document':{'schemaVersion':'2.2', 'description':'Read current paid call counts only',
                        'parameters':{}, 'mainSteps':[{'action':'aws:runShellScript', 'name':'report',
                        'inputs':{'timeoutSeconds':'60', 'runCommand':[
                            "python3 -I -S -B - <<'JJIKMUK_PAID_USAGE'\n"+source+
                            "\nmain('"+kind+"')\nJJIKMUK_PAID_USAGE"]}}]}}


if __name__ == '__main__':
    for component in ('chatbot','ocr'):
        target = Path(__file__).parent/'plans'/('paid-usage-'+component+'-20261112.json')
        with target.open('x', encoding='utf-8') as output:
            json.dump(plan(component), output, ensure_ascii=False, indent=2)
            output.write('\n')
