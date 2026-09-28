"""Tests for the S3/X3 Bluetooth protocol."""

from __future__ import annotations

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from custom_components.vanmoof import const
from custom_components.vanmoof.ble_s3 import (
    S3Crypto,
    S3Session,
    parse_errors,
    parse_string,
    parse_u32_le,
)

from .conftest import S3_KEY


def _aes(data: bytes, decrypt: bool = False) -> bytes:
    cipher = Cipher(algorithms.AES(bytes.fromhex(S3_KEY)), modes.ECB())
    op = cipher.decryptor() if decrypt else cipher.encryptor()
    return op.update(data) + op.finalize()


def _block(data: bytes) -> bytes:
    return _aes(data.ljust(16, b"\x00"))


def test_auth_payload() -> None:
    crypto = S3Crypto(S3_KEY, 2)
    payload = crypto.auth_payload(b"\x12\x34")
    assert len(payload) == 20
    assert payload[16:] == b"\x00\x00\x00\x02"
    assert _aes(payload[:16], decrypt=True) == b"\x12\x34" + b"\x00" * 14


def test_write_payload_roundtrip() -> None:
    crypto = S3Crypto(S3_KEY, 1)
    payload = crypto.write_payload(b"\xab\xcd", b"\x03\x01")
    assert _aes(payload, decrypt=True) == b"\xab\xcd\x03\x01" + b"\x00" * 12
    assert crypto.decrypt(payload)[:4] == b"\xab\xcd\x03\x01"


def test_parsers() -> None:
    assert parse_u32_le((12345).to_bytes(4, "little") + b"\x00" * 12) == 12345
    assert parse_string(b"1.09.03\x00\x00junk") == "1.09.03"
    assert parse_errors(b"\x00" * 16) == ""
    assert parse_errors(b"\x00\x02") == "0002"


class FakeS3Bike:
    """Simulates the GATT server of an S3 bike."""

    def __init__(self) -> None:
        self.authenticated = False
        self.writes: list[tuple[str, bytes]] = []
        self.values = {
            const.S3_DISTANCE: (43210).to_bytes(4, "little"),
            const.S3_SPEED: b"\x00",
            const.S3_LOCK_STATE: b"\x01",
            const.S3_ALARM_STATE: b"\x02",
            const.S3_POWER_LEVEL: b"\x03",
            const.S3_SPEED_LIMIT: b"\x00",
            const.S3_UNIT_SYSTEM: b"\x00",
            const.S3_GEAR: b"\x02",
            const.S3_LIGHT_MODE: b"\x00",
            const.S3_BELL_TONE: b"\x16",
            const.S3_MODULE_STATE: b"\x03",
            const.S3_ERRORS: b"\x00",
            const.S3_MODULE_BATTERY_LEVEL: b"\x55",
            const.S3_MODULE_BATTERY_STATE: b"\x00",
            const.S3_BATTERY_STATE: b"\x01",
            const.S3_FW_BIKE: b"1.09.03\x00",
            const.S3_BATTERY_LEVEL: b"\x4d",
        }

    async def read_gatt_char(self, uuid: str) -> bytes:
        from bleak.exc import BleakError

        if uuid == const.S3_CHALLENGE:
            return b"\x42\x24"
        if not self.authenticated:
            raise BleakError("Insufficient authentication")
        if uuid not in self.values:
            raise BleakError("Invalid handle")
        return _block(self.values[uuid])

    async def write_gatt_char(self, uuid: str, data: bytes, response: bool = True) -> None:
        if uuid == const.S3_KEY_INDEX:
            self.authenticated = _aes(data[:16], decrypt=True)[:2] == b"\x42\x24"
            return
        self.writes.append((uuid, _aes(data, decrypt=True)))


async def test_read_state() -> None:
    bike = FakeS3Bike()
    session = S3Session(bike, S3Crypto(S3_KEY, 2))
    await session.authenticate()
    state = await session.read_state()
    assert state.in_range
    assert state.distance_km == 4321.0
    assert state.battery == 77
    assert state.module_battery == 85
    assert state.lock_state == "locked"
    assert state.locked is True
    assert state.alarm_state == "automatic"
    assert state.power_level == 3
    assert state.speed_limit == "eu"
    assert state.gear == 2
    assert state.light_mode == "auto"
    assert state.bell_tone == "bell"
    assert state.module_state == "standby"
    assert state.charging is True
    assert state.module_charging is False
    assert state.has_error is False
    assert state.firmware == {"bike": "1.09.03"}


async def test_wrong_key_raises_auth_error() -> None:
    import pytest

    from custom_components.vanmoof.ble_s3 import S3AuthError

    session = S3Session(FakeS3Bike(), S3Crypto("ff" * 16, 2))
    await session.authenticate()
    with pytest.raises(S3AuthError):
        await session.read_state()


async def test_commands() -> None:
    bike = FakeS3Bike()
    session = S3Session(bike, S3Crypto(S3_KEY, 2))
    await session.authenticate()
    await session.unlock()
    await session.set_power_level(2)
    await session.set_light_mode(1)
    await session.play_sound(const.S3_SOUND_HORN)
    assert bike.writes[0] == (const.S3_LOCK_STATE, b"\x42\x24\x00" + b"\x00" * 13)
    assert bike.writes[1][1][:4] == b"\x42\x24\x02\x01"
    assert bike.writes[2][1][:3] == b"\x42\x24\x01"
    assert bike.writes[3][1][:4] == b"\x42\x24\x0a\x01"
