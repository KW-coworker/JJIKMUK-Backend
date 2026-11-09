import unittest
from oidc_precheck import validate_claims


class OidcTests(unittest.TestCase):
    def test_exact_identity_and_context_without_exposing_token(self):
        claims={'iss':'https://token.actions.githubusercontent.com','aud':'sts.amazonaws.com',
            'sub':'repo:KW-coworker/JJIKMUK-Backend:environment:production','repository_id':'1300060655',
            'ref':'refs/heads/main','sha':'a'*40,'run_id':'123','other_secret':'DO_NOT_RETURN'}
        env={'GITHUB_SHA':'a'*40,'GITHUB_RUN_ID':'123'}
        self.assertNotIn('DO_NOT_RETURN',str(validate_claims(claims,env)))
        for key in ('iss','aud','sub','repository_id','ref','sha','run_id'):
            bad=dict(claims);bad[key]='other'
            with self.assertRaises(ValueError):validate_claims(bad,env)


if __name__=='__main__':unittest.main()
