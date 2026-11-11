import hashlib,json,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
import initial_profiles as profiles
from manifest import content_profile


class ProfileTests(unittest.TestCase):
    def test_only_original_v17_v20_can_extend_the_observed_prefix(self):
        resources=Path(__file__).resolve().parents[3]/'src/main/resources'
        original={}
        for p in (resources/'db/migration').glob('V*__*.sql'):
            # The retired initializer accepts only its original V1–V20 scope.
            if int(p.name.split('__')[0][1:])>20:continue
            original['BOOT-INF/classes/db/migration/'+p.name]=p.read_bytes()
        original.update({'META-INF/MANIFEST.MF':b'Main-Class: org.springframework.boot.loader.launch.JarLauncher\n',
            'BOOT-INF/classes/org/jjikmuk/backend/domain/chat/AiChatClient.class':b'chatbot.developer-test-auto-consent',
            profiles.APPLICATION:b'spring.flyway.enabled=true\n',
            'BOOT-INF/classes/application-dev.properties':b'fixture.mode=same\n'})
        old={k:v for k,v in original.items() if not k.startswith(profiles.PREFIX)
             or int(k.split('/V')[1].split('__')[0])<=16}
        def jar(path,files):
            with zipfile.ZipFile(path,'w') as z:
                for name,raw in files.items():z.writestr(name,raw)
        with tempfile.TemporaryDirectory() as folder:
            left=Path(folder)/'old.jar';right=Path(folder)/'new.jar';jar(left,old);jar(right,original)
            profile=content_profile(left)
            expected=hashlib.sha256(json.dumps(profile,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            with patch.object(profiles,'OLD_SHA',profile['jar_sha256']),patch.object(profiles,'OLD_PROFILE',expected):
                self.assertEqual(len(profiles.verify_initial_profiles(left,right)['migrations']),20)
                future=dict(original);future['BOOT-INF/classes/db/migration/V21__future_fixture.sql']=b'SELECT 1;'
                jar(right,future)
                with self.assertRaises(ValueError):profiles.verify_initial_profiles(left,right)
                migration=next(k for k in original if '/V17__' in k)
                prefix=next(k for k in original if '/V1__' in k)
                for key in (migration,prefix,profiles.APPLICATION,'BOOT-INF/classes/application-dev.properties'):
                    changed=dict(original);changed[key]+=b'changed';jar(right,changed)
                    with self.subTest(key=key),self.assertRaises(ValueError):profiles.verify_initial_profiles(left,right)
                changed=dict(original);changed['BOOT-INF/classes/extra.properties']=b'new=value';jar(right,changed)
                with self.assertRaisesRegex(ValueError,'CONFIGURATION_SET'):profiles.verify_initial_profiles(left,right)
                jar(right,original);changed=dict(old);changed[profiles.APPLICATION]+=b'changed';jar(left,changed)
                with self.assertRaisesRegex(ValueError,'OLD_PROFILE'):profiles.verify_initial_profiles(left,right)


if __name__=='__main__':unittest.main()
