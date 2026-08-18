# Phase 4.11A — Historian Subscription Reliability / Scale Investigation

Date: 2026-08-18

Status: Development validation complete; production cutover not authorized.

## Finding

Both the legacy and initial canonical workers created monitored items one NodeId at a time on one Subscription object. For 1,641 active tags this produced 1,641 sequential OPC requests. During the previous notebook run, construction took long enough for the OPC connection to fail after 501 successes. The installed asyncua 2.0 API supports subscribing a list of nodes in one request and returns a handle or failure StatusCode for each node.

The server grants a 60-second session timeout instead of the requested one hour, but the corrected build completed well inside that grant. No evidence of a 501-tag Kepware limit remained after batching.

## Implementation

- Subscribe in bounded batches; default size is 100 and configurable through `OPC_SUBSCRIPTION_BATCH_SIZE`.
- Preserve one Subscription object and the existing NodeId-to-full-Path identity map.
- Interpret batch results per node so one bad NodeId does not hide healthy successes.
- Categorize failures as bad NodeId, invalid NodeId, timeout, connection lost, server rejection, or other OPC status.
- Treat transport loss as a session failure and rebuild from a new OPC session and reloaded TagMaster snapshot.
- Add `status_change_notification` diagnostics required by asyncua 2.0.
- Report active, requested, subscribed, failed, completeness, batch progress, and total build time separately.
- Do not clear a pending registry generation from a partial rebuild acknowledgement.
- Check stop/rebuild commands between bounded batches for controlled shutdown.

The Influx contract is unchanged: derived `opc_<LINE>` database, full TagMaster Path measurement, `value` field, no tags, no explicit timestamp, and existing normalization.

## Controlled notebook result

- Active/requested: 1,641
- Subscribed: 1,641
- Failed: 0
- Complete: true
- Build duration: 0.688 seconds
- OPC connects: 1
- OPC reconnects/disconnects: 0
- Successful local Influx write events: 649
- Failed local Influx writes: 0
- Clean worker stop: confirmed
- Final canonical worker count: 0
- Supervisor remained disabled

Recent local coverage from this run:

- `opc_LP2`: 440 measurements
- `opc_SCGLS`: 30 measurements
- Field key: `value`
- Influx tag keys: none
- Boolean example normalized to numeric zero: `LP2_SIEMENS/LCC/CollatorRdy`
- Numeric LP2 example: `LP2/MIX/BatchCount`
- Numeric SCGLS example: `SCGLS_LP/LS_LP_IOT/Conv&Water Pump/Conv_CC_Lump_I`

The server still logs that the requested session timeout was revised to 60 seconds. This did not impair the batched build and no status-change warning was emitted.

## Verification

Full OpcTagManager suite: 173 passed.

Production poller, production Influx, production SQL data, production Alarm runtime, Kepware configuration, and MiniPC runtime were not modified. Live cutover remains separately gated by production-server verification and explicit authorization.
