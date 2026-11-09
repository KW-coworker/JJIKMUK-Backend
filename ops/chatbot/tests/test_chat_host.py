from unittest.mock import Mock,patch
import unittest
from chat_host import ChatHost


class HostGates(unittest.TestCase):
    def host(self):
        host=object.__new__(ChatHost)
        host.config={'expected_argv':['python','-B','-m','app.start','--host','127.0.0.1','--port','8000']}
        host.runtime=Mock();host.database=Mock();host.protected=Mock(return_value={'fixed':'hash'});host.source_intact=Mock()
        m={'run_id':'10','runtime_sha256':'runtime','schema_sha256':'schema','rag_sha256':'rag'}
        previous={'manifest':m,'protected':{'fixed':'hash'}}
        candidate={'manifest':dict(m,run_id='11'),'protected':previous['protected']}
        return host,previous,candidate
    def test_schema_change_stops_before_activation_or_database_access(self):
        host,old,new=self.host();new['manifest']['schema_sha256']='new requirement'
        with self.assertRaisesRegex(ValueError,'SCHEMA_CHANGE'):host.preflight(old,new)
        host.database.assert_not_called()
    def test_stale_and_rag_rebuild_start_are_rejected(self):
        host,old,new=self.host();new['manifest']['run_id']='9'
        with self.assertRaisesRegex(ValueError,'STALE'):host.preflight(old,new)
        new['manifest']['run_id']='11';host.config['expected_argv'].append('--rebuild-rag')
        with self.assertRaisesRegex(ValueError,'RAG_START'):host.preflight(old,new)
    def test_rollback_refuses_changed_index_config_or_database(self):
        host,old,new=self.host();host.protected.return_value={'fixed':'changed'}
        with self.assertRaisesRegex(ValueError,'PROTECTED'):host.rollback_preflight(old,new)
        host.database.assert_not_called()
        host.protected.return_value=old['protected'];host.database.side_effect=ValueError('CHATBOT_SCHEMA_MISMATCH')
        with self.assertRaisesRegex(ValueError,'SCHEMA'):host.rollback_preflight(old,new)
