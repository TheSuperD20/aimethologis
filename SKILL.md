---
name: mm
description: Use when building a Mattermost bot, integrating with Mattermost API, or debugging WebSocket/REST issues in a chat bot. Covers deadlocks, event loop isolation, reconnection, message dedup, state sync, and timeout patterns. Trigger words - mattermostdriver, websocket, httpx, event loop, deadlock, reconnect, dedup, timeout.
---

# Mattermost Bot Integration Checklist

Production-tested pitfalls and patterns from building async Mattermost bots. Every item caused real outages.

## When to Use

- Building a bot that connects to Mattermost via WebSocket + REST API
- Debugging hangs, deadlocks, duplicate messages, or lost state
- Using `mattermostdriver` Python library
- Any async Python bot with WebSocket listener + HTTP API calls

## Architecture: The Threading Problem

Mattermost bots have a fundamental threading challenge:

```
Main thread (asyncio event loop)
  |
  +-- WebSocket listener (worker thread, own event loop)
       |
       +-- WS handler callback (async, in worker thread's loop)
            |
            +-- REST API calls (must NOT use main loop)
            +-- LLM calls (need timeout that works across threads)
```

**The root cause of most bugs:** WebSocket runs in a worker thread with its own event loop. Any code that assumes a single event loop will deadlock.

## Critical Pitfalls

### 1. NEVER use async HTTP client from WebSocket handler

**Problem:** WebSocket handler runs in a worker thread. Using `await async_httpx_client.get()` or `run_in_executor` deadlocks because the future resolves on the main event loop which is blocked.

**Fix:** Use sync `httpx.get()` / `httpx.post()` directly. The worker thread can run sync code safely.

```python
# WRONG - deadlocks
async def _ws_handler(self, event):
    resp = await self._async_client.get(url)           # deadlock
    resp = await loop.run_in_executor(None, requests.get, url)  # deadlock

# RIGHT - sync httpx in worker thread
def _sync_api_get(self, path: str) -> httpx.Response:
    return httpx.get(f"{self._api_base}{path}",
                     headers=self._headers, timeout=30.0)
```

### 2. SSL monkey-patch for mattermostdriver WebSocket

mattermostdriver uses `ssl.Purpose.CLIENT_AUTH` for WebSocket SSL context — wrong for client connections on modern Python/OpenSSL.

```python
import mattermostdriver.websocket as mm_ws
_orig = mm_ws.ssl.create_default_context
def _fix(*a, **kw): return _orig(ssl.Purpose.SERVER_AUTH)
mm_ws.ssl.create_default_context = _fix
```

### 3. LLM timeout: threading.Timer, not asyncio.wait_for

`asyncio.wait_for` doesn't fire when the event loop is blocked (worker thread scenario). Use a thread-based watchdog:

```python
async def _call_llm(self, **kwargs):
    loop = asyncio.get_event_loop()
    task = loop.create_task(self._client.chat.completions.create(**kwargs))

    def _watchdog():
        if not task.done():
            loop.call_soon_threadsafe(task.cancel)

    timer = threading.Timer(90.0, _watchdog)
    timer.daemon = True
    timer.start()
    try:
        return await task
    except asyncio.CancelledError:
        raise asyncio.TimeoutError("LLM timed out")
    finally:
        timer.cancel()
```

### 4. WebSocket deduplication on reconnect

Mattermost replays recent events on WebSocket reconnect. Without dedup, bot sends duplicate responses.

```python
self._seen_ids: set[str] = set()

async def _ws_handler(self, event):
    post_id = post.get("id", "")
    if post_id in self._seen_ids:
        return
    self._seen_ids.add(post_id)
    if len(self._seen_ids) > 2000:
        self._seen_ids = set(list(self._seen_ids)[-1000:])
```

### 5. WebSocket supervision loop with auto-reconnect

WebSocket dies silently (network issues, token expiry). Must supervise:

```python
while not self._shutdown:
    try:
        await loop.run_in_executor(None, self._start_ws_listener)
    except Exception:
        logger.exception("ws_crashed")
    if self._shutdown:
        break
    reconnect_count += 1
    await asyncio.sleep(min(5 * 2**reconnect_count, 30))
    await loop.run_in_executor(None, self._driver.login)  # fresh token
    self._headers = {"Authorization": f"Bearer {self._driver.client.token}"}
```

### 6. WebSocket handler needs its own event loop

```python
def _start_ws_listener(self) -> None:
    thread_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(thread_loop)
    try:
        self._driver.init_websocket(self._ws_handler)
    finally:
        thread_loop.close()
```

## State & Data Integrity

### 7. Save state in finally block

If exception occurs during processing, unsaved state is lost forever. Always persist in `finally`:

```python
try:
    notebook = await updater.update(notebook, messages)
    # ... processing ...
finally:
    save_notebook(session, notebook)  # ALWAYS persist
```

### 8. Re-feed gap detection for missed messages

Bot restart = missed messages. Detect gaps by comparing thread message count with notebook state:

```python
thread_msgs = await messenger.get_thread_messages(thread_id)
user_msgs = [m for m in thread_msgs if m.author != bot_username]
gap = len(user_msgs) - notebook.message_count
if gap > len(current_batch):
    batch_ids = {m.id for m in current_batch}
    missed = [m for m in user_msgs if m.id not in batch_ids]
    current_batch = missed[-(gap - len(current_batch)):] + current_batch
```

### 9. Message buffer: snapshot before flush

Race condition: new messages arrive while processing buffered ones. Take snapshot, process, then pop only processed:

```python
messages = list(self._buffers[thread_id])  # snapshot
await callback(thread_id, messages)
self._buffers[thread_id] = self._buffers[thread_id][len(messages):]  # pop processed
```

### 10. Notebook state vs formal model desync

Cheap LLM maintains `notebook.positions` and `notebook.waiting_for`. Formal `session.positions` (Pydantic model) is a separate dict. They WILL desync. **Always use notebook state** (the LLM-maintained one) as source of truth for "who responded."

## Performance & Resilience

### 11. Cap batch size for cheap model

Cheap models (Gemini Flash, Haiku) timeout on 50+ messages. Cap input:

```python
if len(messages) > 15:
    messages = messages[-15:]
```

But track absolute count from the full thread separately.

### 12. Compact state for cheap LLM calls

Truncate constraint to 200 chars, positions to 100 chars, keep last 10 messages. Cheap models have small context.

### 13. Cache user ID lookups

`user_id -> username` mapping via HTTP is slow. Cache in memory (dict is fine for <1000 users).

### 14. Wrap all external calls in try/except

Every Mattermost API call can fail. Never let a failed reaction or user lookup crash batch processing.

### 15. HTTP-only login for scripts

One-shot scripts (digest, reports) should skip WebSocket. Use `driver.login()` + sync httpx directly.

## Quick Reference

| Problem | Wrong | Right |
|---------|-------|-------|
| HTTP from WS handler | `await async_client.get()` | `httpx.get()` sync |
| LLM timeout | `asyncio.wait_for()` | `threading.Timer` watchdog |
| WS reconnect dupes | No dedup | `_seen_ids` set |
| WS dies silently | Single `init_websocket()` | Supervision loop + backoff |
| State on crash | Save after processing | Save in `finally` |
| Missed messages | Hope for the best | Gap detection + re-feed |
| Who responded? | `session.positions` | `notebook.waiting_for` |
| Cheap model timeout | Send all messages | Cap to 15 |
| SSL on modern Python | Default mattermostdriver | Monkey-patch SERVER_AUTH |
