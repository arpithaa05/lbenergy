# IHL Heat Pump Research Dataset

- Space ID: `3dbed10b-9e88-4163-916d-3182e2ecc69f`
- Devices: see `devices.csv` (4 devices)
- All timestamps are in **UTC**, format `YYYY-MM-DD HH:MM:SS`.
- Booleans are encoded as `1` / `0`, missing values as empty fields.

## Time windows

| Label | From | To (inclusive) |
|---|---|---|
| heating | 2026-03-30 | 2026-04-05 |
| cooling | 2026-05-25 | 2026-05-31 |

Each window has its own directory containing `heat_pump_snapshots.csv`,
`heat_pump_intervals.csv`, `space_events.csv` and `power_draw.csv` files.

## Space configuration

These are the control settings of the space **at export time**:

| Setting | Value                   |
|---|-------------------------|
| Space type | CLIMATE_CONTROLLED_ROOM |
| Mode | AUTOMATIC               |
| Temperature process strategy | CLIMATE_CONTROL         |
| Minimum temperature (unoccupied) | 11 °C                   |
| Event temperature (occupied) | 21 °C                   |
| Temperature limit (min / max) | 11 / 30 °C              |
| Preheat duration | 0 min                   |
| Daily shutdown | no                      |

The control loop works roughly as follows: while a `space_event` is active (or during the
preheat window before it), the space is heated/cooled towards the event temperature;
outside events it is kept at the minimum temperature.

## Files

### heat_pump_snapshots.csv

One row per status report sent by a heat pump device (full resolution, not aggregated).

Process data:

| Column | Description |
|---|---|
| id | Row UUID |
| device_id | Reporting device, see devices.csv |
| space_id | Space UUID |
| last_seen_at | Time the device reported this status (UTC) |
| status_is_enabled | Unit switched on |
| status_operation_mode | `AUTO`, `HEAT` or `COOL` |
| status_target_temperature_in_celsius | Current setpoint (°C) |
| status_temperature_in_celsius | Measured room air temperature (°C) |
| status_humidity_in_percent | Relative humidity (%) |
| status_carbon_dioxide_in_ppm | CO₂ concentration (ppm) |
| status_voc_in_micrograms_per_cubic_meter | Volatile organic compounds (µg/m³) |
| status_temperature_supply_in_celsius | Supply air temperature (°C) |
| status_temperature_return_in_celsius | Return air temperature (°C) |
| status_temperature_outside_in_celsius | Outside air temperature at the unit (°C) |
| status_air_flow_supply_in_percent | Supply fan air flow (%) |
| status_air_flow_return_in_percent | Return fan air flow (%) |
| status_is_heating_required | Device demands heating |
| status_is_cooling_required | Device demands cooling |
| status_heat_threshold_in_celsius | Below this temperature the unit heats (°C) |
| status_cool_threshold_in_celsius | Above this temperature the unit cools (°C) |
| status_is_compressor_active | Compressor running |
| status_is_defrost_active | Defrost cycle running |
| status_low_pressure_in_bar | Refrigerant circuit low-side pressure (bar) |
| status_high_pressure_in_bar | Refrigerant circuit high-side pressure (bar) |
| status_daily_shutdown_* | State/targets while the daily night-shutdown window is active |

Diagnostics (useful to filter out unhealthy periods):

| Column | Description |
|---|---|
| status_is_status_active | Unit reports an active status condition |
| status_is_alarm_active | Unit reports an active alarm |
| status_error_registers | Raw alarm registers, see below |
| status_is_network_connected / status_has_network_error / status_network_error_count | Device connectivity health |
| status_system_uptime_in_seconds | Seconds since the device controller booted |
| firmware_version / payload_version | Device software versions |

### heat_pump_intervals.csv

Pre-aggregated statistics per device and time bucket. `time_range` names the bucket
length (`FIFTEEN_MINUTES`, `ONE_HOUR`, `SIX_HOURS` or `ONE_DAY`); `interval_start_time`
and `interval_end_time` bound the bucket. `median_*` columns are medians over all
snapshots in the bucket, `*_highest_*` columns are maxima. `was_adjusting_temperature`
is `1` if the device demanded heating or cooling at some point during the bucket.

### space_events.csv

Periods during which the space was booked/occupied, i.e. when the comfort ("event")
temperature applied instead of the minimum temperature. `type` and `source` describe the kind and origin (e.g. calendar import)
of the event.

### devices.csv

Lookup table mapping `device_id`, the device type and hardware
version.

### power_draw.csv

Device power draw (kW) at the time of the snapshot in 5-minute intervals.

## Error registers

`status_error_registers` contains the raw values of four 16-bit Modbus alarm registers
of the heat pump as a comma-separated string in the order `1901,1902,1903,1904`,
e.g. `3,0,512,0`. Each value is a bitfield: bit *n* set means the corresponding alarm
is active. In the example, register 1901 has bits 0 and 1 set (Outside Air Humidity
Sensor Fault + Circuit 1 High Pressure Switch Alarm) and register 1903 has bit 9 set
(Fire Detector Alarm). `0,0,0,0` (or all empty) means no alarms.

#### Register 1901

| Bit | Meaning |
|---|---|
| 0 | Outside Air Humidity Sensor Fault |
| 1 | Circuit 1 High Pressure Switch Alarm |
| 2 | Circuit 1 Low Pressure Switch Alarm |
| 3 | Circuit 1 Compressor 1 Alarm |
| 4 | Circuit 1 Compressor 2 Alarm |
| 5 | Circuit 1 Compressor 3 Alarm |
| 6 | Circuit 1 Discharge Pressure Sensor Fault |
| 7 | Circuit 1 Suction Pressure Sensor Fault |
| 8 | General Alarm |
| 9 | Temperature Sensor Fault |
| 10 | Supply Fan Fault |
| 11 | Return Fan Fault |
| 12 | Supply Air Temperature Sensor Fault |
| 13 | Return Air Temperature Sensor Fault |
| 14 | Outside Air Temperature Sensor Fault |
| 15 | Return Air Humidity Sensor Fault |

#### Register 1902

| Bit | Meaning |
|---|---|
| 0 | Filter Alarm 2 |
| 1 | Heat Recovery System Fault |
| 2 | Hot Water Coil Fault |
| 3 | Gas-Fired Fault |
| 4 | Electrical Heater Fault |
| 5 | Circuit 1 High Pressure Alarm |
| 6 | Circuit 1 Low Pressure Alarm |
| 7 | Circuit 2 High Pressure Alarm |
| 8 | Circuit 2 High Pressure Switch Alarm |
| 9 | Circuit 2 Low Pressure Switch Alarm |
| 10 | Circuit 2 Compressor 1 Alarm |
| 11 | Circuit 2 Compressor 2 Alarm |
| 12 | Circuit 2 Compressor 3 Alarm |
| 13 | Circuit 2 Discharge Pressure Sensor Fault |
| 14 | Circuit 2 Suction Pressure Sensor Fault |
| 15 | Filter Alarm 1 |

#### Register 1903

| Bit | Meaning |
|---|---|
| 0 | Circuit 1 Compressor 1 Maintenance Alarm |
| 1 | Circuit 1 Compressor 2 Maintenance Alarm |
| 2 | Circuit 1 Compressor 3 Maintenance Alarm |
| 3 | Circuit 2 Compressor 1 Maintenance Alarm |
| 4 | Circuit 2 Compressor 2 Maintenance Alarm |
| 5 | Circuit 2 Compressor 3 Maintenance Alarm |
| 6 | Circuit 1 Suction Temperature Sensor Fault |
| 7 | Circuit 2 Suction Temperature Sensor Fault |
| 8 | Circuit 2 Low Pressure Alarm |
| 9 | Fire Detector Alarm |
| 10 | Supply Air Flow Sensor Fault |
| 11 | Return Air Flow Sensor Fault |
| 12 | Phase Fault Alarm |
| 13 | Pre-Electrical Heater Alarm |
| 14 | Supply Fan Maintenance Alarm |
| 15 | Exhaust Fan Maintenance Alarm |

#### Register 1904

| Bit | Meaning |
|---|---|
| 0 | A2L Gas Detector Fault |
| 1 | Additional Board Fault |
| 8 | Circuit 1 Electronic Expansion Valve Driver Alarm |
| 9 | Circuit 2 Electronic Expansion Valve Driver Alarm |
| 10 | Circuit 1 Electronic Expansion Valve Driver Connection Alarm |
| 11 | Circuit 2 Electronic Expansion Valve Driver Connection Alarm |
| 12 | Exhaust Air Flow Sensor Fault |
| 13 | Plate Heat Exchanger Temperature Sensor Fault |
| 14 | Circuit 1 Condenser Fan Alarm |
| 15 | Circuit 2 Condenser Fan Alarm |
