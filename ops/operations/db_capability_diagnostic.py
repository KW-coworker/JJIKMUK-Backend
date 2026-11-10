"""Report only bounded capability flags, never grant text or account names."""
import re


def summarize(grants,role,scheduler):
    assert len(grants)<=101 and scheduler in ('ON','OFF','DISABLED')
    known={'PROCESS','TRIGGER','EVENT','SHOW DATABASES'}
    rights={'global':set(),'schema':set()}
    partial_revoke=False
    for text in grants:
        assert isinstance(text,str) and len(text)<=16384
        partial_revoke |= text.startswith('REVOKE ')
        match=re.fullmatch(r'GRANT (.+) ON (\*\.\*|`jjikmuk`\.\*) TO .+',text)
        if match:
            names=set(match[1].split(', '))
            rights['global' if match[2]=='*.*' else 'schema'].update(known if 'ALL PRIVILEGES' in names else known & names)
    checks={'partial_revoke_present':partial_revoke,'role_none':role=='NONE',
            'role_known_rds':role=='`rds_superuser_role`@`%`',
            'event_scheduler_on':scheduler=='ON','event_scheduler_off':scheduler in ('OFF','DISABLED')}
    for scope,names in rights.items():
        for name in sorted(known):checks[scope+'_'+name.lower().replace(' ','_')]=name in names
    return {'status':'OK','checks':checks,'counts':{'grant_rows':len(grants)},
            'codes':['CAPABILITY_NAMES_ONLY_NO_VALUES_NO_DB_MUTATIONS']}
