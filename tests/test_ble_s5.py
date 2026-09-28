"""Tests for the S5/A5 Bluetooth protocol."""

from __future__ import annotations

import base64
import os

import cbor2
import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from custom_components.vanmoof import ble_s5
from custom_components.vanmoof.ble_s5 import (
    PayloadType,
    Reassembler,
    S5AuthError,
    S5Session,
    Topic,
    build_fragments,
    build_subscribe,
    certificate_expiry,
    generate_keypair,
    state_from_topics,
)


def make_certificate(expiry: int) -> str:
    return base64.b64encode(os.urandom(64) + cbor2.dumps({"e": expiry, "i": 1})).decode()


def test_fragment_roundtrip_large_message() -> None:
    payload = bytes([PayloadType.AUTH_CERT]) + os.urandom(600)
    fragments = build_fragments(payload)
    assert len(fragments) == 3
    assert all(len(f) <= 244 for f in fragments)
    assert fragments[0][0] == 0x81
    assert fragments[1][0] == 0x01
    reassembler = Reassembler()
    results = [reassembler.feed(f) for f in fragments]
    assert results[:2] == [None, None]
    assert results[2].type == PayloadType.AUTH_CERT
    assert results[2].body == payload[1:]


def test_subscribe_message() -> None:
    assert build_subscribe([1, 24]) == b"\x02\xe0\x01\x00\x01\x00\x18"


def test_certificate_expiry() -> None:
    assert certificate_expiry(make_certificate(1_900_000_000)) == 1_900_000_000
    assert certificate_expiry("not base64!") is None


def test_state_from_topics() -> None:
    state = state_from_topics(
        {
            Topic.BATTERY: 64,
            Topic.MODULE_BATTERY: 90,
            Topic.LOCK: 3,
            Topic.DISTANCE: 123456,
            Topic.SPEED: 0,
            Topic.POWER_LEVEL: 2,
            Topic.LIGHT_MODE: 3,
            Topic.SPEED_LIMIT: 1,
            Topic.ALARM: 1,
            Topic.CALORIES: 1500,
            Topic.ERRORS: [],
            Topic.FIRMWARE: {"app": "1.2.3"},
        }
    )
    assert state.battery == 64
    assert state.module_battery == 90
    assert state.lock_state == "unlocked"
    assert state.distance_km == 1234.6
    assert state.light_mode == "auto"
    assert state.speed_limit == "32"
    assert state.alarm_state == "automatic"
    assert state.calories == 1500
    assert state.has_error is False
    assert state.firmware == {"app": "1.2.3"}


class FakeS5Bike:
    """Simulates the S5 notify/write characteristic."""

    services = None

    def __init__(self, public_key_b64: str) -> None:
        self._public = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        self._reassembler = Reassembler()
        self._callback = None
        self._nonce = os.urandom(16)
        self.subscribed: list[int] = []

    async def start_notify(self, _uuid, callback) -> None:
        self._callback = callback

    def _send(self, payload: bytes) -> None:
        for fragment in build_fragments(payload):
            self._callback(None, bytearray(fragment))

    async def write_gatt_char(self, _uuid, data: bytes, response: bool = False) -> None:
        message = self._reassembler.feed(bytes(data))
        if message is None:
            return
        if message.type == PayloadType.AUTH_CERT:
            self._send(bytes([PayloadType.AUTH_CHALLENGE]) + self._nonce)
        elif message.type == PayloadType.AUTH_CHALLENGE:
            try:
                self._public.verify(message.body, self._nonce)
                ok = True
            except InvalidSignature:
                ok = False
            self._send(bytes([PayloadType.AUTH_DETAILS]) + cbor2.dumps({"auth": ok, "enc": False}))
        elif message.type == PayloadType.SUBSCRIBE:
            body = message.body[2:]
            self.subscribed = [
                int.from_bytes(body[i : i + 2], "big") for i in range(0, len(body), 2)
            ]
            for topic, value in ((Topic.BATTERY, 55), (Topic.LOCK, 1), (Topic.DISTANCE, 5000)):
                self._send(
                    bytes([PayloadType.TOPIC]) + topic.to_bytes(2, "big") + cbor2.dumps(value)
                )


async def test_session_handshake_and_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ble_s5.asyncio, "sleep", _no_sleep)
    private, public = generate_keypair()
    bike = FakeS5Bike(public)
    session = S5Session(bike, make_certificate(1_900_000_000), private)
    await session.authenticate()
    state = await session.read_state(duration=0.2)
    assert Topic.BATTERY in bike.subscribed
    assert state.battery == 55
    assert state.lock_state == "locked"
    assert state.distance_km == 50.0


async def test_session_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ble_s5.asyncio, "sleep", _no_sleep)
    private, _ = generate_keypair()
    _, other_public = generate_keypair()
    session = S5Session(FakeS5Bike(other_public), make_certificate(1_900_000_000), private)
    with pytest.raises(S5AuthError):
        await session.authenticate()


async def _no_sleep(_seconds: float) -> None:
    return None
