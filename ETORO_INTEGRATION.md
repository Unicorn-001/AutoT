# eToro market data and Demo Trading V1

**Real-money trading is not enabled in V1.** Configuration accepts only `demo`; the transport uses a fixed eToro host and permits only market-data and explicitly demo trading paths. Manual confirmation is required for each opening or closing intent. There is no scheduled broker execution, WebSocket trading callback, or unattended order loop.

Strategy, ranking, signals, risk thresholds, market-context decisions, Yahoo daily history, and internal paper execution remain unchanged. eToro is an execution-time data source and a separate demo execution record. An HTTP success is an acknowledgement, never evidence of a fill.

## Architecture

```text
Scanner -> existing Yahoo daily history -> frozen strategy / ranking
  |                                        |
  +-> persisted scan                       +-> internal paper intent / ledger
                                                      | read only
Streamlit Broker / eToro Demo -> DemoService -----------+
  |                                 |
  |                      existing fill_risk.recheck + market_context.assess
  |                                 |
  |                     separate broker intent journal (commit before POST)
  |                                 |
  +-> quote provider / resolver     +-> external broker adapter
            |                                 |
            +----------- eToro Client --------+
                       fixed host, demo routes
                                 |
                 REST market data / demo execution
                                 |
                explicit status lookup / reconciliation
                                 |
                   shadow comparison with paper
```

`autot/broker/external.py` declares external broker and quote contracts separately from the older synchronous paper/Alpaca broker interface. `etoro/client.py` owns authentication and HTTP. `etoro/market.py` owns instrument resolution and quotes. `etoro/broker.py` owns demo route mapping. `demo_service.py` orchestrates manual checks, persistence and reconciliation. Streamlit contains no HTTP calls.

The first version mirrors an already-confirmed internal US BUY paper intent. Creating that paper intent remains the existing explicit Paper Trading action. Demo submission reads the ledger using SQLite `mode=ro`; it never creates, updates, closes, or fills paper trades. The real-trade journal is untouched.

## Obtain and configure credentials

1. Sign in to a verified eToro account. Complete account verification if API key management is unavailable.
2. Obtain your application's Public API Key through the [eToro API Portal](https://api-portal.etoro.com/). This is `ETORO_API_KEY`; it is separate from the user key. Application provisioning/availability depends on the portal and account eligibility. Do not use public documentation example credentials.
3. In eToro, open **Settings > Trading > API Key Management > Create New Key**. Give the key a recognizable name, select **Demo**, and choose **Write** for demo execution (read access alone is sufficient only for supported read operations). Configure expiry/IP restrictions as needed.
4. Complete the SMS/phone verification and copy the generated user key into `ETORO_USER_KEY`.
5. Configure the environment of the process that runs AutoT. For the managed service, use its protected environment file; `ops/autot.env.example` supplies empty placeholders. Do not edit the example with actual values, paste keys into the UI, commit secrets, or store them in SQLite.
6. Set `ETORO_TRADING_MODE=demo`. Restart AutoT so the server process receives the environment.

See the official [authentication instructions](https://api-portal.etoro.com/core/getting-started/authentication) and [getting-started FAQ](https://builders.etoro.com/faq). There is no assumption that your current account already has API access.

```dotenv
ETORO_API_KEY=<your-application-public-api-key>
ETORO_USER_KEY=<your-demo-user-key>
ETORO_TRADING_MODE=demo
ETORO_TIMEOUT_SECONDS=10
ETORO_MAX_RETRIES=2
```

The configuration reader uses environment variables only. Existing application startup may load its local `.env`; do not depend on that for service deployment. Existing `.gitignore` already excludes `.env`, `.env.*` except the example, Streamlit secrets, and runtime data; no ignore change was necessary.

Timeout is finite, greater than zero, and at most 60 seconds. Retry count is 0–4. Configuration representations omit keys. Transport failures expose only normalized categories/status codes, never raw headers, bodies or exception messages. Returned credential echoes are redacted before display/persistence; authentication/tracking token fields are discarded.

## Connectivity and quotes

Open **Broker / eToro Demo**. The banner always identifies simulated funds. Configured credentials initially show **authentication unverified**; configuration alone is not an authentication test. Click **Check demo connection / portfolio** to perform a demo account read. Missing keys produce a useful setup message and no API request.

Enter `AAPL`, `NVDA`, or `BE`, then click **Resolve instrument / fetch eToro quote**. Resolution requires one exact symbol match; fuzzy matches and ambiguity fail explicitly. Only non-sensitive symbol, instrument ID, instrument type and exchange ID are cached in memory, for at most one hour per resolver instance. Streamlit reruns can create a new resolver.

The quote mapping is:

| eToro field | AutoT field / use |
| --- | --- |
| resolved `symbol` | symbol |
| `instrumentID` | instrument ID, matched against the resolved ID |
| `bid` | bid; executable SELL reference |
| `ask` | ask; executable BUY reference |
| `lastExecution` | last execution/current trade price, when provided |
| `date` | timezone-aware broker timestamp, or unavailable |
| adapter identity | `source="eToro"` |
| ask minus bid | absolute spread |
| spread / midpoint × 100 | spread percentage |

JSON fractional numbers are parsed as Decimal; normalized prices and persisted fills retain decimal precision. No bid or ask is fabricated from last price or midpoint. If the selected executable side is absent, execution fails. The advisory UI can still use Yahoo explicitly; eToro orders never silently fall back to Yahoo. A missing, future, or older-than-300-second quote blocks demo submission. This is an external execution freshness gate, not a changed strategy eligibility threshold.

Scanner opportunity **Pre-Trade Market Context** now has a Yahoo/eToro provider selector. eToro displays bid, ask, side-specific reference, spread, timestamp and source. The existing `assess` decision thresholds are unchanged. The original provider remains the default, and historical bars remain Yahoo.

## Manual demo opening order

1. Run the existing daily scanner and confirm a qualified US BUY opportunity through Paper Trading. Review its quantity, entry, stop and target using the existing workflow.
2. Open **Broker / eToro Demo**, check connectivity, inspect the quote, and choose the linked internal paper intent.
3. Review the displayed immutable setup and quantity. Check **I explicitly confirm this eToro DEMO order**, then click **Submit confirmed DEMO order**.
4. The service verifies US stock metadata, account eligibility for underlying LONG X1, a fresh ask, the existing AutoT fill-risk validation, and a current market-context result other than REJECT. A risk resize is blocked for review rather than silently changing the confirmed quantity.
5. It independently validates actual tracked broker exposure through the existing risk engine and checks demo credit. Unknown holdings, copied portfolios, pending activity, unresolved submissions and partial executions block new exposure. Use a dedicated demo portfolio for V1 validation.
6. A durable INTENDED record and request UUID are committed before sending. Click **Refresh broker status / reconcile** after submission. Compare the actual fill with the paper fill once both exist.

Opening mapping: `action=open`, `transaction=buy`, `orderType=mkt`, resolved `instrumentId`, integer `units` from the paper intent, `orderCurrency=usd`, `leverage=1`, `settlementType=real`, `stopLossType=fixed`, original `stopLossRate` and `takeProfitRate`. Here **`settlementType=real` means underlying-asset settlement in the DEMO account**, not real-money execution. The route and trading mode remain demo. CFD, margin, futures, options, crypto and opening SELL/short orders are disabled.

LIMIT is disabled. eToro distinguishes market-if-touched and immediate-or-cancel limits; neither is silently relabeled as AutoT LIMIT. Broker-side protective stops/targets are attached to the manually confirmed order; AutoT does not run a broker execution worker.

## Closing and reconciliation

The documented v2 unified endpoint currently opens positions only. V1 closes one fully filled, tracked long position via the separate demo close route. Select the execution, explicitly confirm the close, then click **Close confirmed DEMO position**. Closing verifies demo mode, explicit manual close confirmation, valid tracked position/instrument IDs, and the current long X1 position identity and quantity. It uses only the position-specific full-close route, which cannot open or reverse into a short. Entry market-context decisions (including REJECT/CAUTION), Fill-Time Risk Recheck, scanner eligibility and paper-ledger availability do not gate closing. No quote is required to close; the actual execution price is obtained by reconciliation. The close intent is committed before submission, and an uncertain response is never blindly replayed. Partial/split-position closes are not exposed by this V1 UI.

Click **Refresh demo close status** to capture executed units, exit price and timestamp. Gross realized P&L is calculated from confirmed USD opening/closing units and prices; fees are shown separately. The comparison reports broker minus paper entry, fill timing, quantity, stop/target differences, and gross realized P&L only when both are closed. Unavailable values stay unavailable.

The broker journal lives at `$AUTOT_DATA_DIR/broker/executions.sqlite3`:

- `executions`: `intent_key` primary key, unique `request_id`, unique `paper_trade_id`, JSON `payload`.
- `execution_events`: append-only event ID, intent key, recorded time, JSON payload.
- Payload: scanner run/opportunity references when uniquely recoverable, candidate scan links when ambiguous, paper trade ID, original signal time/timeframe/mode, symbol/side, reference entry/stop/target, intended units/notional, instrument ID, broker order ID, submitted time/status, decimal fill price/time/units/notional, rejection/cancellation reasons, fees, position IDs, quote/context/risk evidence and mapped request.
- Close evidence: close intent UUID/time/SELL side, verified position/instrument IDs and intended quantity, close order ID/status, executed units/price/time, gross P&L and basis.

Older paper snapshots do not contain a scan run ID. V1 searches persisted scans read-only for the exact opportunity and signal time. A unique match is linked; multiple matches remain explicit candidates, and absent provenance stays null. The complete paper signal link is retained in all cases; no run ID is invented.

One demo opening attempt per paper intent is enforced by SQLite uniqueness, across reruns/restarts/processes. Uncertain submissions stay INTENDED/UNKNOWN and block new exposure until reconciled. Lookup can use the opening request UUID if the response was lost. No execution POST is automatically retried, including 429, because the durable intent must be reconciled first. Read requests and the read-only eligibility POST use bounded exponential 429 backoff; large Retry-After values (>30 seconds) are returned for later manual retry instead of holding the UI indefinitely. Every attempted HTTP request has a UUID; the opening execution UUID is durable and sent once.

## Endpoint inventory

Host: `https://public-api.etoro.com`. Standard REST base: `/api/v1/`; documented v2 paths are explicit exceptions.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/v2/market-data/instruments/search` | exact symbol resolution from relevance-ranked results |
| GET | `/api/v1/market-data/exchanges` | verify recognized US stock exchange |
| GET | `/api/v1/market-data/instruments/rates` | current bid/ask/last/timestamp |
| GET | `/api/v1/trading/info/demo/pnl` | demo credit, portfolio and positions |
| POST | `/api/v2/trading/info/demo/eligibility` | read-only underlying LONG X1 eligibility |
| POST | `/api/v2/trading/execution/demo/orders` | manually confirmed MARKET BUY |
| GET | `/api/v2/trading/info/demo/orders:lookup` | opening status/position/fill reconciliation |
| POST | `/api/v1/trading/execution/demo/market-close-orders/positions/{positionId}` | manually confirmed full position close |
| GET | `/api/v1/trading/info/demo/close-orders/{orderId}` | close status/fills |

Contracts were checked against official eToro documentation on 2026-11-24: [rates](https://api-portal.etoro.com/api-reference/market-data/get-instrument-market-rates), [instrument search](https://api-portal.etoro.com/api-reference/market-data/search-instruments-by-free-text-query), [create demo order](https://api-portal.etoro.com/api-reference/trading--demo/create-an-order), [eligibility](https://api-portal.etoro.com/api-reference/trading--demo/check-instrument-trading-eligibility), [order lookup](https://api-portal.etoro.com/api-reference/trading--demo/get-order-information-and-position-details), [close position](https://api-portal.etoro.com/api-reference/trading--demo/close-demo-position-by-units), and [close lookup](https://api-portal.etoro.com/api-reference/trading--demo/get-close-order-information-and-closed-position-details).

## Troubleshooting and limitations

- **401:** verify that both application and user keys are present in the running process, correct and unexpired. Do not paste them into logs or tickets.
- **403:** check Demo environment, account/API availability, permissions and IP restrictions. Configuration cannot grant broker permissions.
- **429:** allow the quota window to reset; reduce manual refreshes. Execution requests are not automatically replayed.
- **Timeout/5xx after submission:** treat execution as UNKNOWN. Refresh/reconcile by stored request ID. Do not create a second paper intent to bypass uncertainty.
- **Lost close response:** the documented close lookup requires a close order ID; inspect the eToro demo account if that ID was lost. AutoT does not guess or resend.
- **No symbol/ambiguous symbol/unknown exchange name:** fail closed. The current exchange allowlist recognizes NASDAQ, NYSE, New York Stock Exchange, NYSE Arca and NYSE American descriptions. Other descriptions require a reviewed mapping, never a guessed ID.
- **Risk resize/context rejection:** review the existing strategy setup; V1 does not optimize or change it to obtain approval.
- **External changes/automatic protective exits:** opening status lookup does not provide a complete closed-trade history. V1's automated gross P&L comparison covers closes submitted and reconciled through this workspace. Externally closed/modified positions and protective exits need direct eToro review; fuller trade-history reconciliation is backlog.
- **Partial fills:** captured accurately but block additional exposure and V1 full-position closing until reviewed. No partial fill is silently promoted to full.
- **Settings/risk:** both paper exposure and broker exposure must pass the existing per-intent settings/risk policy. Broker budgets use AutoT configured capital plus an independent broker-credit check; V1 does not synchronize account capital automatically.
- **Validation:** automated tests are offline fakes only. No credentialed connectivity or demo order has been sent as part of implementation. Account-specific payload acceptance still requires the manual validation above.

## REST decision and V1.1 backlog

On-demand REST is adequate for this daily US-stock swing workflow: fetch at review/submission and manually reconcile. This avoids long-lived Streamlit threads and callback-triggered orders. The official WebSocket URL is `wss://ws.etoro.com/ws`; no WebSocket connection is opened in V1.

V1.1 can add a separate quote-provider worker with bounded reconnect backoff, normalized quote persistence and explicit freshness checks. WebSocket callbacks must never place orders. Other backlog: broader exchange metadata mapping, full closed-trade history/fees, partial and split-position close support, cancellation workflow and a separately reviewed LIMIT/IOC contract.

## Offline validation

Run focused checks first:

```sh
venv/bin/python -m pytest tests/test_etoro.py tests/test_market_context.py tests/test_market_context_quotes.py tests/test_market_context_web.py tests/test_fill_time_risk.py -q
venv/bin/python -m pytest -q
```

`tests/test_etoro.py` disables real requests by default and injects fake transports. Coverage includes headers, UUID uniqueness, redaction, retry/timeouts, symbol ambiguity, exact precision, side selection, demo enforcement, manual confirmation, intent-before-HTTP persistence, restart/idempotency, broker rejections, risk/context rejection, reconciliation, closing, shadow comparison and missing/configured credential UI states.

Validation after the close-safety correction: **65 focused eToro tests passed**; **1,396 full-suite tests passed**. Closing regression coverage includes rejected entry context, independence from entry risk/scanner/quote checks, position-only close mapping, confirmation and demo enforcement, valid IDs, durable close intent, and uncertain-response restart without replay. These results are for offline mocked validation, not a credentialed broker certification. `git diff --check` is clean. No commit was created.
