# Current Tag Value live verification

Live reads on 2026-09-09 used the configured OPC_URL and repository virtualenv.
No historian/subscription changes or polling were made.

## Root cause

Installed asyncua `UaSession._send_request` defaults to one second, and
`UaSession.read` does not supply a timeout. Setting `Client(timeout=10)` still
failed the target Value read. The outer exception was `Exception: Unhandled
exception while sending request to OPC UA server`, caused by `TimeoutError`
(empty message), caused by `asyncio.exceptions.CancelledError`.
The previous reader discarded this chain and showed generic unavailable text.

The original reader creates a fresh session and awaits activation correctly;
it does not reuse a stale client. The live socket was OPEN and session ACTIVATED.
UInt16 conversion and acceptance of Good responses were not the cause.

## Live results

| Read | Raw value | StatusCode | VariantType | DataType | Connected at read | Exception |
| --- | --- | --- | --- | --- | --- | --- |
| Original target Value read | No response | No response | No response | Separate attribute read: ns=0;i=5 | Yes | Exception -> TimeoutError -> CancelledError |
| Explicit five-second request, target | 419 | Good / 0x00000000 | UInt16 | ns=0;i=5 | Yes | None |
| Updated TagValueReader, target at 16:17:27 UTC | 420 | Good / 0x00000000 | UInt16 | ns=0;i=5 | Yes | None |
| Comparison ns=0;i=2259 (ServerStatus.State) | 0 | Good / 0x00000000 | Int32 | ns=0;i=852 | Yes | None |

Target: `ns=2;s=LP2_MODBUS.MIX.USAGE.BatchCnt`.
The explicit read took 3.437 seconds; the updated reader including session
lifecycle took 2.422 seconds. Counter advancement from 419 to 420 was observed.
The comparison also succeeds using the original reader (verified at 16:17:58 UTC).
It is a server diagnostic node, not a production process tag.

A literal backslash in `ns=2;s=LP2\_MODBUS.MIX.USAGE.BatchCnt` returns
BadNodeIdUnknown. The registered NodeId and successful reads use LP2_MODBUS;
the reader preserves submitted NodeIds exactly, including namespace index 2.

## Change and verification scope

The preview sends one ReadRequest containing Value and DataType attributes of
the exact selected node through its own activated session, explicitly supplying
five seconds to the transport. Total lifecycle budget is fifteen seconds; UI
budget is eighteen seconds. No retries, subscriptions or polling were added.
Bad/Uncertain DataValues now produce named status failures; exceptions retain
their cause chain. UI displays the actual error and returned status code.

Live verification exercised the modified Python reader directly. The running
web process was not restarted and browser interaction was not verified; a running
process must reload this code to use the fix. UI behavior is covered by Node tests.
