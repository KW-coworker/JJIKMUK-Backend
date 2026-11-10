"""One-time observed V1-V16 to prepared V1-V20 adoption, never ordinary CD."""
import hashlib
import json
import zipfile
from manifest import content_profile,require
from initial_contract import OLD_SHA
from initial_schema import validate_source

OLD_PROFILE='421149eae6d2b9cc7b33fecef07b08d006db0fe2a9800762233ba533969f3982'
PREFIX='BOOT-INF/classes/db/migration/'
APPLICATION='BOOT-INF/classes/application.properties'


def normalize_lines(raw):
    return raw.replace(b'\r\n',b'\n')


def verify_initial_profiles(old_jar,new_jar):
    old=content_profile(old_jar);new=content_profile(new_jar)
    require(old['jar_sha256']==OLD_SHA and hashlib.sha256(
        json.dumps(old,sort_keys=True,separators=(',',':')).encode()).hexdigest()==OLD_PROFILE,
        'OBSERVED_OLD_PROFILE_CHANGED')
    validate_source(new)
    previous={r['version']:r for r in old['migrations']}
    current={r['version']:r for r in new['migrations']}
    require(set(previous)=={str(i) for i in range(1,17)},'OBSERVED_MIGRATION_PREFIX_CHANGED')
    require(set(old['configuration'])==set(new['configuration']),'INITIAL_CONFIGURATION_SET_CHANGED')
    with zipfile.ZipFile(old_jar) as left,zipfile.ZipFile(new_jar) as right:
        for version,row in previous.items():
            other=current[version]
            require(row['script']==other['script'] and row['checksum']==other['checksum']
                and normalize_lines(left.read(PREFIX+row['script']))==normalize_lines(right.read(PREFIX+other['script'])),
                'INITIAL_ORIGINAL_MIGRATION_CHANGED')
        for name in old['configuration']:
            if name==APPLICATION:
                # Existing profile logic permits only the reviewed grant alias,
                # comments and line ending normalization for application.properties.
                require(old['configuration'][name]==new['configuration'][name],'INITIAL_APP_CONFIGURATION_CHANGED')
            else:
                require(normalize_lines(left.read(name))==normalize_lines(right.read(name)),
                        'INITIAL_PROFILE_CONFIGURATION_CHANGED')
    return new
