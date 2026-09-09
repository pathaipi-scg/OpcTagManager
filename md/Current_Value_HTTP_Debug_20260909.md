# Current Value HTTP and browser investigation

## Reproduced failure and cancelling layer

The actual production endpoint is
`POST http://127.0.0.1:1863/api/opc-tags/current-value`, with JSON body:

```json
{"node_id":"ns=2;s=LP2_MODBUS.MIX.USAGE.BatchCnt"}
```

The production HTTP request reproduced the reported exception after 5.187 seconds:
`Exception: Unhandled exception while sending request to OPC UA server -> TimeoutError -> CancelledError`.
It returned `connected_at_read: true`, no DataValue and no StatusCode.
Another production browser Refresh Value request succeeded in 3.529 seconds,
showing 426 / Good / UInt16. The problem is intermittent.

The remaining cancelling layer was `UASocketProtocol.send_request` in installed
asyncua `client/ua_client.py`, whose `wait_for(_send_request(...), timeout)` still
had the explicit five-second timeout supplied by the preview ReadRequest helper.
This was not the browser's 18-second AbortController, the service's 15-second
outer wait_for, or a FastAPI endpoint timeout. No additional endpoint timeout
middleware was found. Raising Client(timeout) alone cannot override explicitly
supplied request timeouts.

An instrumented HTTP request subsequently returned Good/426 after a 7.035-second
Value read (7.228-second endpoint duration). Another exceeded eight seconds:
session activated at 155 ms, ReadRequest started at 156 ms and failed at 8153 ms;
session cleanup finished at 8186 ms. This trace directly identifies the wire
Value request timeout and rules out session activation on that request.
Eight seconds therefore was also insufficient for every observed request.

## Final prepared change

* One private OPC client/session per user-triggered preview, unchanged ownership.
* Ten-second explicit request timeout; fifteen-second outer lifecycle budget.
* Existing browser timeout remains eighteen seconds.
* Preview-only transport also overrides one-second create/activate/close helper
  defaults. Those helpers were observed in the timing trace, but were not the
  demonstrated Value-read failure.
* Preview health-check interval exceeds the lifecycle budget, preventing its
  independent one-second health read during this one-shot request.
* Secure-channel lifetime and negotiated session lifetime are not request
  timeouts. The session negotiated 60 seconds; this was not the cancelling layer.
* Value and DataType are obtained by one ReadRequest for the exact NodeId.
  MaxAge semantics remain unchanged. No retries, caching or continuous polling.
* Temporary diagnostic fields capture API start, client creation, connection,
  activation, each UA request/effective timeout, read finish/failure, service
  finish and total endpoint duration. Errors identify the failure stage.

No historian, existing subscriptions, alarm_sound or polling code was changed.

## Final HTTP verification (16:39:03 UTC)

The prepared version ran the actual application/API on isolated port 1864 with
`--lifespan off`. This disables startup workers in that test instance, avoiding
a second historian. Its normal registry and Kepware connections were used.

| Field | BatchCnt | Fast comparison ns=0;i=2259 |
| --- | --- | --- |
| Value | 427 | 0 |
| Status | Good / 0x00000000 | Good / 0x00000000 |
| VariantType | UInt16 | Int32 |
| DataType | ns=0;i=5 | ns=0;i=852 |
| Connected at read | true | true |
| Exception | none | none |
| Session activated | 151 ms | 148 ms |
| Read started | 151 ms | 148 ms |
| Read finished | 3894 ms | 177 ms |
| Total endpoint | 3922 ms | 207 ms |

The counter advanced during investigation; values were not hardcoded.

## Deployment boundary

Production port 1863 was exercised both by direct HTTP and by real headless
Chrome navigation through LP2_MODBUS > MIX > USAGE > BatchCnt > Refresh Value.
The prepared version also received HTTP and browser verification on port 1864.
Production reload remains pending: its enabled historian supervisor makes a
restart affect existing subscriptions, so user authorization was requested.
Do not confuse the isolated verification instance with a production deployment.

Twelve Python tests and three JavaScript UI tests pass. Browser verification
script: `D:/AI/verify-preview.cjs`; screenshots: `D:/AI/preview-1863.png` and
`D:/AI/preview-1864.png`.

Ten seconds is a bounded engineering-preview budget, not a guarantee that
Kepware will always respond within it. Longer requests retain stage and timing
details instead of becoming generic unavailable errors.
