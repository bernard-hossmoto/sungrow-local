# Register map

All registers are **input registers, read with function code 4**. The addresses below are
the ones sent on the wire. Sungrow's protocol document counts from 1, so its numbers are one
higher (wire 13001 = document 13002). Multi-word values are **low word first**.

Verified on a Sungrow SH15T with WiNet-S. The energy balance closes on that system:
production = direct use + charged + exported, and consumption = direct use + discharged +
imported, both matching the iSolarCloud app to 0.1 kWh.

## Instantaneous values

| Wire address | Document | Value | Type | Unit |
|---|---|---|---|---|
| 5016 | 5017 | total DC (PV) power | U32 | W |
| 5213 | 5214 | battery power, negative = charging | S32 | W |
| 5600 | 5601 | meter active power, positive = import | S32 | W |
| 13019 | 13020 | battery voltage | U16 | 0.1 V |
| 13021 | 13022 | battery power (unsigned, not used) | U16 | W |
| 13022 | 13023 | battery state of charge | U16 | 0.1 % |
| 13023 | 13024 | battery health | U16 | 0.1 % |
| 13024 | 13025 | battery temperature | S16 | 0.1 °C |
| 13038 | 13039 | battery capacity | U16 | 0.1 kWh |

## Energy counters

Daily counters reset at midnight in the inverter's clock.

| Value | Today (wire) | Total (wire) | Unit |
|---|---|---|---|
| PV production | 13001 (U16) | 13002 (U32) | 0.1 kWh |
| direct consumption of PV | 13016 (U16) | 13017 (U32) | 0.1 kWh |
| battery discharge | 13025 (U16) | 13026 (U32) | 0.1 kWh |
| grid import | 13035 (U16) | 13036 (U32) | 0.1 kWh |
| battery charge | 13039 (U16) | 13040 (U32) | 0.1 kWh |
| grid export | 13044 (U16) | 13045 (U32) | 0.1 kWh |

## Not used

| Wire address | Document | Value | Why |
|---|---|---|---|
| 13007 | 13008 | load power | read 0 W or values that did not match the other readings on the tested system; the house load is calculated as PV + battery + grid instead |

## Requests used per reading

sungrow-local reads five blocks per cycle, with one connection and a pause between them:

| Start | Count | Content |
|---|---|---|
| 5016 | 2 | PV power |
| 5213 | 2 | battery power |
| 5600 | 2 | meter power |
| 13000 | 30 | daily and total counters, battery state |
| 13033 | 14 | capacity, import, charge, export |
