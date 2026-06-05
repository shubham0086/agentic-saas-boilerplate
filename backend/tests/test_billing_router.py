import hmac
import hashlib
import json
import pytest
from fastapi.testclient import TestClient

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from billing_router import router
from fastapi import FastAPI

app = FastAPI()
app.include_router(router)
client = TestClient(app)

STRIPE_SECRET = "whsec_mocksecret12345"
RAZORPAY_SECRET = "rzp_mocksecret12345"


def make_stripe_sig(body: bytes, timestamp: str = "1234567890") -> str:
    signed = f"{timestamp}.".encode() + body
    sig = hmac.new(STRIPE_SECRET.encode(), signed, hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={sig}"


def make_razorpay_sig(body: bytes) -> str:
    return hmac.new(RAZORPAY_SECRET.encode(), body, hashlib.sha256).hexdigest()


# --- Stripe ---

def test_stripe_missing_header():
    res = client.post("/api/billing/webhook/stripe", json={})
    assert res.status_code == 400


def test_stripe_invalid_signature():
    body = json.dumps({"type": "checkout.session.completed"}).encode()
    res = client.post(
        "/api/billing/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": "t=999,v1=badhash", "Content-Type": "application/json"}
    )
    assert res.status_code == 401


def test_stripe_valid_checkout_event():
    payload = {
        "type": "checkout.session.completed",
        "data": {"object": {"client_reference_id": "user_1"}}
    }
    body = json.dumps(payload).encode()
    sig = make_stripe_sig(body)
    res = client.post(
        "/api/billing/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json()["gateway"] == "stripe"


def test_stripe_valid_unknown_event_type():
    payload = {"type": "invoice.paid"}
    body = json.dumps(payload).encode()
    sig = make_stripe_sig(body)
    res = client.post(
        "/api/billing/webhook/stripe",
        content=body,
        headers={"Stripe-Signature": sig, "Content-Type": "application/json"}
    )
    assert res.status_code == 200


# --- Razorpay ---

def test_razorpay_missing_header():
    res = client.post("/api/billing/webhook/razorpay", json={})
    assert res.status_code == 400


def test_razorpay_invalid_signature():
    body = json.dumps({"event": "payment.captured"}).encode()
    res = client.post(
        "/api/billing/webhook/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": "badhash", "Content-Type": "application/json"}
    )
    assert res.status_code == 401


def test_razorpay_valid_payment_captured():
    payload = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"email": "test@example.com"}}}
    }
    body = json.dumps(payload).encode()
    sig = make_razorpay_sig(body)
    res = client.post(
        "/api/billing/webhook/razorpay",
        content=body,
        headers={"X-Razorpay-Signature": sig, "Content-Type": "application/json"}
    )
    assert res.status_code == 200
    assert res.json()["gateway"] == "razorpay"


# --- Quota ---

def test_get_default_quota():
    res = client.get("/api/billing/user/quota?user_id=user_1")
    assert res.status_code == 200
    data = res.json()
    assert data["user_id"] == "user_1"
    assert "remaining_credits" in data


def test_get_unknown_user_quota():
    res = client.get("/api/billing/user/quota?user_id=ghost")
    assert res.status_code == 200
    assert res.json()["remaining_credits"] == 0
