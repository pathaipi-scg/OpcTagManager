import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock
from asyncua import ua
from services.tag_value import TagValueReader, read_attributes_once
from asyncua.ua.ua_binary import struct_to_binary
from asyncua.common.utils import Buffer
from unittest.mock import patch
import OpcTagManager
import test_app

class TagValueTests(unittest.IsolatedAsyncioTestCase):
    async def test_wire_read_uses_explicit_timeout_and_exact_node(self):
        client = MagicMock()
        response = ua.ReadResponse()
        response.Results = [ua.DataValue(ua.Variant(419, ua.VariantType.UInt16)),
                            ua.DataValue(ua.Variant(ua.NodeId(5, 0)))]
        client.uaclient.protocol.send_request = AsyncMock(return_value=Buffer(struct_to_binary(response)))
        node_id = 'ns=2;s=LP2_MODBUS.MIX.USAGE.BatchCnt'
        data, datatype = await read_attributes_once(client, node_id, 5)
        self.assertEqual(data.Value.Value, 419)
        call = client.uaclient.protocol.send_request.call_args
        self.assertEqual(call.kwargs, {'timeout': 5})
        self.assertEqual([v.NodeId.to_string() for v in call.args[0].Parameters.NodesToRead], [node_id, node_id])
        self.assertEqual([v.AttributeId for v in call.args[0].Parameters.NodesToRead],
                         [ua.AttributeIds.Value, ua.AttributeIds.DataType])
        client.uaclient.protocol.send_request.assert_awaited_once()

    def setUp(self):
        self.client = MagicMock()
        self.client.__aenter__ = AsyncMock(return_value=self.client)
        self.client.__aexit__ = AsyncMock(return_value=False)
        self.node = self.client.get_node.return_value
        self.node.read_data_value = AsyncMock(return_value=ua.DataValue(ua.Variant(42)))
        self.factory = MagicMock(return_value=self.client)
        self.reader = TagValueReader('opc.tcp://test', self.factory, timeout=0.05)
        self.client.uaclient.protocol.state.name = 'OPEN'
        self.client.uaclient.session.state.name = 'ACTIVATED'
        async def attributes(*args):
            return [await self.node.read_data_value(raise_on_bad_status=False),
                    ua.DataValue(ua.Variant(ua.NodeId(5, 0)))]
        self.read_patch = patch('services.tag_value.read_attributes_once', side_effect=attributes)
        self.read_patch.start()
        self.addCleanup(self.read_patch.stop)

    async def test_single_read(self):
        result = await self.reader.read('ns=2;s=Selected')
        self.assertTrue(result['success'])
        self.assertEqual(result['value'], '42')
        self.assertEqual(result['quality'], 'Good')
        self.assertIn('+00:00', result['read_at'])
        self.assertTrue(result['connected_at_read'])
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
        self.assertIn('ConnectionError: secret endpoint', result['error'])
        self.assertFalse(result['connected_at_read'])

    async def test_word(self):
        self.node.read_data_value.return_value = ua.DataValue(ua.Variant(419, ua.VariantType.UInt16))
        result = await self.reader.read('ns=2;s=LP2_MODBUS.MIX.USAGE.BatchCnt')
        self.assertTrue(result['success'])
        self.assertEqual(result['value'], '419')
        self.assertEqual(result['data_type'], 'UInt16')
        self.assertEqual(result['status_code'], '0x00000000')

    async def test_wrapped_timeout(self):
        try:
            raise TimeoutError('wire timeout')
        except TimeoutError as cause:
            error = Exception('Unhandled exception while sending request to OPC UA server')
            error.__cause__ = cause
        self.node.read_data_value.side_effect = error
        result = await self.reader.read('ns=2;s=A')
        self.assertEqual(result['category'], 'timeout')
        self.assertIn('TimeoutError: wire timeout', result['error'])

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
