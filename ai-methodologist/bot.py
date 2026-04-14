import ssl
import json
import logging
import threading
import asyncio
import time
from typing import Callable, Optional
import requests
import mattermostdriver.websocket as mm_ws

# SSL fix: mattermostdriver uses CLIENT_AUTH which is wrong for client connections
_orig_ssl = mm_ws.ssl.create_default_context
mm_ws.ssl.create_default_context = lambda *a, **kw: _orig_ssl(ssl.Purpose.SERVER_AUTH)

from mattermostdriver import Driver

logger = logging.getLogger(__name__)


class MattermostBot:
    def __init__(self, url: str, token: str, username: str = "ai-methodologist"):
        parsed = url.rstrip("/")
        scheme = "https" if parsed.startswith("https") else "http"
        host = parsed.replace("https://", "").replace("http://", "")

        self._driver = Driver({
            "url": host,
            "token": token,
            "scheme": scheme,
            "port": 443 if scheme == "https" else 8065,
            "verify": True,
            "timeout": 15,
        })
        self._token = token
        self._base_url = parsed
        self._api_base = f"{parsed}/api/v4"
        self._headers = {"Authorization": f"Bearer {token}"}
        self._seen_ids: set = set()
        self._shutdown = False
        self._message_callback: Optional[Callable] = None
        self.bot_user_id: Optional[str] = None

    def login(self, retries: int = 5, retry_delay: float = 3.0, attempt_timeout: float = 15.0):
        import concurrent.futures
        last_exc = None
        for attempt in range(1, retries + 1):
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(self._driver.login)
                    me = future.result(timeout=attempt_timeout)
                self._headers = {"Authorization": f"Bearer {self._driver.client.token}"}
                if not isinstance(me, dict):
                    me = {}
                self.bot_user_id = me.get("id")
                logger.info(f"Logged in as {me.get('username')} ({self.bot_user_id})")
                return
            except concurrent.futures.TimeoutError:
                last_exc = TimeoutError(f"Login timed out after {attempt_timeout}s")
                logger.warning(f"Login attempt {attempt}/{retries} timed out")
            except Exception as e:
                last_exc = e
                logger.warning(f"Login attempt {attempt}/{retries} failed: {e}")
            if attempt < retries:
                time.sleep(retry_delay)
        raise last_exc

    def logout(self):
        try:
            self._driver.logout()
        except Exception:
            pass

    def get_bot_user_info(self) -> dict:
        return self._sync_get("/users/me")

    # --- Sync REST helpers (safe to call from WebSocket worker thread) ---

    def _sync_get(self, path: str) -> dict:
        resp = requests.get(f"{self._api_base}{path}", headers=self._headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _sync_post(self, path: str, data) -> dict:
        resp = requests.post(f"{self._api_base}{path}", headers=self._headers, json=data, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # --- Public API ---

    def send_typing(self, channel_id: str) -> None:
        """Send a single typing indicator pulse to the channel."""
        try:
            requests.post(
                f"{self._api_base}/users/me/typing",
                headers=self._headers,
                json={"channel_id": channel_id},
                timeout=5,
            )
        except Exception:
            pass  # typing indicator is best-effort

    def typing_while(self, channel_id: str, interval: float = 2.5):
        """Context manager that sends typing indicator until the block finishes.

        Usage:
            with bot.typing_while(channel_id):
                result = llm.generate_longread(...)
        """
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            stop_event = threading.Event()

            def _pulse():
                while not stop_event.wait(interval):
                    self.send_typing(channel_id)

            self.send_typing(channel_id)  # immediate first pulse
            t = threading.Thread(target=_pulse, daemon=True)
            t.start()
            try:
                yield
            finally:
                stop_event.set()

        return _ctx()



    def send_message(self, channel_id: str, message: str) -> str:
        post = self._sync_post("/posts", {"channel_id": channel_id, "message": message})
        return post.get("id", "")

    def send_buttons(self, channel_id: str, message: str, buttons: list) -> str:
        """Send message with interactive buttons.

        buttons: [{"name": "Label", "context": {"task_id": ..., "action": ...}}]
        Buttons POST to CALLBACK_URL/api/button_callback when clicked.
        """
        import os
        callback_base = os.environ.get("CALLBACK_URL", "http://localhost:8000")
        attachments = [{
            "text": "",
            "actions": [
                {
                    "name": btn["name"],
                    "integration": {
                        "url": f"{callback_base}/api/button_callback",
                        "context": btn.get("context", {}),
                    },
                }
                for btn in buttons
            ],
        }]
        post = self._sync_post("/posts", {
            "channel_id": channel_id,
            "message": message,
            "props": {"attachments": attachments},
        })
        return post.get("id", "")

    def send_file(self, channel_id: str, file_path: str, message: str = "") -> str:
        """Upload a file and post it to channel."""
        filename = file_path.split("/")[-1]
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{self._api_base}/files",
                headers={"Authorization": self._headers["Authorization"]},
                data={"channel_id": channel_id},
                files={"files": (filename, f)},
                timeout=60,
            )
            resp.raise_for_status()
            file_id = resp.json()["file_infos"][0]["id"]
        post = self._sync_post("/posts", {
            "channel_id": channel_id,
            "message": message,
            "file_ids": [file_id],
        })
        return post.get("id", "")

    def get_dm_channel(self, user_id: str) -> str:
        """Get or create DM channel between bot and user."""
        try:
            data = self._sync_post("/channels/direct", [self.bot_user_id, user_id])
            return data["id"]
        except Exception as e:
            logger.error(f"get_dm_channel failed for user_id={user_id}: {e}")
            raise

    def get_user_by_username(self, username: str) -> Optional[dict]:
        username = username.lstrip("@")
        try:
            return self._sync_get(f"/users/username/{username}")
        except Exception:
            return None

    def download_file(self, file_id: str, save_path: str) -> None:
        resp = requests.get(
            f"{self._api_base}/files/{file_id}",
            headers=self._headers,
            timeout=120,
            allow_redirects=True,
        )
        resp.raise_for_status()
        with open(save_path, "wb") as f:
            f.write(resp.content)

    # --- WebSocket listener ---

    def set_message_callback(self, callback: Callable):
        """callback(user_id, channel_id, message, file_ids) called for each new message."""
        self._message_callback = callback

    def start_listening(self):
        """Start WebSocket supervision loop in background thread. Non-blocking."""
        t = threading.Thread(target=self._supervision_loop, daemon=True)
        t.start()

    def stop(self):
        self._shutdown = True

    def _supervision_loop(self):
        reconnect_count = 0
        while not self._shutdown:
            try:
                self._start_ws()
            except Exception:
                logger.exception("WebSocket crashed")
            if self._shutdown:
                break
            reconnect_count += 1
            delay = min(5 * (2 ** reconnect_count), 30)
            logger.info(f"Reconnecting in {delay}s...")
            time.sleep(delay)
            try:
                self.login()
            except Exception:
                logger.exception("Re-login failed")

    def _start_ws(self):
        thread_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(thread_loop)
        try:
            self._driver.init_websocket(self._ws_handler)
        finally:
            thread_loop.close()

    async def _ws_handler(self, event):
        try:
            # mattermostdriver may send event as string or dict
            if isinstance(event, str):
                event = json.loads(event)
            if not isinstance(event, dict):
                return
            if event.get("event") != "posted":
                return
            data = event.get("data", {})
            post = json.loads(data.get("post", "{}"))
            post_id = post.get("id", "")

            # Dedup
            if post_id in self._seen_ids:
                return
            self._seen_ids.add(post_id)
            if len(self._seen_ids) > 2000:
                self._seen_ids = set(list(self._seen_ids)[-1000:])

            # Ignore system posts (join/leave/add to channel etc.)
            # System posts have a non-empty "type" field like "system_join_team".
            if post.get("type", ""):
                return

            user_id = post.get("user_id", "")
            if not user_id:
                return  # no author → system event
            if user_id == self.bot_user_id:
                return  # ignore own messages

            # Only process Direct Messages (channel_type "D").
            # Ignore public/private channels and group chats to avoid
            # responding in shared channels like Town Square.
            channel_type = data.get("channel_type", "")
            if channel_type != "D":
                return

            channel_id = post.get("channel_id", "")
            message = post.get("message", "")
            file_ids = post.get("file_ids", [])

            if self._message_callback:
                self._message_callback(user_id, channel_id, message, file_ids)
        except Exception:
            logger.exception("Error in ws_handler")
