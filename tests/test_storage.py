import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import storage


class StorageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.conn = MagicMock()
        self.conn.execute = AsyncMock()
        self.conn.fetchrow = AsyncMock()
        self.conn.transaction.return_value.__aenter__.return_value = self.conn
        self.pool = MagicMock()
        self.pool.acquire.return_value.__aenter__.return_value = self.conn
        self.patcher = patch('storage.get_pool', new_callable=AsyncMock, return_value=self.pool)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    async def test_migration_assigns_existing_codes_to_bancho(self):
        await storage.init_db(self.pool)
        self.conn.execute.assert_any_await("ALTER TABLE link_codes ADD COLUMN IF NOT EXISTS server TEXT NOT NULL DEFAULT 'bancho'")

    async def test_created_code_contains_the_selected_server(self):
        self.conn.fetchrow.return_value = {'code': 'ABCDEFGH'}
        with patch('storage.generate_code', return_value='ABCDEFGH'):
            self.assertEqual(await storage.create_link_code('130', False, server='morasooma'), 'ABCDEFGH')
        query, *arguments = self.conn.fetchrow.await_args.args
        self.assertIn('(code, user_id, is_restrict, server)', query)
        self.assertEqual(arguments, ['ABCDEFGH', '130', False, 'morasooma'])

    async def test_wrong_server_does_not_mark_the_code_used(self):
        self.conn.fetchrow.return_value = None
        self.assertIsNone(await storage.consume_link_code('ABCDEFGH', server='bancho'))
        query, *arguments = self.conn.fetchrow.await_args.args
        self.assertIn('WHERE code = $1 AND server = $2', query)
        self.assertIn('FOR UPDATE', query)
        self.assertEqual(arguments, ['ABCDEFGH', 'bancho'])
        self.assertFalse(any('UPDATE' in call.args[0] for call in self.conn.execute.await_args_list))

    async def test_matching_code_is_consumed_once_under_the_same_server(self):
        self.conn.fetchrow.return_value = {'user_id': '130', 'is_restrict': False, 'used_at': None}
        self.assertEqual(await storage.consume_link_code('ABCDEFGH', 'morasooma'), ('130', False))
        self.conn.execute.assert_any_await('UPDATE link_codes SET used_at = NOW() WHERE code = $1 AND server = $2', 'ABCDEFGH', 'morasooma')
        self.conn.fetchrow.return_value = {'user_id': '130', 'is_restrict': False, 'used_at': 'used'}
        self.assertIsNone(await storage.consume_link_code('ABCDEFGH', 'morasooma'))
