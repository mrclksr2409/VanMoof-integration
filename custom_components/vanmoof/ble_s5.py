"""Bluetooth protocol for VanMoof S5 / A5 bikes.

The bike authenticates the app with an Ed25519 certificate issued by the
VanMoof cloud for a public key we generate. After the handshake the bike
publishes CBOR encoded "topics" (battery, lock, odometer, ...) for every topic
we subscribe to. Messages are split into fragments with a 3-byte header.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import io
import logging
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

import cbor2
from bleak import BleakClient
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .const import (
    S5_COLLECT_SECONDS,
    S5_LIGHT_MODES,
    S5_MTU,
    S5_NOTIFY_CHAR,
    S5_SPEED_LIMITS,
    S5_WRITE_CHAR,
)
from .models import BikeState

_LOGGER = logging.getLogger(__name__)


class S5AuthError(Exception):
    """The bike rejected our certificate."""


class S5ProtocolError(Exception):
    """Unexpected or missing answer from the bike."""


class PayloadType(IntEnum):
    """First byte of a reassembled message."""

    TOPIC = 1
    SUBSCRIBE = 2
    AUTH_CERT = 3
    AUTH_CHALLENGE = 4
    AUTH_DETAILS = 5
    PARAM_UPDATE = 7


class Topic(IntEnum):
    """Known topics published by the bike."""

    LOCK = 1
    MODULE_BATTERY = 16
    BATTERY = 24
    CALORIES = 73
    SPEED = 80
    SPEED_LIMIT = 97
    POWER_LEVEL = 101
    LIGHT_MODE = 106
    ALARM = 110
    BELL = 114
    LOCK_ALT = 161
    DISTANCE = 165
    FIRMWARE = 192
    FIND_MY = 225
    ERRORS = 255


SUBSCRIBE_CONTROL = 0xE001
SUBSCRIBED_TOPICS = [t.value for t in Topic]


# -- keys & certificates -------------------------------------------------------


def generate_keypair() -> tuple[str, str]:
    """Return (private seed, public key), both raw and base64 encoded."""
    key = Ed25519PrivateKey.generate()
    seed = key.private_bytes(
        serialization.Encoding.Raw,
        serialization.PrivateFormat.Raw,
        serialization.NoEncryption(),
    )
    public = key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return base64.b64encode(seed).decode(), base64.b64encode(public).decode()


def sign(private_key_b64: str, message: bytes) -> bytes:
    """Sign with the stored Ed25519 seed."""
    seed = base64.b64decode(private_key_b64)[:32]
    return Ed25519PrivateKey.from_private_bytes(seed).sign(message)


def cbor_first(data: bytes) -> Any:
    """Decode the first CBOR item in `data` (trailing bytes are ignored)."""
    return cbor2.CBORDecoder(io.BytesIO(data)).decode()


def certificate_expiry(certificate_b64: str) -> int | None:
    """Expiry timestamp embedded in a certificate (CBOR map after 64-byte signature)."""
    try:
        raw = base64.b64decode(certificate_b64)
        payload = cbor_first(raw[64:])
    except (binascii.Error, ValueError, cbor2.CBORDecodeError, EOFError):
        return None
    if isinstance(payload, dict) and isinstance(payload.get("e"), int):
        return payload["e"]
    return None


# -- framing -------------------------------------------------------------------


def build_fragments(payload: bytes, mtu: int = S5_MTU) -> list[bytes]:
    """Split a message into fragments of at most `mtu` bytes.

    The header holds a first-fragment flag and the number of bytes that follow
    the payload-type byte, which the receiver uses to know when it is complete.
    """
    chunk = mtu - 3
    fragments = []
    for index, offset in enumerate(range(0, len(payload), chunk)):
        remaining = len(payload) - 1 if index == 0 else len(payload) - offset
        header = bytes(
            [(0x80 if index == 0 else 0x00) | 0x01, (remaining >> 8) & 0xFF, remaining & 0xFF]
        )
        fragments.append(header + payload[offset : offset + chunk])
    return fragments


@dataclass
class Message:
    """A reassembled message."""

    type: int
    body: bytes


class Reassembler:
    """Collect fragments until a complete message is received."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._expected = 0

    def feed(self, fragment: bytes) -> Message | None:
        """Add a fragment; return the message when complete."""
        if len(fragment) < 3:
            return None
        if fragment[0] & 0x80:
            self._buffer = bytearray(fragment[3:])
            self._expected = int.from_bytes(fragment[1:3], "big") + 1
        else:
            self._buffer.extend(fragment[3:])
        if self._expected and len(self._buffer) >= self._expected:
            data = bytes(self._buffer[: self._expected])
            self._buffer = bytearray()
            self._expected = 0
            return Message(type=data[0], body=data[1:])
        return None


def build_subscribe(topics: list[int]) -> bytes:
    """Subscribe message for the given topics."""
    return (
        bytes([PayloadType.SUBSCRIBE])
        + SUBSCRIBE_CONTROL.to_bytes(2, "big")
        + b"".join(t.to_bytes(2, "big") for t in topics)
    )


def parse_topic(body: bytes) -> tuple[int, Any] | None:
    """Return (topic, value) from a TOPIC message body."""
    if len(body) < 2:
        return None
    topic = int.from_bytes(body[:2], "big")
    value: Any = None
    if len(body) > 2:
        try:
            value = cbor_first(body[2:])
        except (cbor2.CBORDecodeError, EOFError, ValueError):
            value = body[2:].hex()
    return topic, value


# -- state mapping ---------------------------------------------------------------


def _int(value: Any) -> int | None:
    if isinstance(value, bool):
        return int(value)
    return int(value) if isinstance(value, int | float) else None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def state_from_topics(topics: dict[int, Any]) -> BikeState:
    """Translate collected topics into a BikeState."""
    state = BikeState(in_range=True, raw={str(k): _text(v) for k, v in topics.items()})
    state.battery = _int(topics.get(Topic.BATTERY))
    state.module_battery = _int(topics.get(Topic.MODULE_BATTERY))
    lock = _int(topics.get(Topic.LOCK, topics.get(Topic.LOCK_ALT)))
    if lock is not None:
        state.lock_state = "unlocked" if lock == 3 else "locked"
    distance = _int(topics.get(Topic.DISTANCE))
    state.distance_km = round(distance / 100, 1) if distance is not None else None
    state.speed_kmh = _int(topics.get(Topic.SPEED))
    state.power_level = _int(topics.get(Topic.POWER_LEVEL))
    state.calories = _int(topics.get(Topic.CALORIES))
    if (light := _int(topics.get(Topic.LIGHT_MODE))) is not None:
        state.light_mode = S5_LIGHT_MODES.get(light)
    if (limit := _int(topics.get(Topic.SPEED_LIMIT))) is not None:
        state.speed_limit = S5_SPEED_LIMITS.get(limit)
    if (alarm := _int(topics.get(Topic.ALARM))) is not None:
        state.alarm_state = "off" if alarm == 0 else "automatic"
    if Topic.ERRORS in topics:
        errors = topics[Topic.ERRORS]
        empty = errors in (None, 0, b"", "", [], {}) or (
            isinstance(errors, list | tuple) and not any(errors)
        )
        state.errors = "" if empty else _text(errors)
    if (fw := topics.get(Topic.FIRMWARE)) is not None:
        if isinstance(fw, dict):
            state.firmware = {str(k): _text(v) or "" for k, v in fw.items()}
        else:
            state.firmware = {"bike": _text(fw) or ""}
    return state


# -- session ---------------------------------------------------------------------


class S5Session:
    """Talk to a connected S5/A5 bike."""

    def __init__(self, client: BleakClient, certificate_b64: str, private_key_b64: str) -> None:
        self._client = client
        self._certificate = base64.b64decode(certificate_b64)
        self._private_key = private_key_b64
        self._queue: asyncio.Queue[Message] = asyncio.Queue()
        self._reassembler = Reassembler()
        self._write_char = S5_NOTIFY_CHAR

    def _on_notify(self, _sender: Any, data: bytearray) -> None:
        if (message := self._reassembler.feed(bytes(data))) is not None:
            self._queue.put_nowait(message)

    async def _send(self, payload: bytes) -> None:
        for fragment in build_fragments(payload):
            await self._client.write_gatt_char(self._write_char, fragment, response=False)

    async def _wait_for(self, msg_type: int, seconds: float) -> Message:
        loop = asyncio.get_running_loop()
        end = loop.time() + seconds
        while (remaining := end - loop.time()) > 0:
            try:
                message = await asyncio.wait_for(self._queue.get(), remaining)
            except TimeoutError:
                break
            if message.type == msg_type:
                return message
        raise S5ProtocolError(f"No message of type {msg_type} received")

    async def authenticate(self) -> None:
        """Certificate handshake."""
        await self._client.start_notify(S5_NOTIFY_CHAR, self._on_notify)
        services = self._client.services
        if services is not None and services.get_characteristic(S5_WRITE_CHAR):
            self._write_char = S5_WRITE_CHAR
        await asyncio.sleep(1.0)
        await self._send(bytes([PayloadType.AUTH_CERT]) + self._certificate)
        challenge = await self._wait_for(PayloadType.AUTH_CHALLENGE, 6.0)
        await self._send(
            bytes([PayloadType.AUTH_CHALLENGE]) + sign(self._private_key, challenge.body)
        )
        details = await self._wait_for(PayloadType.AUTH_DETAILS, 10.0)
        try:
            info = cbor_first(details.body)
        except (cbor2.CBORDecodeError, EOFError, ValueError):
            info = None
        if not isinstance(info, dict) or not info.get("auth"):
            raise S5AuthError("Bike rejected the certificate")

    async def read_state(self, duration: float = S5_COLLECT_SECONDS) -> BikeState:
        """Subscribe to all topics and collect values for `duration` seconds."""
        await self._send(build_subscribe(SUBSCRIBED_TOPICS))
        topics: dict[int, Any] = {}
        loop = asyncio.get_running_loop()
        end = loop.time() + duration
        while (remaining := end - loop.time()) > 0:
            try:
                message = await asyncio.wait_for(self._queue.get(), remaining)
            except TimeoutError:
                break
            if message.type == PayloadType.TOPIC and (parsed := parse_topic(message.body)):
                topics[parsed[0]] = parsed[1]
        if not topics:
            raise S5ProtocolError("Bike did not publish any values")
        _LOGGER.debug("S5 topics: %s", topics)
        return state_from_topics(topics)
