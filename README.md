<p align="center">
  <img src="https://raw.githubusercontent.com/mrclksr2409/VanMoof-integration/main/custom_components/vanmoof/brand/logo.png" alt="VanMoof" width="300">
</p>

# VanMoof für Home Assistant

Custom Integration, die alle verfügbaren Informationen deines VanMoof-E-Bikes in Home Assistant bringt.
Bei der Einrichtung werden **nur E-Mail-Adresse und Passwort** deines VanMoof-Kontos abgefragt.
Alle Räder des Kontos werden automatisch angelegt.

| Modell | Protokoll | Status |
|---|---|---|
| S3 / X3 (und ältere „Electrified“-Modelle) | Bluetooth, AES-Schlüssel aus der Cloud | unterstützt |
| S5 / A5 | Bluetooth, Ed25519-Zertifikat aus der Cloud | **Beta** (nur Lesen) |
| S6 / andere | – | nur Cloud-Daten |

## So funktioniert es

- **Cloud (VanMoof-Konto):** Die Integration meldet sich an und lädt Stammdaten wie Name, Modell, Farbe, Firmware und Diebstahlstatus.
- **Zugangsdaten fürs Rad:** Aus der Cloud kommen auch die Bluetooth-Zugangsdaten.
  - **S3/X3:** der Verschlüsselungsschlüssel des Rads.
  - **S5/A5:** Die Integration erzeugt ein eigenes Schlüsselpaar und lässt sich dafür von VanMoof ein Zertifikat ausstellen. Dieses wird vor Ablauf automatisch erneuert.
- **Bluetooth (lokal):** Live-Werte wie Akku, Kilometerstand und Schloss gibt es **nur per Bluetooth**.
  - Home Assistant verbindet sich in einem einstellbaren Intervall kurz mit dem Rad, liest alles aus und trennt die Verbindung wieder.
  - Das funktioniert mit dem eingebauten Bluetooth-Adapter oder über [ESPHome-Bluetooth-Proxies](https://esphome.io/components/bluetooth_proxy.html) in der Nähe des Abstellplatzes.
- **Offline-Betrieb:** Ist das Rad außer Reichweite, bleiben die letzten Werte erhalten und „In Reichweite“ steht auf *aus*. Sind die Zugangsdaten einmal gespeichert, läuft das Auslesen auch ohne Cloud weiter.

## Entitäten

| Entität | S3/X3 | S5/A5 |
|---|:-:|:-:|
| Akku, Modul-Akku | ✔ | ✔ |
| Kilometerstand, Geschwindigkeit | ✔ | ✔ |
| Unterstützungsstufe, Lichtmodus, Alarmmodus, Geschwindigkeitsregion | ✔ | ✔ |
| Gang (E-Shifter), Modulstatus, Einheitensystem | ✔ | – |
| Kalorien | – | ✔ |
| Lädt / Modul lädt | ✔ | – |
| Schloss | ✔ `lock` (Entsperren per HA) | ✔ Binärsensor |
| Auswahl: Unterstützungsstufe, Licht, Klingelton | ✔ | – |
| Buttons: Aktualisieren, Klingeln | ✔ / ✔ | ✔ / – |
| In Reichweite, Problem, Fehlercode, Firmware, Zuletzt gesehen | ✔ | ✔ |
| Als gestohlen gemeldet, Ortung, Firmware-Update, Smartmodul-Firmware (Cloud) | ✔ | ✔ |
| Strecke diese Woche (optional, aus der VanMoof-App) | ✔ | ✔ |

Abschließen ist nur physisch am Rad möglich (Kick-Lock). Das ist eine Eigenschaft von VanMoof, keine Einschränkung der Integration.

## Aktionen

### `vanmoof.save_settings` – Radeinstellungen speichern

Speichert Einstellungen per Bluetooth auf dem Rad (nur S3/X3). Alle angegebenen Werte werden in **einer** Bluetooth-Verbindung geschrieben, weggelassene Einstellungen bleiben unverändert. Danach werden die Werte neu vom Rad gelesen.

| Feld | Werte |
|---|---|
| `device_id` | ein oder mehrere VanMoof-Räder (Pflicht) |
| `power_level` | `0`–`4` (Unterstützungsstufe) |
| `light_mode` | `auto`, `on`, `off` |
| `bell_tone` | `sonar`, `bell`, `party`, `foghorn` |

Mindestens eine Einstellung muss angegeben werden. Beispiel für eine Automation:

```yaml
action: vanmoof.save_settings
data:
  device_id: 0123456789abcdef0123456789abcdef
  power_level: 2
  light_mode: auto
  bell_tone: bell
```

## Sprachen

Die Oberfläche der Integration (Einrichtung, Optionen, Entitäten, Aktionen und Fehlermeldungen) ist auf **Deutsch**, **Englisch** und **Niederländisch** übersetzt. Home Assistant wählt die Sprache automatisch passend zur eingestellten Sprache des Benutzers.

## Installation

1. **In HACS hinzufügen:** HACS → ⋮ → *Benutzerdefinierte Repositories* → `https://github.com/mrclksr2409/VanMoof-integration`, Typ *Integration*.
2. **Installieren:** „VanMoof“ installieren und Home Assistant neu starten.
3. **Einrichten:** *Einstellungen → Geräte & Dienste → Integration hinzufügen → VanMoof*, dann E-Mail und Passwort eingeben.

Manuell geht es auch: den Ordner `custom_components/vanmoof` nach `<config>/custom_components/` kopieren.

Icon und Logo liegen im Ordner `custom_components/vanmoof/brand/`. Home Assistant zeigt sie ab Version 2026.3 automatisch in der Integrationsübersicht an, ein Eintrag im Brands-Repository ist nicht nötig.

### Optionen

- **Bluetooth-Abfrageintervall** (60–3600 s, Standard 300 s): Während einer Abfrage kann sich die VanMoof-App nicht mit dem Rad verbinden. Scheitern mehrere Abfragen hintereinander, verlängert sich das Intervall automatisch, höchstens bis auf 1 h.
- **Wöchentliche Fahrtenstatistik:** lädt die Wochenzusammenfassung aus dem Backend der VanMoof-App.

## Datenschutz & Sicherheit

- **Gespeicherte Daten:** Passwort, Refresh-Token und die Bluetooth-Zugangsdaten liegen im Config-Entry von Home Assistant (`.storage/core.config_entries`). Das Passwort wird gespeichert, damit abgelaufene Tokens und S5-Zertifikate ohne dein Zutun erneuert werden können.
- **Diagnose-Downloads** schwärzen alle Schlüssel, Tokens, Rahmennummern und persönlichen Daten.
- **Kommunikation:** Die Integration spricht nur mit den offiziellen VanMoof-Servern und lokal mit deinem Rad.

## Bekannte Einschränkungen

- **Inoffizielle API:** Die VanMoof-Cloud-API ist nicht offiziell dokumentiert und kann sich ändern. Für den Login werden zwei bekannte API-Hosts genutzt, mit automatischem Fallback.
- **Leere Radliste:** Die Cloud liefert bei manchen Konten zeitweise keine Räder. Bereits gespeicherte Zugangsdaten bleiben dann erhalten.
- **S5/A5:** Das Protokoll ist nur teilweise erforscht. Aktuell werden Werte nur gelesen, nicht geschrieben.
- **Nur eine Bluetooth-Verbindung:** Das Rad akzeptiert jeweils nur eine Verbindung. Ist die App gerade verbunden, schlägt die Abfrage fehl und wird später wiederholt.

## Danksagung

Dieses Projekt ist eine eigenständige Implementierung. Das Protokollwissen stammt aus der Community:

- [quantsini/pymoof](https://github.com/quantsini/pymoof) und [SvenTiigi/VanMoofKit](https://github.com/SvenTiigi/VanMoofKit): S3/X3-Bluetooth
- [TimTheBeastNL/VanMoof-SA5-HomeAssistant](https://github.com/TimTheBeastNL/VanMoof-SA5-HomeAssistant) und [Knight1/vanmoof-ble](https://github.com/Knight1/vanmoof-ble): S5/A5-Protokoll
- [Knight1/vanmoof-api](https://github.com/Knight1/vanmoof-api): API-Dokumentation
- [BobMcGlobus/ha-vanmoof](https://github.com/BobMcGlobus/ha-vanmoof): Praxiserfahrungen mit S3-Verbindungen in Home Assistant

„VanMoof“ ist eine Marke ihres jeweiligen Inhabers. Dieses Projekt steht in keiner Verbindung zu VanMoof.

## Entwicklung

```bash
pip install -r requirements_test.txt
ruff check . && pytest
```
