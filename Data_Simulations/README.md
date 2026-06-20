# IHL Heat Pump Research Dataset

**Space ID:** `3dbed10b-9e88-4163-916d-3182e2ecc69f`
**Devices:** 4 registered devices (refer to `devices.csv`)

## 1. General Notes
* **Timestamps:** All timestamps are localized to UTC and formatted as `YYYY-MM-DD HH:MM:SS`.
* **Booleans:** Encoded as integer binaries (`1` = True / Active, `0` = False / Inactive).
* **Missing Values:** Represented as empty fields (nulls) in the CSV.

## 2. Experimental Time Windows
Data is segmented into specific time windows based on the dominant environmental conditions. Each window contains its own dedicated directory populated with identically structured files.

| Label | Start Date | End Date (inclusive) |
| :--- | :--- | :--- |
| **heating** | 2026-03-30 | 2026-04-05 |
| **cooling** | 2026-05-25 | 2026-05-31 |

## 3. Space Configuration
The dataset was collected from a climate-controlled room operating under an automated temperature strategy. The control loop activates heating or cooling toward the "occupied" event temperature when a `space_event` is active (or during its preheat phase). Outside of active events, the system maintains the minimum "unoccupied" temperature threshold.

* **Space Type:** `CLIMATE_CONTROLLED_ROOM`
* **Operation Mode:** `AUTOMATIC`
* **Temperature Process Strategy:** `CLIMATE_CONTROL`
* **Minimum Temperature (Unoccupied):** 11.0 °C
* **Event Temperature (Occupied):** 21.0 °C
* **Temperature Limit (Min/Max):** 11.0 °C / 30.0 °C
* **Preheat Duration:** 0 min
* **Daily Shutdown:** Inactive

---

## 4. File Manifest and Data Dictionaries

### 4.1. `heat_pump_snapshots.csv`
Contains high-resolution, unaggregated telemetry and process data sent directly by the heat pump controllers. Each row represents a single status report.

#### 4.1.1 Process Variables

| Variable Name | Data Type | Unit/Scale | Example | Description |
| :--- | :--- | :--- | :--- | :--- |
| `id` | UUID | UUIDv4 | `1aaa01ee-...` | Unique identifier for the telemetry snapshot. |
| `device_id` | UUID | UUIDv4 | `bdaf0e14-...` | Unique identifier mapping to the specific heat pump (`devices.csv`). |
| `space_id` | UUID | UUIDv4 | `3dbed10b-...` | Space identifier. |
| `last_seen_at` | Datetime | UTC | `2026-05-25 00:00:47` | Timestamp the controller transmitted the snapshot. |
| `status_is_enabled` | Boolean | 0 or 1 | `1` | Indicates if the main unit power is switched on. |
| `status_operation_mode` | String | Enum | `HEAT` | Current operating mode (`AUTO`, `HEAT`, `COOL`). |
| `status_target_temperature_in_celsius` | Numeric | °C | `18.0` | Active temperature setpoint. |
| `status_temperature_in_celsius` | Numeric | °C | `20.74` | Measured ambient room air temperature. |
| `status_humidity_in_percent` | Numeric | % | `46.9` | Measured relative room humidity. |
| `status_carbon_dioxide_in_ppm` | Numeric | ppm | `582` | Indoor CO₂ concentration. |
| `status_voc_in_micrograms_per_cubic_meter` | Numeric | µg/m³ | `203` | Indoor Volatile Organic Compounds concentration. |
| `status_temperature_supply_in_celsius` | Numeric | °C | `20.9` | Measured supply air temperature from the device. |
| `status_temperature_return_in_celsius` | Numeric | °C | `21.4` | Measured return air temperature back to the device. |
| `status_temperature_outside_in_celsius` | Numeric | °C | `16.3` | Measured outside air temperature at the unit's external sensor. |
| `status_air_flow_supply_in_percent` | Numeric | % | `50` | Supply fan operational output speed. |
| `status_air_flow_return_in_percent` | Numeric | % | `50` | Return fan operational output speed. |
| `status_is_heating_required` | Boolean | 0 or 1 | `0` | Active logical demand for heating cycle. |
| `status_is_cooling_required` | Boolean | 0 or 1 | `0` | Active logical demand for cooling cycle. |
| `status_heat_threshold_in_celsius` | Numeric | °C | `17.0` | Lower bound threshold triggering heating cycle. |
| `status_cool_threshold_in_celsius` | Numeric | °C | `19.0` | Upper bound threshold triggering cooling cycle. |
| `status_is_compressor_active` | Boolean | 0 or 1 | `0` | Indicates if the hardware compressor is actively running. |
| `status_is_defrost_active` | Boolean | 0 or 1 | `0` | Indicates if the system is executing an anti-icing defrost cycle. |
| `status_low_pressure_in_bar` | Numeric | bar | `12.1` | Refrigerant circuit pressure (low-side). |
| `status_high_pressure_in_bar` | Numeric | bar | `12.1` | Refrigerant circuit pressure (high-side). |

#### 4.1.2 Daily Shutdown Variables
These variables log targets when the scheduled daily/nightly shutdown window is active.

| Variable Name | Data Type | Unit/Scale | Description |
| :--- | :--- | :--- | :--- |
| `status_daily_shutdown_is_active` | Boolean | 0 or 1 | Indicates if the daily shutdown schedule is currently active. |
| `status_daily_shutdown_temperature_in_celsius` | Numeric | °C | Standby target temperature during shutdown. |
| `status_daily_shutdown_air_flow_supply_in_percent`| Numeric | % | Standby supply fan target output during shutdown. |
| `status_daily_shutdown_air_flow_return_in_percent`| Numeric | % | Standby return fan target output during shutdown. |

#### 4.1.3 Diagnostics and Health Overviews
Crucial for filtering out irregular or malfunctioning intervals from analytical models.

| Variable Name | Data Type | Example | Description |
| :--- | :--- | :--- | :--- |
| `status_is_status_active` | Boolean | `1` | The controller is actively reporting a status condition. |
| `status_is_alarm_active` | Boolean | `0` | High-level indicator that an alarm has been triggered. |
| `status_error_registers` | String | `"0,2,0,0"` | Raw alarm registers in Modbus standard (1901,1902,1903,1904). See Section 5. |
| `status_is_network_connected` | Boolean | `1` / null | Health of device network interface. |
| `status_has_network_error` | Boolean | `0` / null | Signals an existing network error. |
| `status_network_error_count` | Numeric | null | Cumulative count of network transmission errors. |
| `status_system_uptime_in_seconds` | Numeric | `8320640` | Total seconds elapsed since the device controller firmware booted. |
| `firmware_version` | String | `"0.2.0"` | Installed device controller software version. |
| `payload_version` | Numeric | `170209` | Incremental transmission iteration of the data payload. |

---

### 4.2. Subsidiary Data Files

* **`heat_pump_intervals.csv`**: Pre-aggregated time-series summaries.
    * `time_range`: Defines bucket width (`FIFTEEN_MINUTES`, `ONE_HOUR`, `SIX_HOURS`, `ONE_DAY`).
    * `interval_start_time` / `interval_end_time`: Bounding timestamps for the aggregation.
    * `median_*`: Median values taken across all telemetry snapshots within the interval bucket.
    * `*_highest_*`: Maximum limit observed within the bucket.
    * `was_adjusting_temperature`: Binary (`1` or `0`), active if heating/cooling was demanded at any point during the bucket.

* **`space_events.csv`**: Environmental context.
    * Logs periods where the room was occupied/booked. Dictates when the higher "event" (comfort) temperature was mandated instead of the default minimum baseline.
    * Includes `type` and `source` markers describing the origin of the event (e.g., calendar schedule import).

* **`devices.csv`**: Device registry.
    * Lookup table translating `device_id` into localized device types and installed hardware versions.

* **`power_draw.csv`**: Energy monitoring.
    * Records actual electrical power draw in kilowatts (kW), aligned with snapshot time indices in 5-minute sampling intervals.

---

## 5. Diagnostic Error Registers (`status_error_registers`)

The `status_error_registers` variable contains four 16-bit Modbus alarm registers encoded as a comma-separated string `A,B,C,D` mapping to registers `1901`, `1902`, `1903`, and `1904` respectively.

Each register functions as a bitfield. If bit `n` is set, the corresponding diagnostic alarm is active. Example: A payload of `"3,0,512,0"` indicates:
* Register 1901 (`3`): Bits 0 and 1 are active.
* Register 1903 (`512`): Bit 9 is active.
* `"0,0,0,0"` or null strings denote zero active alarms.

### Register 1901 Map
| Bit | Diagnostics Meaning | Bit | Diagnostics Meaning |
| :--- | :--- | :--- | :--- |
| **0** | Outside Air Humidity Sensor Fault | **8** | General Alarm |
| **1** | Circuit 1 High Pressure Switch Alarm | **9** | Temperature Sensor Fault |
| **2** | Circuit 1 Low Pressure Switch Alarm | **10** | Supply Fan Fault |
| **3** | Circuit 1 Compressor 1 Alarm | **11** | Return Fan Fault |
| **4** | Circuit 1 Compressor 2 Alarm | **12** | Supply Air Temperature Sensor Fault |
| **5** | Circuit 1 Compressor 3 Alarm | **13** | Return Air Temperature Sensor Fault |
| **6** | Circuit 1 Discharge Pressure Sensor Fault | **14** | Outside Air Temperature Sensor Fault |
| **7** | Circuit 1 Suction Pressure Sensor Fault | **15** | Return Air Humidity Sensor Fault |

### Register 1902 Map
| Bit | Diagnostics Meaning | Bit | Diagnostics Meaning |
| :--- | :--- | :--- | :--- |
| **0** | Filter Alarm 2 | **8** | Circuit 2 High Pressure Switch Alarm |
| **1** | Heat Recovery System Fault | **9** | Circuit 2 Low Pressure Switch Alarm |
| **2** | Hot Water Coil Fault | **10** | Circuit 2 Compressor 1 Alarm |
| **3** | Gas-Fired Fault | **11** | Circuit 2 Compressor 2 Alarm |
| **4** | Electrical Heater Fault | **12** | Circuit 2 Compressor 3 Alarm |
| **5** | Circuit 1 High Pressure Alarm | **13** | Circuit 2 Discharge Pressure Sensor Fault |
| **6** | Circuit 1 Low Pressure Alarm | **14** | Circuit 2 Suction Pressure Sensor Fault |
| **7** | Circuit 2 High Pressure Alarm | **15** | Filter Alarm 1 |

### Register 1903 Map
| Bit | Diagnostics Meaning | Bit | Diagnostics Meaning |
| :--- | :--- | :--- | :--- |
| **0** | Circuit 1 Compressor 1 Maintenance Alarm | **8** | Circuit 2 Low Pressure Alarm |
| **1** | Circuit 1 Compressor 2 Maintenance Alarm | **9** | Fire Detector Alarm |
| **2** | Circuit 1 Compressor 3 Maintenance Alarm | **10** | Supply Air Flow Sensor Fault |
| **3** | Circuit 2 Compressor 1 Maintenance Alarm | **11** | Return Air Flow Sensor Fault |
| **4** | Circuit 2 Compressor 2 Maintenance Alarm | **12** | Phase Fault Alarm |
| **5** | Circuit 2 Compressor 3 Maintenance Alarm | **13** | Pre-Electrical Heater Alarm |
| **6** | Circuit 1 Suction Temperature Sensor Fault | **14** | Supply Fan Maintenance Alarm |
| **7** | Circuit 2 Suction Temperature Sensor Fault | **15** | Exhaust Fan Maintenance Alarm |

### Register 1904 Map
| Bit | Diagnostics Meaning | Bit | Diagnostics Meaning |
| :--- | :--- | :--- | :--- |
| **0** | A2L Gas Detector Fault | **11** | Circuit 2 Electronic Expansion Valve Driver Connection Alarm |
| **1** | Additional Board Fault | **12** | Exhaust Air Flow Sensor Fault |
| **8** | Circuit 1 Electronic Expansion Valve Driver Alarm | **13** | Plate Heat Exchanger Temperature Sensor Fault |
| **9** | Circuit 2 Electronic Expansion Valve Driver Alarm | **14** | Circuit 1 Condenser Fan Alarm |
| **10** | Circuit 1 Electronic Expansion Valve Driver Connection Alarm | **15** | Circuit 2 Condenser Fan Alarm |
