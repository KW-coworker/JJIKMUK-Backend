import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import readiness_probe as probe


class ReadinessTlsTests(unittest.TestCase):
    def options(self):
        # Reproduce the option names written by the institution migration tool.
        # This is synthetic configuration, never a copied production URL/password.
        return {
            'serverTimezone': 'Asia/Seoul', 'characterEncoding': 'UTF-8',
            'sslMode': 'VERIFY_IDENTITY',
            'trustCertificateKeyStoreUrl': 'file:/opt/food-chatbot/rds-institution-trust.p12',
            'trustCertificateKeyStoreType': 'PKCS12',
            'trustCertificateKeyStorePassword': 'SYNTHETIC_NOT_A_REAL_SECRET',
            'fallbackToSystemTrustStore': 'false',
        }

    def inputs(self, options, extra=''):
        props = ('spring.datasource.url=jdbc:mysql://' + probe.DB_HOST + ':3306/jjikmuk?'
                 + urlencode(options) + extra + '\nspring.datasource.username=fixture\n'
                 + 'spring.datasource.password=SYNTHETIC_DB_PASSWORD\n').encode()
        with patch.object(probe, 'backend_identity', return_value=('123', b'args', b'1')), \
             patch.object(probe, 'environment', return_value=(b'', {})), \
             patch.object(probe, 'read', return_value=props):
            return probe.database_inputs()

    def test_institution_certificate_options_are_supported_without_connecting(self):
        result = self.inputs(self.options())
        self.assertEqual('fixture', result[4]['spring.datasource.username'])

    def test_observed_batch_option_accepts_only_boolean_values(self):
        # Names match the live diagnostic; every value here is synthetic.
        for value in ('true', 'false', 'TRUE', 'False'):
            with self.subTest(value=value):
                self.inputs(dict(self.options(), rewriteBatchedStatements=value))
        for value in ('', 'arbitrary', 'true;SQL', ' true', '1'):
            with self.subTest(value=value), self.assertRaises(probe.ProbeStop):
                self.inputs(dict(self.options(), rewriteBatchedStatements=value))
        with self.assertRaises(probe.ProbeStop):
            self.inputs(dict(self.options(), rewriteBatchedStatements='true'),
                        '&rewriteBatchedStatements=false')

    def test_unknown_and_duplicate_options_still_stop(self):
        for options, extra in [(dict(self.options(), socketFactory='unreviewed'), ''),
                               (self.options(), '&sslMode=VERIFY_IDENTITY'),
                               (self.options(), '&ssl%4dode=VERIFY_IDENTITY')]:
            with self.subTest(extra=extra), self.assertRaises(probe.ProbeStop):
                self.inputs(options, extra)

    def test_changed_or_incomplete_trust_profile_stops_without_exposing_values(self):
        cases = [('sslMode', 'PREFERRED'), ('sslMode', 'VERIFY_CA'),
                 ('trustCertificateKeyStoreUrl', 'https://unreviewed.invalid/store'),
                 ('trustCertificateKeyStoreUrl', 'file:/tmp/unreviewed.p12'),
                 ('trustCertificateKeyStoreType', 'JKS'),
                 ('fallbackToSystemTrustStore', 'true'),
                 ('trustCertificateKeyStorePassword', ''),
                 ('trustCertificateKeyStorePassword', 'x' * 1025)]
        for key, value in cases:
            with self.subTest(key=key, value=value[:30]), self.assertRaises(probe.ProbeStop) as error:
                self.inputs(dict(self.options(), **{key: value}))
            self.assertNotIn('SYNTHETIC', str(error.exception))
            self.assertNotIn('unreviewed', str(error.exception))
        for key in ('sslMode', 'trustCertificateKeyStoreUrl', 'trustCertificateKeyStoreType',
                    'trustCertificateKeyStorePassword', 'fallbackToSystemTrustStore'):
            options = self.options()
            del options[key]
            with self.subTest(missing=key), self.assertRaises(probe.ProbeStop):
                self.inputs(options)


if __name__ == '__main__':
    unittest.main()
