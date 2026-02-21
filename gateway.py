"""
═══════════════════════════════════════════════════════════════════════
  SECURE CLIENT GATEWAY ENTRY CONTROL
  Sections 1–14 of the Gateway Specification
═══════════════════════════════════════════════════════════════════════

Architecture:  Client → Assigned Gateway → Router → Target Node

Guarantees:
  • No client can bypass a gateway
  • No external traffic reaches routers
  • No spoofed requests accepted
  • No replay attacks succeed
  • No unauthorized region access
"""

import hashlib
import hmac
import time
import secrets
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


# ═══════════════════════════════════════════════════════════════════
#  CRYPTO HELPERS
# ═══════════════════════════════════════════════════════════════════

def generate_keypair() -> Tuple[str, str]:
    """Generate a simulated (private_key, public_key) pair using HMAC secrets."""
    private = secrets.token_hex(32)
    public = hashlib.sha256(private.encode()).hexdigest()
    return private, public


def sign(data: str, private_key: str) -> str:
    """Produce HMAC-SHA256 signature of data using private_key."""
    return hmac.new(private_key.encode(), data.encode(), hashlib.sha256).hexdigest()


def verify(data: str, signature: str, private_key: str, public_key: str) -> bool:
    """
    Verify that the signature matches sign(data, private_key).
    In a real system this would use asymmetric crypto; here we
    accept the private key on the verification side for simulation.
    """
    expected = sign(data, private_key)
    return hmac.compare_digest(expected, signature)


def hash_request(payload: str, nonce: str, timestamp: str) -> str:
    """Deterministic hash of the signable portion of a request."""
    raw = f"{payload}|{nonce}|{timestamp}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ═══════════════════════════════════════════════════════════════════
#  SECTION 2 — CLIENT REGISTRATION
# ═══════════════════════════════════════════════════════════════════

@dataclass
class ClientRecord:
    """Registered client entry in the registry."""
    client_id: str
    public_key: str
    _private_key: str                       # kept for simulation signing
    assigned_gateway_id: str
    allowed_regions: List[str] = field(default_factory=list)
    rate_limit: int = 10                    # requests per window
    trust_score: float = 1.0               # [0, 1]


# ═══════════════════════════════════════════════════════════════════
#  SECTION 4 — REQUEST FORMAT
# ═══════════════════════════════════════════════════════════════════

@dataclass
class GatewayRequest:
    """
    Forwarded request format.  ALL fields are mandatory.
    Requests missing any field must be rejected.
    """
    client_id: str
    gateway_id: str
    timestamp: str
    nonce: str
    payload: str
    signature_client: str
    signature_gateway: str = ""             # attached by gateway after validation
    region: str = ""                        # optional region tag


# ═══════════════════════════════════════════════════════════════════
#  CLIENT REGISTRY
# ═══════════════════════════════════════════════════════════════════

class ClientRegistry:
    """
    Central registry that maps client_id → ClientRecord.
    Used by gateways and routers for validation lookups.
    """

    def __init__(self):
        self._clients: Dict[str, ClientRecord] = {}
        self._gateway_ids: set = set()

    # ── Registration ──────────────────────────────────────────────

    def register_client(
        self,
        client_id: str,
        gateway_id: str,
        allowed_regions: Optional[List[str]] = None,
        rate_limit: int = 10,
    ) -> ClientRecord:
        """Register a new client and return its record (with keys)."""
        priv, pub = generate_keypair()
        record = ClientRecord(
            client_id=client_id,
            public_key=pub,
            _private_key=priv,
            assigned_gateway_id=gateway_id,
            allowed_regions=allowed_regions or [],
            rate_limit=rate_limit,
        )
        self._clients[client_id] = record
        self._gateway_ids.add(gateway_id)
        return record

    def get_client(self, client_id: str) -> Optional[ClientRecord]:
        return self._clients.get(client_id)

    def is_registered(self, client_id: str) -> bool:
        return client_id in self._clients

    # ── Section 13 — Gateway failover ────────────────────────────

    def reassign_gateway(self, client_id: str, new_gateway_id: str) -> bool:
        """Reassign client to a new gateway (system-initiated only)."""
        rec = self._clients.get(client_id)
        if rec is None:
            return False
        rec.assigned_gateway_id = new_gateway_id
        self._gateway_ids.add(new_gateway_id)
        return True

    # ── Section 12 — Trust feedback ──────────────────────────────

    def reduce_trust(self, client_id: str, amount: float = 0.2) -> float:
        """Reduce client trust score.  Returns new score."""
        rec = self._clients.get(client_id)
        if rec is None:
            return -1.0
        rec.trust_score = max(0.0, rec.trust_score - amount)
        return rec.trust_score

    @property
    def all_clients(self) -> Dict[str, ClientRecord]:
        return dict(self._clients)


# ═══════════════════════════════════════════════════════════════════
#  SECTION 3 — GATEWAY
# ═══════════════════════════════════════════════════════════════════

class Gateway:
    """
    Trusted entry validator.

    Responsibilities:
      1. Authenticate client identity (Section 5)
      2. Validate request format (Section 4)
      3. Enforce rate limits (Section 9)
      4. Replay protection (Section 10)
      5. Region validation (Section 8)
      6. Attach gateway signature (Section 6)
      7. Forward to router

    Gateways NEVER modify payload content.
    """

    NONCE_WINDOW_SECONDS = 60               # reject timestamps older than this
    TRUST_BLOCK_THRESHOLD = 0.2             # block client if trust < this

    def __init__(self, gateway_id: str, registry: ClientRegistry):
        self.gateway_id = gateway_id
        self.registry = registry
        self._private_key, self._public_key = generate_keypair()
        self._nonce_cache: Dict[str, set] = {}     # client_id → {nonces}
        self._request_counts: Dict[str, int] = {}  # client_id → count this window
        self._window_start: float = time.time()
        self._window_seconds: float = 60.0
        self.alive: bool = True

    # ── Public key for router verification ────────────────────────

    @property
    def public_key(self) -> str:
        return self._public_key

    # ── Main entry point ──────────────────────────────────────────

    def process_request(self, req: GatewayRequest) -> Tuple[bool, str, Optional[GatewayRequest]]:
        """
        Validate and sign a client request.

        Returns:
            (accepted: bool, reason: str, signed_request or None)
        """
        if not self.alive:
            return False, "gateway_offline", None

        # 1 — Format validation (Section 4)
        missing = self._check_format(req)
        if missing:
            return False, f"missing_fields:{','.join(missing)}", None

        # 2 — Client exists?
        client = self.registry.get_client(req.client_id)
        if client is None:
            return False, "unregistered_client", None

        # 3 — Gateway assignment check (Section 7 pre-check)
        if client.assigned_gateway_id != self.gateway_id:
            return False, "wrong_gateway", None

        # 4 — Trust check (Section 12)
        if client.trust_score < self.TRUST_BLOCK_THRESHOLD:
            return False, "client_blocked_low_trust", None

        # 5 — Client signature verification (Section 5)
        data_to_verify = hash_request(req.payload, req.nonce, req.timestamp)
        if not verify(data_to_verify, req.signature_client,
                      client._private_key, client.public_key):
            return False, "invalid_client_signature", None

        # 6 — Replay protection (Section 10)
        replay_ok, replay_reason = self._check_replay(req.client_id, req.nonce, req.timestamp)
        if not replay_ok:
            return False, replay_reason, None

        # 7 — Rate limiting (Section 9)
        rate_ok, rate_reason = self._check_rate(req.client_id, client.rate_limit)
        if not rate_ok:
            return False, rate_reason, None

        # 8 — Region validation (Section 8)
        if client.allowed_regions and req.region:
            if req.region not in client.allowed_regions:
                return False, "region_not_allowed", None

        # 9 — Sign request (Section 6)
        full_hash = hashlib.sha256(
            f"{req.client_id}|{req.gateway_id}|{req.payload}|{req.nonce}|{req.timestamp}".encode()
        ).hexdigest()
        req.signature_gateway = sign(full_hash, self._private_key)

        return True, "accepted", req

    # ── Internal validations ──────────────────────────────────────

    def _check_format(self, req: GatewayRequest) -> List[str]:
        """Return list of missing mandatory fields."""
        missing = []
        if not req.client_id:
            missing.append("client_id")
        if not req.gateway_id:
            missing.append("gateway_id")
        if not req.timestamp:
            missing.append("timestamp")
        if not req.nonce:
            missing.append("nonce")
        if req.payload is None:
            missing.append("payload")
        if not req.signature_client:
            missing.append("signature_client")
        return missing

    def _check_replay(self, client_id: str, nonce: str, timestamp: str) -> Tuple[bool, str]:
        """Section 10: reject reused nonces and stale timestamps."""
        # Timestamp freshness
        try:
            ts = float(timestamp)
        except ValueError:
            return False, "invalid_timestamp"
        if time.time() - ts > self.NONCE_WINDOW_SECONDS:
            return False, "expired_timestamp"

        # Nonce uniqueness
        if client_id not in self._nonce_cache:
            self._nonce_cache[client_id] = set()
        if nonce in self._nonce_cache[client_id]:
            return False, "replayed_nonce"
        self._nonce_cache[client_id].add(nonce)
        return True, "ok"

    def _check_rate(self, client_id: str, limit: int) -> Tuple[bool, str]:
        """Section 9: per-client rate limiting."""
        now = time.time()
        if now - self._window_start > self._window_seconds:
            self._request_counts.clear()
            self._window_start = now

        count = self._request_counts.get(client_id, 0)
        if count >= limit:
            return False, "rate_limit_exceeded"
        self._request_counts[client_id] = count + 1
        return True, "ok"

    # ── Section 12 — Trust feedback ──────────────────────────────

    def report_malicious_client(self, client_id: str, severity: float = 0.3) -> float:
        """Node reports malicious behavior → gateway reduces trust."""
        return self.registry.reduce_trust(client_id, severity)

    # ── Gateway failure (Section 13) ─────────────────────────────

    def fail(self):
        self.alive = False

    def recover(self):
        self.alive = True


# ═══════════════════════════════════════════════════════════════════
#  SECTION 11 — ROUTER ACCEPTANCE RULE
# ═══════════════════════════════════════════════════════════════════

class SecureRouter:
    """
    Router that only accepts gateway-signed traffic.

    Acceptance rule (Section 11):
      valid_gateway_signature == TRUE  →  process
      otherwise                        →  drop silently

    Origin enforcement (Section 7):
      request.gateway_id must match registry[client_id].assigned_gateway
    """

    def __init__(self, registry: ClientRegistry, gateways: Dict[str, Gateway]):
        self.registry = registry
        self.gateways = gateways          # gateway_id → Gateway (for pubkey lookup)

    def accept_request(self, req: GatewayRequest) -> Tuple[bool, str]:
        """
        Validate a gateway-signed request before routing.

        Returns (accepted, reason).
        """
        # 1 — Must have gateway signature (Section 11)
        if not req.signature_gateway:
            return False, "no_gateway_signature"

        # 2 — Gateway must be known
        gw = self.gateways.get(req.gateway_id)
        if gw is None:
            return False, "unknown_gateway"

        # 3 — Verify gateway signature (Section 6)
        full_hash = hashlib.sha256(
            f"{req.client_id}|{req.gateway_id}|{req.payload}|{req.nonce}|{req.timestamp}".encode()
        ).hexdigest()
        expected_sig = sign(full_hash, gw._private_key)
        if not hmac.compare_digest(req.signature_gateway, expected_sig):
            return False, "invalid_gateway_signature"

        # 4 — Origin enforcement (Section 7)
        client = self.registry.get_client(req.client_id)
        if client is None:
            return False, "unregistered_client"
        if client.assigned_gateway_id != req.gateway_id:
            return False, "gateway_origin_mismatch"

        return True, "accepted"


# ═══════════════════════════════════════════════════════════════════
#  HELPER — Build a signed request (for simulation)
# ═══════════════════════════════════════════════════════════════════

def build_client_request(
    client: ClientRecord,
    payload: str = "hello",
    region: str = "",
    timestamp: Optional[str] = None,
    nonce: Optional[str] = None,
    forge_signature: bool = False,
    override_gateway: Optional[str] = None,
) -> GatewayRequest:
    """
    Convenience function that creates a properly signed GatewayRequest
    on behalf of a registered client.
    """
    ts = timestamp or str(time.time())
    nc = nonce or secrets.token_hex(16)
    data = hash_request(payload, nc, ts)

    if forge_signature:
        sig = "forged_" + secrets.token_hex(16)
    else:
        sig = sign(data, client._private_key)

    return GatewayRequest(
        client_id=client.client_id,
        gateway_id=override_gateway or client.assigned_gateway_id,
        timestamp=ts,
        nonce=nc,
        payload=payload,
        signature_client=sig,
        signature_gateway="",               # gateway fills this in
        region=region,
    )
