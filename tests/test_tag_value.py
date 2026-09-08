import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from asyncua import ua
from services.tag_value import TagValueReader
from unittest.mock import patch
import OpcTagManager
import test_app

class TagValueTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.__aenter__ = AsyncMock(return_value=self.client)
        self.client.__aexit__ = AsyncMock(return_value=False)
        self.node = self.client.get_node.return_value
        self.node.read_data_value = AsyncMock(return_value=ua.DataValue(ua.Variant(42)))
        self.factory = MagicMock(return_value=self.client)
        self.reader = TagValueReader('opc.tcp://test', self.factory, timeout=0.05)

    async def test_single_read(self):
        result = await self.reader.read('ns=2;s=Selected')
        self.assertTrue(result['success'])
        self.assertEqual(result['value'], '42')
        self.assertEqual(result['quality'], 'Good')
        self.assertIn('+00:00', result['read_at'])
        self.client.get_node.assert_called_once_with('ns=2;s=Selected')
        self.node.read_data_value.assert_awaited_once_with(raise_on_bad_status=False)
        self.client.__aexit__.assert_awaited_once()
        self.assertEqual([c[0] for c in self.node.mock_calls], ['read_data_value'])

    async def test_bad_quality(self):
        self.node.read_data_value.return_value.StatusCode = ua.StatusCode(ua.StatusCodes.BadNoCommunication)
        self.assertEqual((await self.reader.read('ns=2;s=A'))['quality'], 'BadNoCommunication')

    async def test_stale_node(self):
        self.node.read_data_value.return_value.StatusCode = ua.StatusCode(ua.StatusCodes.BadNodeIdUnknown)
        self.assertEqual((await self.reader.read('ns=2;s=A'))['category'], 'invalid_node')

    async def test_invalid_node(self):
        self.assertEqual((await self.reader.read('invalid'))['category'], 'invalid_node')
        self.factory.assert_not_called()

    async def test_disconnected(self):
        self.client.__aenter__.side_effect = ConnectionError('secret endpoint')
        result = await self.reader.read('ns=2;s=A')
        self.assertEqual(result['category'], 'unavailable')
        self.assertNotIn('secret', str(result))

    async def test_timeout(self):
        async def slow(**kwargs):
            await asyncio.sleep(1)
        self.node.read_data_value.side_effect = slow
        self.assertEqual((await self.reader.read('ns=2;s=A'))['category'], 'timeout')
        self.client.__aexit__.assert_awaited_once()


class TagValueRouteTests(unittest.TestCase):
    def test_exact_node(self):
        with patch.object(OpcTagManager.TagValueReader, 'read', new_callable=AsyncMock) as read:
            read.return_value = {'success': True, 'value': '42'}
            status, _ = test_app.OpcTagManagerAppTests.request('POST', '/api/opc-tags/current-value', {'node_id': 'ns=2;s=A'})
            self.assertEqual(status, 200)
            read.assert_awaited_once_with('ns=2;s=A')

    def test_rejects_multiple_nodes_and_write_payload(self):
        for body in ({'node_id': ['ns=2;s=A', 'ns=2;s=B']}, {'node_id': 'ns=2;s=A', 'value': 1}, {'node_id': ''}):
            status, _ = test_app.OpcTagManagerAppTests.request('POST', '/api/opc-tags/current-value', body)
            self.assertEqual(status, 422)
