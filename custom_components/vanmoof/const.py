"""Constants for the VanMoof integration."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

DOMAIN: Final = "vanmoof"

# --- Config entry keys ------------------------------------------------------

CONF_ACCOUNT_ID: Final = "account_id"
CONF_REFRESH_TOKEN: Final = "refresh_token"
CONF_BIKES: Final = "bikes"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_RIDE_STATISTICS: Final = "ride_statistics"

DEFAULT_SCAN_INTERVAL: Final = 300  # seconds between BLE polls
MIN_SCAN_INTERVAL: Final = 60
MAX_SCAN_INTERVAL: Final = 3600
CLOUD_UPDATE_INTERVAL: Final = 3600  # seconds between cloud refreshes

# --- Cloud API --------------------------------------------------------------

# Static key shipped in the official VanMoof app; identical for every user.
API_KEY: Final = "fcb38d47-f14b-30cf-843b-26283f6a5819"
API_BASE_URLS: Final = (
    "https://api.vanmoof-api.com/v8",
    "https://my.vanmoof.com/api/v8",
)
BIKE_API_URL: Final = "https://bikeapi.production.vanmoof.cloud"
TENJIN_API_URL: Final = "https://tenjin.vanmoof.com/api/v1"
TOKEN_EXPIRY_MARGIN: Final = 60  # seconds
CERT_RENEWAL_WINDOW: Final = 24 * 60 * 60  # seconds


class Generation(StrEnum):
    """Bluetooth protocol generation of a bike."""

    S3 = "s3"  # S3 / X3 and older "ELECTRIFIED" bikes: AES-128 key from the cloud
    S5 = "s5"  # S5 / A5: Ed25519 certificate issued by the cloud
    UNKNOWN = "unknown"


BLE_PROFILE_GENERATION: Final[dict[str, Generation]] = {
    "SMARTBIKE_2016": Generation.S3,
    "SMARTBIKE_2018": Generation.S3,
    "ELECTRIFIED_2016": Generation.S3,
    "ELECTRIFIED_2017": Generation.S3,
    "ELECTRIFIED_2018": Generation.S3,
    "ELECTRIFIED_2019": Generation.S3,
    "ELECTRIFIED_2020": Generation.S3,
    "ELECTRIFIED_2021": Generation.S3,
    "ELECTRIFIED_2022": Generation.S5,
    "ELECTRIFIED_2023_TRACK_1": Generation.S5,
}


def generation_for_profile(ble_profile: str | None, has_key: bool) -> Generation:
    """Map the cloud `bleProfile` to a protocol generation."""
    if ble_profile and ble_profile in BLE_PROFILE_GENERATION:
        return BLE_PROFILE_GENERATION[ble_profile]
    if ble_profile and ble_profile.startswith(("ELECTRIFIED_2023", "ELECTRIFIED_2024")):
        return Generation.S5
    # Older bikes without a known profile still work if the cloud gave us a key.
    return Generation.S3 if has_key else Generation.UNKNOWN


# --- S3 / X3 Bluetooth profile ------------------------------------------------


def _s3_uuid(short: str) -> str:
    return f"6acc{short}-e631-4069-944d-b8ca7598ad50"


S3_SERVICE_INFO: Final = _s3_uuid("5540")
S3_SERVICE_SECURITY: Final = _s3_uuid("5500")
S3_CHALLENGE: Final = _s3_uuid("5501")
S3_KEY_INDEX: Final = _s3_uuid("5502")
S3_LOCK_STATE: Final = _s3_uuid("5521")
S3_ALARM_STATE: Final = _s3_uuid("5523")
S3_DISTANCE: Final = _s3_uuid("5531")
S3_SPEED: Final = _s3_uuid("5532")
S3_UNIT_SYSTEM: Final = _s3_uuid("5533")
S3_POWER_LEVEL: Final = _s3_uuid("5534")
S3_SPEED_LIMIT: Final = _s3_uuid("5535")
S3_GEAR: Final = _s3_uuid("5536")
S3_BATTERY_LEVEL: Final = _s3_uuid("5541")
S3_BATTERY_STATE: Final = _s3_uuid("5542")
S3_MODULE_BATTERY_LEVEL: Final = _s3_uuid("5543")
S3_MODULE_BATTERY_STATE: Final = _s3_uuid("5544")
S3_FW_BIKE: Final = _s3_uuid("554a")
S3_FW_BLE: Final = _s3_uuid("554b")
S3_FW_CONTROLLER: Final = _s3_uuid("554c")
S3_FW_BATTERY: Final = _s3_uuid("5550")
S3_MODULE_STATE: Final = _s3_uuid("5562")
S3_ERRORS: Final = _s3_uuid("5563")
S3_PLAY_SOUND: Final = _s3_uuid("5571")
S3_BELL_TONE: Final = _s3_uuid("5574")
S3_LIGHT_MODE: Final = _s3_uuid("5581")

S3_SOUND_HORN: Final = 0x0A

# --- S5 / A5 Bluetooth profile ------------------------------------------------

S5_SERVICE: Final = "e3d80000-3416-4a54-b011-68d41fdcbfcf"
S5_NOTIFY_CHAR: Final = "e3d80001-3416-4a54-b011-68d41fdcbfcf"
S5_WRITE_CHAR: Final = "e3d80002-3416-4a54-b011-68d41fdcbfcf"
S5_MTU: Final = 244
S5_COLLECT_SECONDS: Final = 5.0

# --- Value mappings shared by entities ---------------------------------------

LOCK_STATES: Final = {0: "unlocked", 1: "locked", 2: "awaiting_unlock"}
ALARM_STATES: Final = {0: "off", 1: "manual", 2: "automatic"}
S3_LIGHT_MODES: Final = {0: "auto", 1: "on", 2: "off"}
S5_LIGHT_MODES: Final = {0: "off", 1: "on", 2: "halo", 3: "auto"}
S3_SPEED_LIMITS: Final = {0: "eu", 1: "us", 2: "jp"}
S5_SPEED_LIMITS: Final = {0: "25", 1: "32", 2: "24"}
UNIT_SYSTEMS: Final = {0: "metric", 1: "imperial"}
BELL_TONES: Final = {0x0A: "sonar", 0x16: "bell", 0x17: "party", 0x18: "foghorn"}
MODULE_STATES: Final = {
    0: "on",
    1: "off",
    2: "shipping",
    3: "standby",
    4: "alarm_1",
    5: "alarm_2",
    6: "alarm_3",
    7: "sleeping",
    8: "tracking",
}
POWER_LEVELS: Final = ["0", "1", "2", "3", "4"]
