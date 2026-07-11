"""
Betfair Streaming API client — live odds for upcoming AU races.

Betfair's Streaming API pushes market updates over a persistent TLS socket.
Messages are newline-delimited JSON in the same format as the historical files.
This module:
  1. Authenticates with Betfair (certificate-based non-interactive login).
  2. Subscribes to all AU thoroughbred WIN markets for the current day.
  3. Emits RunnerOdds updates to a callback, which the live-poll task writes
     to the database and uses to recompute implied probs + edge.

The connection is managed with automatic reconnect on failure. The caller
is responsible for the outer scheduler loop (see pipeline/tasks/live_poll.py).

Betfair Streaming API docs:
  https://docs.developer.betfair.com/display/1smk3cen4v3lu3yomq5qye0d/Streaming+API
"""

import json
import logging
import socket
import ssl
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from racing.config import settings
from racing.pipeline.betfair.market_utils import MarketSnapshot, RunnerOdds

log = logging.getLogger(__name__)

STREAM_HOST = "stream-api.betfair.com"
STREAM_PORT = 443
CONNECT_TIMEOUT = 10
READ_TIMEOUT = 30
RECONNECT_DELAY = 5  # seconds between reconnect attempts


class BetfairStreamClient:
    """
    Persistent streaming connection to the Betfair Exchange.

    Usage:
        client = BetfairStreamClient(on_snapshot=my_callback)
        client.start()   # non-blocking — runs on a background thread
        # ... later ...
        client.stop()

    The on_snapshot callback receives a MarketSnapshot every time odds change.
    It must be thread-safe; the client calls it from the reader thread.
    """

    def __init__(self, on_snapshot: Callable[[MarketSnapshot], None]) -> None:
        self._on_snapshot = on_snapshot
        self._sock: ssl.SSLSocket | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._connection_id = ""
        self._session_token = ""

        # In-memory market state — rebuilt from streaming deltas
        self._market_defs: dict[str, dict] = {}
        self._runner_back: dict[str, dict[int, float]] = {}
        self._runner_lay: dict[str, dict[int, float]] = {}
        self._runner_vol: dict[str, dict[int, float]] = {}

    # ──────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────

    def start(self) -> None:
        """Start the reader thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="betfair-stream")
        self._thread.start()
        log.info("Betfair stream client started")

    def stop(self) -> None:
        self._running = False
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread:
            self._thread.join(timeout=5)
        log.info("Betfair stream client stopped")

    # ──────────────────────────────────────────
    # Connection lifecycle
    # ──────────────────────────────────────────

    def _run_loop(self) -> None:
        while self._running:
            try:
                self._connect_and_authenticate()
                self._subscribe_au_thoroughbred()
                self._read_loop()
            except Exception:
                log.exception("Stream error — reconnecting in %ss", RECONNECT_DELAY)
                time.sleep(RECONNECT_DELAY)

    def _connect_and_authenticate(self) -> None:
        ctx = ssl.create_default_context()
        ctx.load_cert_chain(settings.betfair_cert_path, settings.betfair_key_path)

        raw = socket.create_connection((STREAM_HOST, STREAM_PORT), timeout=CONNECT_TIMEOUT)
        self._sock = ctx.wrap_socket(raw, server_hostname=STREAM_HOST)
        self._sock.settimeout(READ_TIMEOUT)
        log.info("Connected to Betfair stream at %s:%s", STREAM_HOST, STREAM_PORT)

        # First message from server is a connection message with connection-id
        conn_msg = self._recv_message()
        self._connection_id = conn_msg.get("connectionId", "")

        # Authenticate
        self._send_message({
            "op": "authentication",
            "id": 1,
            "appKey": settings.betfair_app_key,
            "session": self._get_session_token(),
        })
        auth_resp = self._recv_message()
        if auth_resp.get("statusCode") != "SUCCESS":
            raise ConnectionError(f"Betfair auth failed: {auth_resp}")
        log.info("Betfair stream authenticated")

    def _get_session_token(self) -> str:
        """
        Non-interactive cert-based login. Returns the ssoid session token.
        Requires a Betfair API-NG application key and valid cert/key pair.
        """
        import httpx

        resp = httpx.post(
            "https://identitysso-cert.betfair.com/api/certlogin",
            data={"username": settings.betfair_username, "password": settings.betfair_password},
            headers={"X-Application": settings.betfair_app_key},
            cert=(settings.betfair_cert_path, settings.betfair_key_path),
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        if body.get("loginStatus") != "SUCCESS":
            raise ConnectionError(f"Betfair login failed: {body}")
        return body["sessionToken"]

    def _subscribe_au_thoroughbred(self) -> None:
        """Subscribe to all AU thoroughbred WIN markets for today."""
        self._send_message({
            "op": "marketSubscription",
            "id": 2,
            "marketFilter": {
                "countries": ["AU"],
                "marketTypes": ["WIN"],
                "eventTypeIds": ["7"],   # Horse Racing
            },
            "marketDataFilter": {
                "fields": ["EX_BEST_OFFERS", "EX_TRADED", "SP_NEAR", "SP_ACTUAL"],
                "ladderLevels": 3,
            },
        })
        log.info("Subscribed to AU thoroughbred WIN markets")

    # ──────────────────────────────────────────
    # Message loop
    # ──────────────────────────────────────────

    def _read_loop(self) -> None:
        while self._running:
            msg = self._recv_message()
            op = msg.get("op")
            if op == "mcm":
                self._handle_mcm(msg)
            elif op == "heartbeat":
                pass  # keep-alive, no action needed

    def _handle_mcm(self, msg: dict[str, Any]) -> None:
        now = datetime.now(timezone.utc)
        for mc in msg.get("mc", []):
            mid = mc.get("id", "")
            if not mid:
                continue

            if "marketDefinition" in mc:
                self._market_defs[mid] = mc["marketDefinition"]

            for rc in mc.get("rc", []):
                sid = rc.get("id")
                if sid is None:
                    continue
                if "batb" in rc and rc["batb"]:
                    self._runner_back.setdefault(mid, {})[sid] = rc["batb"][0][1]
                if "batl" in rc and rc["batl"]:
                    self._runner_lay.setdefault(mid, {})[sid] = rc["batl"][0][1]
                if "trd" in rc:
                    for trd in rc["trd"]:
                        self._runner_vol.setdefault(mid, {})[sid] = (
                            self._runner_vol.get(mid, {}).get(sid, 0) + trd[1]
                        )

            snapshot = self._build_snapshot(mid, now)
            if snapshot:
                self._on_snapshot(snapshot)

    def _build_snapshot(self, market_id: str, captured_at: datetime) -> MarketSnapshot | None:
        defn = self._market_defs.get(market_id)
        if not defn:
            return None

        runners = []
        for r in defn.get("runners", []):
            sid = r["id"]
            scratched = r.get("status") == "REMOVED"
            runners.append(RunnerOdds(
                selection_id=sid,
                name=r.get("name", ""),
                win_back=self._runner_back.get(market_id, {}).get(sid),
                win_lay=self._runner_lay.get(market_id, {}).get(sid),
                traded_vol=self._runner_vol.get(market_id, {}).get(sid, 0.0),
                scratched=scratched,
            ))

        return MarketSnapshot(market_id=market_id, captured_at=captured_at, runners=runners)

    # ──────────────────────────────────────────
    # Socket I/O
    # ──────────────────────────────────────────

    def _send_message(self, msg: dict[str, Any]) -> None:
        assert self._sock is not None
        data = (json.dumps(msg) + "\r\n").encode()
        self._sock.sendall(data)

    def _recv_message(self) -> dict[str, Any]:
        assert self._sock is not None
        buf = b""
        while not buf.endswith(b"\r\n"):
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError("Betfair stream connection closed")
            buf += chunk
        return json.loads(buf.strip())
