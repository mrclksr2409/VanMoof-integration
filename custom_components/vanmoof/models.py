"""Data models for the VanMoof integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import Any

from .const import Generation


@dataclass
class BikeConfig:
    """Per-bike credentials, persisted in the config entry."""

    frame_number: str
    bike_id: int | None
    name: str
    generation: Generation
    ble_profile: str | None = None
    mac_address: str | None = None
    # S3/X3
    encryption_key: str | None = None
    user_key_id: int | None = None
    # S5/A5
    private_key: str | None = None
    public_key: str | None = None
    certificate: str | None = None
    certificate_expiry: int | None = None
    # Advertising address that successfully authenticated last time.
    ble_address: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Serialize for storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BikeConfig:
        """Deserialize from storage, ignoring unknown keys."""
        known = {f.name for f in fields(cls)}
        values = {k: v for k, v in data.items() if k in known}
        values["generation"] = Generation(values.get("generation", Generation.UNKNOWN))
        return cls(**values)


@dataclass
class BikeState:
    """Live values read over Bluetooth. `None` means "not reported"."""

    in_range: bool = False
    last_seen: datetime | None = None
    battery: int | None = None
    charging: bool | None = None
    module_battery: int | None = None
    module_charging: bool | None = None
    distance_km: float | None = None
    speed_kmh: int | None = None
    lock_state: str | None = None
    alarm_state: str | None = None
    power_level: int | None = None
    light_mode: str | None = None
    bell_tone: str | None = None
    speed_limit: str | None = None
    unit_system: str | None = None
    gear: int | None = None
    module_state: str | None = None
    calories: int | None = None
    errors: str | None = None
    firmware: dict[str, str] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def locked(self) -> bool | None:
        """Return True when the bike is locked."""
        if self.lock_state is None:
            return None
        return self.lock_state != "unlocked"

    @property
    def has_error(self) -> bool | None:
        """Return True when the bike reports an error."""
        if self.errors is None:
            return None
        return bool(self.errors)
