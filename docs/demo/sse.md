# Guided Demo SSE contract

Website clients **must** use `fetch` + `ReadableStream` for `POST /v1/turns`.
Do **not** use `EventSource` for POST (EventSource is GET-only).

Internal process path: `http://127.0.0.1:8091/v1/*`.
Browser path after Nginx: `/api/demo/v1/*`.

## Framing

Each event is:

```
event: <name>
data: <json>

```

(`data` is a single JSON object; a blank line terminates the event.)

`Cache-Control: no-cache` and `X-Accel-Buffering: no` are set so proxies do not buffer.

## Display semantics

| Kind | How the UI must label it |
| --- | --- |
| `accepted.mode=live` | Real external OpenAI-compatible call (key configured). Still **not** a full Kernel. |
| `accepted.mode=fake` | Deterministic Fake LLM. Never show as live Kernel reasoning. |
| `fallback.label=canned-demo` | Prepared example. Never show as live execution. |
| `streaming=chunked-complete` | Full text then chunked; **not** token streaming. |

Do not expose chain-of-thought, Cortex, DecisionProcessor, or other Kernel internals.
`status.phase` is only `analyzing` | `organizing` | `answering`.

## Happy-path order

1. Optional `queued` (if both execution slots are busy)
2. `accepted` (`mode` is `live` or `fake`; `streaming` is `chunked-complete`)
3. `status` (`analyzing` then `organizing` then `answering`)
4. optional `tool` (`readonly: true`, whitelist names only)
5. one or more `delta`
6. `done`

Queued tasks do **not** buffer model tokens. They only store queue metadata until a slot is claimed.

## Capacity / failure order

When the queue is full, wait times out, or the model fails, the stream (or JSON) includes:

1. `error` with a frozen `code`
2. `fallback` with `label: canned-demo`

Never leave the client with a blank stream.

Frozen error codes: `rate_limited`, `turn_limit`, `input_too_long`, `queue_full`,
`wait_timeout`, `session_expired`, `already_running`, `unavailable`, `tool_denied`,
`csrf_denied`, `origin_denied`.

## Cancel

`POST /v1/turns/{taskId}/cancel` (cookie + Origin + CSRF):

- queued task → SSE/JSON `cancelled` with `released: queue` (immediate dequeue)
- running task → `released: slot` (LLM work cancelled)

## Disconnect and reconnect

- If the POST stream drops, the server waits **2 seconds**.
- Reconnect with `GET /v1/stream/{taskId}` using the **same session cookie**, Origin, and CSRF.
- Ownership is checked; another session receives an error, never the stream.
- If nobody reconnects within 2 seconds, the task is cancelled and the slot/queue entry is released.
- After the task is terminal, events stay in a **32KiB ring for at most 15 seconds** so a late client can read `done` / `error` / `fallback` / `cancelled`. The LLM/slot is **not** held during that retain window.

## Security

JSON and SSE payloads must not include session ids, cookies, API keys, data-directory paths, raw IPs, or tracebacks.
