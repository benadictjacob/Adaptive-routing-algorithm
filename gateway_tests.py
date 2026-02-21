"""
═══════════════════════════════════════════════════════════════════════
  GATEWAY SECURITY TEST SUITE
  Section 15 — Test Cases   |   Section 16 — Success Criteria
═══════════════════════════════════════════════════════════════════════

Tests:
  1. Unauthorized client request
  2. Forged signature
  3. Wrong gateway origin
  4. Replayed request
  5. Expired timestamp
  6. Rate limit exceeded
  7. Direct router access attempt
  + Valid request end-to-end
  + Trust feedback / client blocking
  + Gateway failover (Section 13)

Each test prints PASS or FAIL.
"""

import sys
import os
import time
import secrets

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gateway import (
    Gateway, SecureRouter, ClientRegistry,
    GatewayRequest, build_client_request, sign, hash_request,
)

# ═══════════════════════════════════════════════════════════════════
#  INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════

_results = []


def run_test(name, fn):
    try:
        fn()
        print(f"  [PASS] {name}")
        _results.append((name, True, ""))
    except Exception as e:
        print(f"  [FAIL] {name}")
        print(f"         Error: {e}")
        _results.append((name, False, str(e)))


def setup():
    """Create a fresh registry, gateway, and router for each test."""
    reg = ClientRegistry()
    gw = Gateway("GW-ALPHA", reg)
    gws = {"GW-ALPHA": gw}
    router = SecureRouter(reg, gws)
    client = reg.register_client("C001", "GW-ALPHA", allowed_regions=["US", "EU"], rate_limit=5)
    return reg, gw, router, client, gws


# ═══════════════════════════════════════════════════════════════════
#  SECTION 15 — MANDATORY TESTS
# ═══════════════════════════════════════════════════════════════════

def test_valid_request():
    """End-to-end: valid client -> gateway -> router succeeds."""
    reg, gw, router, client, _ = setup()
    req = build_client_request(client, payload="ping")
    accepted, reason, signed_req = gw.process_request(req)
    assert accepted, f"Gateway rejected valid request: {reason}"
    assert signed_req.signature_gateway, "No gateway signature"

    router_ok, router_reason = router.accept_request(signed_req)
    assert router_ok, f"Router rejected valid request: {router_reason}"


def test_unauthorized_client():
    """Test 1: Unregistered client is rejected."""
    reg, gw, router, client, _ = setup()
    req = GatewayRequest(
        client_id="UNKNOWN",
        gateway_id="GW-ALPHA",
        timestamp=str(time.time()),
        nonce=secrets.token_hex(16),
        payload="hack",
        signature_client="fake",
    )
    accepted, reason, _ = gw.process_request(req)
    assert not accepted, "Unregistered client was accepted"
    assert "unregistered" in reason, f"Wrong reason: {reason}"


def test_forged_signature():
    """Test 2: Forged client signature is rejected."""
    reg, gw, router, client, _ = setup()
    req = build_client_request(client, payload="test", forge_signature=True)
    accepted, reason, _ = gw.process_request(req)
    assert not accepted, "Forged signature was accepted"
    assert "signature" in reason, f"Wrong reason: {reason}"


def test_wrong_gateway_origin():
    """Test 3: Client routing through wrong gateway is rejected."""
    reg, gw, router, client, gws = setup()
    # Create a second gateway
    gw2 = Gateway("GW-BETA", reg)
    gws["GW-BETA"] = gw2

    # Client is assigned to GW-ALPHA but sends to GW-BETA
    req = build_client_request(client, payload="test", override_gateway="GW-BETA")
    accepted, reason, _ = gw2.process_request(req)
    assert not accepted, "Wrong gateway accepted request"
    assert "wrong_gateway" in reason, f"Wrong reason: {reason}"


def test_replayed_request():
    """Test 4: Replayed nonce is rejected."""
    reg, gw, router, client, _ = setup()
    fixed_nonce = secrets.token_hex(16)
    req1 = build_client_request(client, payload="first", nonce=fixed_nonce)
    ok1, _, _ = gw.process_request(req1)
    assert ok1, "First request should succeed"

    req2 = build_client_request(client, payload="first", nonce=fixed_nonce)
    ok2, reason, _ = gw.process_request(req2)
    assert not ok2, "Replayed request was accepted"
    assert "replay" in reason or "nonce" in reason, f"Wrong reason: {reason}"


def test_expired_timestamp():
    """Test 5: Request with old timestamp is rejected."""
    reg, gw, router, client, _ = setup()
    old_ts = str(time.time() - 120)  # 2 minutes ago (window is 60s)
    req = build_client_request(client, payload="old", timestamp=old_ts)
    accepted, reason, _ = gw.process_request(req)
    assert not accepted, "Expired timestamp was accepted"
    assert "expired" in reason or "timestamp" in reason, f"Wrong reason: {reason}"


def test_rate_limit_exceeded():
    """Test 6: Exceeding rate limit blocks further requests."""
    reg, gw, router, client, _ = setup()
    # Client rate limit = 5
    for i in range(5):
        req = build_client_request(client, payload=f"req{i}")
        ok, reason, _ = gw.process_request(req)
        assert ok, f"Request {i} should succeed: {reason}"

    # 6th request should be blocked
    req = build_client_request(client, payload="excess")
    ok, reason, _ = gw.process_request(req)
    assert not ok, "Rate-limited request was accepted"
    assert "rate" in reason, f"Wrong reason: {reason}"


def test_direct_router_access():
    """Test 7: Request sent directly to router (no gateway signature) is dropped."""
    reg, gw, router, client, _ = setup()
    # Build request but skip gateway processing
    req = build_client_request(client, payload="bypass")
    # Do NOT pass through gateway — send directly to router
    ok, reason = router.accept_request(req)
    assert not ok, "Direct router access was accepted"
    assert "no_gateway_signature" in reason or "signature" in reason, f"Wrong reason: {reason}"


# ═══════════════════════════════════════════════════════════════════
#  ADDITIONAL SECURITY TESTS
# ═══════════════════════════════════════════════════════════════════

def test_trust_feedback_blocks_client():
    """Section 12: Malicious client gets blocked after trust drops."""
    reg, gw, router, client, _ = setup()

    # Client starts with trust=1.0
    req = build_client_request(client, payload="ok")
    ok, _, _ = gw.process_request(req)
    assert ok, "Initial request should succeed"

    # Node reports malicious behavior multiple times
    gw.report_malicious_client("C001", severity=0.4)
    gw.report_malicious_client("C001", severity=0.4)
    gw.report_malicious_client("C001", severity=0.4)
    # Trust should now be ~0.0
    rec = reg.get_client("C001")
    assert rec.trust_score < Gateway.TRUST_BLOCK_THRESHOLD, \
        f"Trust not low enough: {rec.trust_score}"

    # Next request should be blocked
    req2 = build_client_request(client, payload="blocked")
    ok2, reason, _ = gw.process_request(req2)
    assert not ok2, "Blocked client was accepted"
    assert "trust" in reason or "block" in reason, f"Wrong reason: {reason}"


def test_gateway_failover():
    """Section 13: Client reassigned when gateway fails."""
    reg, gw, router, client, gws = setup()
    gw2 = Gateway("GW-BETA", reg)
    gws["GW-BETA"] = gw2
    router_new = SecureRouter(reg, gws)

    # Primary gateway fails
    gw.fail()
    req = build_client_request(client, payload="failover")
    ok, reason, _ = gw.process_request(req)
    assert not ok, "Offline gateway accepted request"

    # System reassigns to GW-BETA
    reg.reassign_gateway("C001", "GW-BETA")

    # Now send through GW-BETA
    req2 = build_client_request(client, payload="failover", override_gateway="GW-BETA")
    ok2, reason2, signed = gw2.process_request(req2)
    assert ok2, f"Failover gateway rejected: {reason2}"

    router_ok, rr = router_new.accept_request(signed)
    assert router_ok, f"Router rejected failover request: {rr}"


def test_region_not_allowed():
    """Section 8: Request from unauthorized region is rejected."""
    reg, gw, router, client, _ = setup()
    req = build_client_request(client, payload="intl", region="CN")  # only US,EU allowed
    ok, reason, _ = gw.process_request(req)
    assert not ok, "Unauthorized region was accepted"
    assert "region" in reason, f"Wrong reason: {reason}"


def test_router_rejects_tampered_signature():
    """Router detects tampered gateway signature."""
    reg, gw, router, client, _ = setup()
    req = build_client_request(client, payload="tamper")
    ok, _, signed = gw.process_request(req)
    assert ok, "Gateway should accept"

    # Tamper with the gateway signature
    signed.signature_gateway = "tampered_" + signed.signature_gateway[9:]
    rok, reason = router.accept_request(signed)
    assert not rok, "Router accepted tampered signature"
    assert "signature" in reason, f"Wrong reason: {reason}"


def test_missing_fields_rejected():
    """Section 4: Request with missing fields is rejected."""
    reg, gw, router, client, _ = setup()
    req = GatewayRequest(
        client_id="C001",
        gateway_id="",         # missing
        timestamp="",          # missing
        nonce="abc",
        payload="test",
        signature_client="sig",
    )
    ok, reason, _ = gw.process_request(req)
    assert not ok, "Request with missing fields was accepted"
    assert "missing" in reason, f"Wrong reason: {reason}"


# ═══════════════════════════════════════════════════════════════════
#  RUNNER
# ═══════════════════════════════════════════════════════════════════

def run_all_gateway_tests():
    global _results
    _results = []

    print("=" * 70)
    print("  SECURE GATEWAY ENTRY CONTROL -- TEST SUITE")
    print("=" * 70)

    print("\n  -- Section 15: Mandatory Security Tests ----")
    run_test("Valid End-to-End Request", test_valid_request)
    run_test("1. Unauthorized Client", test_unauthorized_client)
    run_test("2. Forged Signature", test_forged_signature)
    run_test("3. Wrong Gateway Origin", test_wrong_gateway_origin)
    run_test("4. Replayed Request", test_replayed_request)
    run_test("5. Expired Timestamp", test_expired_timestamp)
    run_test("6. Rate Limit Exceeded", test_rate_limit_exceeded)
    run_test("7. Direct Router Access", test_direct_router_access)

    print("\n  -- Additional Security Tests ----")
    run_test("8. Trust Feedback Blocks Client", test_trust_feedback_blocks_client)
    run_test("9. Gateway Failover", test_gateway_failover)
    run_test("10. Region Not Allowed", test_region_not_allowed)
    run_test("11. Router Rejects Tampered Sig", test_router_rejects_tampered_signature)
    run_test("12. Missing Fields Rejected", test_missing_fields_rejected)

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)
    total = len(_results)

    print("\n" + "=" * 70)
    print(f"  RESULTS: {passed}/{total} PASSED, {failed}/{total} FAILED")
    print("=" * 70)

    if failed > 0:
        print("\n  Failed tests:")
        for name, ok, err in _results:
            if not ok:
                print(f"    x {name}: {err}")

    return failed == 0


if __name__ == "__main__":
    success = run_all_gateway_tests()
    sys.exit(0 if success else 1)
