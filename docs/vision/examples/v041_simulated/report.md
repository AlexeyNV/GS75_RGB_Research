# LED49_RGB_VIDEO_TEST — COMPLETED

Session: 2026-11-17_070800_LED49_RGB_066b1860f48d
UTC: 2026-11-17T07:08:00.314444+00:00; app 0.4.1; port SIMULATED — NO HARDWARE
FW: 0.1.2
OFF confirmed by protocol: True
Reason: All seven stages completed

Physical conditions: operator declarations only. IWDG disabled; keep power accessible.
TX/ACK/DONE timestamps include USB/host latency; optical synchronization is UNALIGNED.

Plan and actual intervals (ns/ms):
```json
{
  "planned": [
    {
      "index": 1,
      "color": "OFF",
      "duration_ms": 5000,
      "planned_start_ms": 0,
      "planned_end_ms": 5000
    },
    {
      "index": 2,
      "color": "RED",
      "duration_ms": 5000,
      "planned_start_ms": 5000,
      "planned_end_ms": 10000
    },
    {
      "index": 3,
      "color": "OFF",
      "duration_ms": 3000,
      "planned_start_ms": 10000,
      "planned_end_ms": 13000
    },
    {
      "index": 4,
      "color": "GREEN",
      "duration_ms": 5000,
      "planned_start_ms": 13000,
      "planned_end_ms": 18000
    },
    {
      "index": 5,
      "color": "OFF",
      "duration_ms": 3000,
      "planned_start_ms": 18000,
      "planned_end_ms": 21000
    },
    {
      "index": 6,
      "color": "BLUE",
      "duration_ms": 5000,
      "planned_start_ms": 21000,
      "planned_end_ms": 26000
    },
    {
      "index": 7,
      "color": "OFF",
      "duration_ms": 5000,
      "planned_start_ms": 26000,
      "planned_end_ms": 31000
    }
  ],
  "actual": [
    {
      "index": 1,
      "color": "OFF",
      "duration_ms": 5000,
      "start_ns": 48000000,
      "start_utc": "2026-11-17T07:08:00.334650+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 52000000,
      "end_ns": 5052000000,
      "end_utc": "2026-11-17T07:08:00.404023+00:00",
      "host_elapsed_ms": 5004.0
    },
    {
      "index": 2,
      "color": "RED",
      "duration_ms": 5000,
      "start_ns": 5052000000,
      "start_utc": "2026-11-17T07:08:00.422942+00:00",
      "status": "COMPLETED",
      "end_ns": 10078000000,
      "end_utc": "2026-11-17T07:08:00.676366+00:00",
      "host_elapsed_ms": 5026.0
    },
    {
      "index": 3,
      "color": "OFF",
      "duration_ms": 3000,
      "start_ns": 10078000000,
      "start_utc": "2026-11-17T07:08:00.679387+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 10082000000,
      "end_ns": 13082000000,
      "end_utc": "2026-11-17T07:08:00.718253+00:00",
      "host_elapsed_ms": 3004.0
    },
    {
      "index": 4,
      "color": "GREEN",
      "duration_ms": 5000,
      "start_ns": 13082000000,
      "start_utc": "2026-11-17T07:08:00.740194+00:00",
      "status": "COMPLETED",
      "end_ns": 18108000000,
      "end_utc": "2026-11-17T07:08:00.963901+00:00",
      "host_elapsed_ms": 5026.0
    },
    {
      "index": 5,
      "color": "OFF",
      "duration_ms": 3000,
      "start_ns": 18108000000,
      "start_utc": "2026-11-17T07:08:00.966891+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 18112000000,
      "end_ns": 21112000000,
      "end_utc": "2026-11-17T07:08:01.012767+00:00",
      "host_elapsed_ms": 3004.0
    },
    {
      "index": 6,
      "color": "BLUE",
      "duration_ms": 5000,
      "start_ns": 21112000000,
      "start_utc": "2026-11-17T07:08:01.027850+00:00",
      "status": "COMPLETED",
      "end_ns": 26138000000,
      "end_utc": "2026-11-17T07:08:01.242660+00:00",
      "host_elapsed_ms": 5026.0
    },
    {
      "index": 7,
      "color": "OFF",
      "duration_ms": 5000,
      "start_ns": 26138000000,
      "start_utc": "2026-11-17T07:08:01.245652+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 26142000000,
      "end_ns": 31142000000,
      "end_utc": "2026-11-17T07:08:01.316490+00:00",
      "host_elapsed_ms": 5004.0
    }
  ]
}
```

Electrical measurements: see measurements.csv; full TX/RX: events.jsonl.
Safety / diagnostics / video / alignment: see session.json.
