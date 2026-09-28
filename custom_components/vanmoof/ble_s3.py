"""Bluetooth protocol for VanMoof S3 / X3 (and older ELECTRIFIED) bikes.

Every protected characteristic is AES-128-ECB encrypted with the key issued by
the cloud. Authentication writes the encrypted challenge nonce plus the user
key id to the key-index characteristic; writes are prefixed with a fresh nonce.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from bleak import BleakClient
from bleak.exc import BleakError
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    ALARM_STATES,
    BELL_TONES,
    LOCK_STATES,
    MODULE_STATES,
    S3_ALARM_STATE,
    S3_BATTERY_LEVEL,
    S3_BATTERY_STATE,
    S3_BELL_TONE,
    S3_CHALLENGE,
    S3_DISTANCE,
    S3_ERRORS,
    S3_FW_BATTERY,
    S3_FW_BIKE,
    S3_FW_BLE,
    S3_FW_CONTROLLER,
    S3_GEAR,
    S3_KEY_INDEX,
    S3_LIGHT_MODE,
    S3_LIGHT_MODES,
    S3_LOCK_STATE,
    S3_MODULE_BATTERY_LEVEL,
    S3_MODULE_BATTERY_STATE,
    S3_MODULE_STATE,
    S3_PLAY_SOUND,
    S3_POWER_LEVEL,
    S3_SPEED,
    S3_SPEED_LIMIT,
    S3_SPEED_LIMITS,
    S3_UNIT_SYSTEM,
    UNIT_SYSTEMS,
)
from .models import BikeState

_LOGGER = logging.getLogger(__name__)

_T = TypeVar("_T")


class S3AuthError(Exception):
    """The bike rejected our key (reads fail after authentication)."""


class S3Crypto:
    """AES helpers for the S3/X3 protocol."""

    def __init__(self, key_hex: str, user_key_id: int) -> None:
        key = bytes.fromhex(key_hex)
        if len(key) != 16:
            raise ValueError("VanMoof S3 encryption key must be 16 bytes")
        self._cipher = Cipher(algorithms.AES(key), modes.ECB())
        self._user_key_id = user_key_id

    def _encrypt(self, data: bytes) -> bytes:
        enc = self._cipher.encryptor()
        return enc.update(data) + enc.finalize()

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt a payload (length must be a multiple of 16)."""
        if not data or len(data) % 16:
            return bytes(data)
        dec = self._cipher.decryptor()
        return dec.update(bytes(data)) + dec.finalize()

    def auth_payload(self, nonce: bytes) -> bytes:
        """Build the payload for the key-index characteristic."""
        block = bytearray(16)
        block[0:2] = nonce[:2]
        return self._encrypt(bytes(block)) + bytes([0, 0, 0, self._user_key_id & 0xFF])

    def write_payload(self, nonce: bytes, data: bytes) -> bytes:
        """Encrypt `data` prefixed with the nonce, zero-padded to 16 bytes."""
        payload = bytearray(nonce[:2]) + bytearray(data)
        payload.extend(b"\x00" * (-len(payload) % 16))
        return self._encrypt(bytes(payload))


def parse_u8(data: bytes) -> int | None:
    """First byte as integer."""
    return data[0] if data else None


def parse_u32_le(data: bytes) -> int | None:
    """First four bytes as little-endian unsigned integer."""
    return int.from_bytes(data[:4], "little") if len(data) >= 4 else None


def parse_string(data: bytes) -> str | None:
    """Null-terminated ASCII string."""
    value = bytes(data).split(b"\x00", 1)[0].decode("ascii", "replace").strip()
    return value or None


def parse_errors(data: bytes) -> str:
    """Hex representation of the error field; empty string = no error."""
    return bytes(data).hex() if any(data) else ""


class S3Session:
    """An authenticated session with a connected S3/X3 bike."""

    def __init__(self, client: BleakClient, crypto: S3Crypto) -> None:
        self._client = client
        self._crypto = crypto

    async def _nonce(self) -> bytes:
        return bytes(await self._client.read_gatt_char(S3_CHALLENGE))

    async def authenticate(self) -> None:
        """Perform the challenge handshake."""
        nonce = await self._nonce()
        await self._client.write_gatt_char(
            S3_KEY_INDEX, self._crypto.auth_payload(nonce), response=True
        )

    async def read(self, uuid: str) -> bytes:
        """Read and decrypt a characteristic."""
        return self._crypto.decrypt(bytes(await self._client.read_gatt_char(uuid)))

    async def write(self, uuid: str, data: bytes) -> None:
        """Encrypt and write a characteristic."""
        nonce = await self._nonce()
        await self._client.write_gatt_char(
            uuid, self._crypto.write_payload(nonce, data), response=True
        )

    async def _optional(self, uuid: str, parser: Callable[[bytes], _T]) -> _T | None:
        """Read a value that some firmware does not support."""
        try:
            return parser(await self.read(uuid))
        except (BleakError, TimeoutError, ValueError, IndexError) as err:
            _LOGGER.debug("Optional read %s failed: %s", uuid, err)
            return None

    async def read_state(self) -> BikeState:
        """Read everything the bike exposes."""
        # The first protected read proves the key works.
        try:
            distance = parse_u32_le(await self.read(S3_DISTANCE))
        except BleakError as err:
            raise S3AuthError(str(err)) from err

        state = BikeState(in_range=True)
        state.distance_km = distance / 10 if distance is not None else None
        state.speed_kmh = await self._optional(S3_SPEED, parse_u8)
        state.lock_state = _map(await self._optional(S3_LOCK_STATE, parse_u8), LOCK_STATES)
        state.alarm_state = _map(await self._optional(S3_ALARM_STATE, parse_u8), ALARM_STATES)
        state.power_level = await self._optional(S3_POWER_LEVEL, parse_u8)
        state.speed_limit = _map(await self._optional(S3_SPEED_LIMIT, parse_u8), S3_SPEED_LIMITS)
        state.unit_system = _map(await self._optional(S3_UNIT_SYSTEM, parse_u8), UNIT_SYSTEMS)
        state.gear = await self._optional(S3_GEAR, parse_u8)
        state.light_mode = _map(await self._optional(S3_LIGHT_MODE, parse_u8), S3_LIGHT_MODES)
        state.bell_tone = _map(await self._optional(S3_BELL_TONE, parse_u8), BELL_TONES)
        state.module_state = _map(await self._optional(S3_MODULE_STATE, parse_u8), MODULE_STATES)
        state.errors = await self._optional(S3_ERRORS, parse_errors)
        state.module_battery = await self._optional(S3_MODULE_BATTERY_LEVEL, parse_u8)
        state.module_charging = _flag(await self._optional(S3_MODULE_BATTERY_STATE, parse_u8))
        state.charging = _flag(await self._optional(S3_BATTERY_STATE, parse_u8))
        for key, uuid in (
            ("bike", S3_FW_BIKE),
            ("ble", S3_FW_BLE),
            ("controller", S3_FW_CONTROLLER),
            ("battery", S3_FW_BATTERY),
        ):
            if version := await self._optional(uuid, parse_string):
                state.firmware[key] = version

        # Right after waking up the bike briefly reports a placeholder 100 %.
        battery = await self._optional(S3_BATTERY_LEVEL, parse_u8)
        if battery is not None and battery >= 100:
            await asyncio.sleep(2)
            reread = await self._optional(S3_BATTERY_LEVEL, parse_u8)
            if reread is not None:
                battery = reread
        state.battery = battery
        return state

    async def unlock(self) -> None:
        """Unlock the bike (locking is done by pushing the lock on the bike)."""
        await self.write(S3_LOCK_STATE, bytes([0]))

    async def set_power_level(self, level: int) -> None:
        """Set motor assist level 0-4."""
        await self.write(S3_POWER_LEVEL, bytes([level, 0x01]))

    async def set_light_mode(self, mode: int) -> None:
        """Set light mode (see S3_LIGHT_MODES)."""
        await self.write(S3_LIGHT_MODE, bytes([mode]))

    async def set_bell_tone(self, tone: int) -> None:
        """Set bell tone (see BELL_TONES)."""
        await self.write(S3_BELL_TONE, bytes([tone]))

    async def play_sound(self, sound: int, count: int = 1) -> None:
        """Play a sound on the bike's speaker."""
        await self.write(S3_PLAY_SOUND, bytes([sound, count]))


def _map(value: int | None, mapping: dict[int, str]) -> str | None:
    if value is None:
        return None
    if value not in mapping:
        _LOGGER.debug("Unknown value %s for mapping %s", value, mapping)
    return mapping.get(value)


def _flag(value: int | None) -> bool | None:
    return None if value is None else value == 1


S3Action = Callable[[S3Session], Awaitable[Any]]
