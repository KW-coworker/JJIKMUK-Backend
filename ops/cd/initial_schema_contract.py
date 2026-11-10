"""Exact V18/V20 columns, indexes and foreign keys from the approved SQL."""
from manifest import require

# name, SQL type, nullable, default, extra
COLUMNS = {
    'chat_conversations': [
        ('id', 'bigint', 'NO', None, 'auto_increment'), ('owner_id', 'bigint', 'NO', None, ''),
        ('client_conversation_id', 'varchar(36)', 'NO', None, ''), ('title', 'varchar(100)', 'NO', None, ''),
        ('active_turn_id', 'bigint', 'YES', None, ''), ('created_at', 'datetime(6)', 'NO', None, ''),
        ('updated_at', 'datetime(6)', 'NO', None, '')],
    'chat_turns': [
        ('id', 'bigint', 'NO', None, 'auto_increment'), ('conversation_id', 'bigint', 'NO', None, ''),
        ('client_message_id', 'varchar(36)', 'NO', None, ''), ('request_hash', 'varchar(64)', 'NO', None, ''),
        ('context_hash', 'varchar(64)', 'NO', None, ''), ('message', 'text', 'NO', None, ''),
        ('barcode', 'varchar(255)', 'YES', None, ''), ('status', 'varchar(16)', 'NO', None, ''),
        ('response_body', 'longtext', 'YES', None, ''), ('error_code', 'varchar(80)', 'YES', None, ''),
        ('created_at', 'datetime(6)', 'NO', None, ''), ('completed_at', 'datetime(6)', 'YES', None, ''),
        ('expires_at', 'datetime(6)', 'NO', None, '')],
    'account_analysis_selections': [('owner_id', 'bigint', 'NO', None, ''),
        ('include_self', 'tinyint(1)', 'NO', '1', ''), ('version', 'bigint', 'NO', '0', '')],
    'account_analysis_selection_families': [('owner_id', 'bigint', 'NO', None, ''),
        ('family_profile_id', 'bigint', 'NO', None, '')],
}
INDEXES = {
    'chat_conversations': [('PRIMARY', 0, ['id']),
        ('uk_chat_conversation_owner_client', 0, ['owner_id', 'client_conversation_id']),
        ('idx_chat_conversation_owner_updated', 1, ['owner_id', 'updated_at', 'id'])],
    'chat_turns': [('PRIMARY', 0, ['id']),
        ('uk_chat_turn_conversation_client', 0, ['conversation_id', 'client_message_id']),
        ('idx_chat_turn_conversation_id', 1, ['conversation_id', 'id']),
        ('idx_chat_turn_context', 1, ['conversation_id', 'context_hash', 'status', 'id'])],
    'account_analysis_selections': [('PRIMARY', 0, ['owner_id'])],
    'account_analysis_selection_families': [('PRIMARY', 0, ['owner_id', 'family_profile_id']),
        ('fk_analysis_selected_family', 1, ['family_profile_id'])],
}
FOREIGN_KEYS = [
    ('chat_conversations', 'fk_chat_conversation_owner', 'owner_id', 'users', 'id'),
    ('chat_turns', 'fk_chat_turn_conversation', 'conversation_id', 'chat_conversations', 'id'),
    ('account_analysis_selections', 'fk_analysis_selection_owner', 'owner_id', 'users', 'id'),
    ('account_analysis_selection_families', 'fk_analysis_selected_settings', 'owner_id', 'account_analysis_selections', 'owner_id'),
    ('account_analysis_selection_families', 'fk_analysis_selected_family', 'family_profile_id', 'family_profiles', 'id'),
]


def verify_new_tables(metadata):
    actual = {}
    for row in metadata['columns']:
        table, name, ordinal, kind, nullable, _, default, extra = row
        if table in COLUMNS:
            actual.setdefault(table, []).append((ordinal, name, kind, nullable, default, extra))
    expected = {table: [(i, *row) for i, row in enumerate(rows, 1)] for table, rows in COLUMNS.items()}
    require({t: sorted(rows) for t, rows in actual.items()} == expected, 'NEW_TABLE_COLUMNS_MISMATCH')
    indexes = {tuple(row) for row in metadata['indexes'] if row[0] in COLUMNS}
    expected_indexes = {(table, name, non_unique, i, column, None, 'BTREE')
        for table, rows in INDEXES.items() for name, non_unique, columns in rows
        for i, column in enumerate(columns, 1)}
    require(indexes == expected_indexes, 'NEW_TABLE_INDEXES_MISMATCH')
    foreign_keys = []
    for table, name, ordinal, column, target_schema, target_table, target_column, update, delete in metadata['foreign_keys']:
        if table in COLUMNS:
            require(ordinal == 1 and target_schema == 'jjikmuk' and update in ('RESTRICT', 'NO ACTION')
                    and delete == 'CASCADE', 'NEW_FOREIGN_KEY_RULE_MISMATCH')
            foreign_keys.append((table, name, column, target_table, target_column))
    require(sorted(foreign_keys) == sorted(FOREIGN_KEYS), 'NEW_FOREIGN_KEYS_MISMATCH')
