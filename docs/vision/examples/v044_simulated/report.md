# LED49_SHORT_PULSE_TEST — COMPLETED

Session: 2026-11-18_120615_LED49_RGB_3f8f8b572ca4
SIMULATION: True (not a physical experiment when true)
UTC: 2026-11-18T12:06:15.486197+00:00; app 0.4.4; port SIMULATED
FW: 0.1.2
OFF confirmed by protocol: True
Reason: All 63 stages completed

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
      "role": "EXPERIMENT",
      "planned_start_ms": 0,
      "planned_end_ms": 5000
    },
    {
      "index": 2,
      "color": "RED",
      "duration_ms": 1000,
      "role": "SYNC_MARKER",
      "planned_start_ms": 5000,
      "planned_end_ms": 6000
    },
    {
      "index": 3,
      "color": "OFF",
      "duration_ms": 2000,
      "role": "EXPERIMENT",
      "planned_start_ms": 6000,
      "planned_end_ms": 8000
    },
    {
      "index": 4,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 8000,
      "planned_end_ms": 8200
    },
    {
      "index": 5,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 8200,
      "planned_end_ms": 8900
    },
    {
      "index": 6,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 8900,
      "planned_end_ms": 9100
    },
    {
      "index": 7,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 9100,
      "planned_end_ms": 9800
    },
    {
      "index": 8,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 9800,
      "planned_end_ms": 9900
    },
    {
      "index": 9,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 9900,
      "planned_end_ms": 10600
    },
    {
      "index": 10,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 10600,
      "planned_end_ms": 10700
    },
    {
      "index": 11,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 10700,
      "planned_end_ms": 11400
    },
    {
      "index": 12,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 11400,
      "planned_end_ms": 11700
    },
    {
      "index": 13,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 11700,
      "planned_end_ms": 12400
    },
    {
      "index": 14,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 12400,
      "planned_end_ms": 12500
    },
    {
      "index": 15,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 12500,
      "planned_end_ms": 13200
    },
    {
      "index": 16,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 13200,
      "planned_end_ms": 13500
    },
    {
      "index": 17,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 13500,
      "planned_end_ms": 14200
    },
    {
      "index": 18,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 14200,
      "planned_end_ms": 14300
    },
    {
      "index": 19,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 14300,
      "planned_end_ms": 15000
    },
    {
      "index": 20,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 15000,
      "planned_end_ms": 15100
    },
    {
      "index": 21,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 15100,
      "planned_end_ms": 15800
    },
    {
      "index": 22,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 15800,
      "planned_end_ms": 15900
    },
    {
      "index": 23,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 15900,
      "planned_end_ms": 16600
    },
    {
      "index": 24,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 16600,
      "planned_end_ms": 16900
    },
    {
      "index": 25,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 16900,
      "planned_end_ms": 17600
    },
    {
      "index": 26,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 17600,
      "planned_end_ms": 17900
    },
    {
      "index": 27,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 17900,
      "planned_end_ms": 18600
    },
    {
      "index": 28,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 18600,
      "planned_end_ms": 18700
    },
    {
      "index": 29,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 18700,
      "planned_end_ms": 19400
    },
    {
      "index": 30,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 19400,
      "planned_end_ms": 19700
    },
    {
      "index": 31,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 19700,
      "planned_end_ms": 20400
    },
    {
      "index": 32,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 20400,
      "planned_end_ms": 20600
    },
    {
      "index": 33,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 20600,
      "planned_end_ms": 21300
    },
    {
      "index": 34,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 21300,
      "planned_end_ms": 21400
    },
    {
      "index": 35,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 21400,
      "planned_end_ms": 22100
    },
    {
      "index": 36,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 22100,
      "planned_end_ms": 22300
    },
    {
      "index": 37,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 22300,
      "planned_end_ms": 23000
    },
    {
      "index": 38,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 23000,
      "planned_end_ms": 23300
    },
    {
      "index": 39,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 23300,
      "planned_end_ms": 24000
    },
    {
      "index": 40,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 24000,
      "planned_end_ms": 24100
    },
    {
      "index": 41,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 24100,
      "planned_end_ms": 24800
    },
    {
      "index": 42,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 24800,
      "planned_end_ms": 25000
    },
    {
      "index": 43,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 25000,
      "planned_end_ms": 25700
    },
    {
      "index": 44,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "planned_start_ms": 25700,
      "planned_end_ms": 25800
    },
    {
      "index": 45,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 25800,
      "planned_end_ms": 26500
    },
    {
      "index": 46,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 26500,
      "planned_end_ms": 26700
    },
    {
      "index": 47,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 26700,
      "planned_end_ms": 27400
    },
    {
      "index": 48,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 27400,
      "planned_end_ms": 27600
    },
    {
      "index": 49,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 27600,
      "planned_end_ms": 28300
    },
    {
      "index": 50,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 28300,
      "planned_end_ms": 28500
    },
    {
      "index": 51,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 28500,
      "planned_end_ms": 29200
    },
    {
      "index": 52,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 29200,
      "planned_end_ms": 29500
    },
    {
      "index": 53,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 29500,
      "planned_end_ms": 30200
    },
    {
      "index": 54,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 30200,
      "planned_end_ms": 30500
    },
    {
      "index": 55,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 30500,
      "planned_end_ms": 31200
    },
    {
      "index": 56,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 31200,
      "planned_end_ms": 31500
    },
    {
      "index": 57,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 31500,
      "planned_end_ms": 32200
    },
    {
      "index": 58,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "planned_start_ms": 32200,
      "planned_end_ms": 32500
    },
    {
      "index": 59,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 32500,
      "planned_end_ms": 33200
    },
    {
      "index": 60,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 33200,
      "planned_end_ms": 33400
    },
    {
      "index": 61,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "planned_start_ms": 33400,
      "planned_end_ms": 34100
    },
    {
      "index": 62,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "planned_start_ms": 34100,
      "planned_end_ms": 34300
    },
    {
      "index": 63,
      "color": "OFF",
      "duration_ms": 5000,
      "role": "EXPERIMENT",
      "planned_start_ms": 34300,
      "planned_end_ms": 39300
    }
  ],
  "actual": [
    {
      "index": 1,
      "color": "OFF",
      "duration_ms": 5000,
      "role": "EXPERIMENT",
      "start_ns": 16000000,
      "start_utc": "2026-11-18T12:06:15.501157+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 20000000,
      "end_ns": 5020000000,
      "end_utc": "2026-11-18T12:06:15.517114+00:00",
      "host_elapsed_ms": 5004.0
    },
    {
      "index": 2,
      "color": "RED",
      "duration_ms": 1000,
      "role": "SYNC_MARKER",
      "start_ns": 5020000000,
      "start_utc": "2026-11-18T12:06:15.521128+00:00",
      "status": "COMPLETED",
      "end_ns": 6054000000,
      "end_utc": "2026-11-18T12:06:15.579946+00:00",
      "host_elapsed_ms": 1034.0
    },
    {
      "index": 3,
      "color": "OFF",
      "duration_ms": 2000,
      "role": "EXPERIMENT",
      "start_ns": 6054000000,
      "start_utc": "2026-11-18T12:06:15.585930+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 6058000000,
      "end_ns": 8058000000,
      "end_utc": "2026-11-18T12:06:15.592911+00:00",
      "host_elapsed_ms": 2004.0
    },
    {
      "index": 4,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 8058000000,
      "start_utc": "2026-11-18T12:06:15.596900+00:00",
      "status": "COMPLETED",
      "end_ns": 8300000000,
      "end_utc": "2026-11-18T12:06:15.624826+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 5,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 8300000000,
      "start_utc": "2026-11-18T12:06:15.629814+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 8304000000,
      "end_ns": 9004000000,
      "end_utc": "2026-11-18T12:06:15.633803+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 6,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 9004000000,
      "start_utc": "2026-11-18T12:06:15.638789+00:00",
      "status": "COMPLETED",
      "end_ns": 9246000000,
      "end_utc": "2026-11-18T12:06:15.665715+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 7,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 9246000000,
      "start_utc": "2026-11-18T12:06:15.670703+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 9250000000,
      "end_ns": 9950000000,
      "end_utc": "2026-11-18T12:06:15.674717+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 8,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 9950000000,
      "start_utc": "2026-11-18T12:06:15.678706+00:00",
      "status": "COMPLETED",
      "end_ns": 10096000000,
      "end_utc": "2026-11-18T12:06:15.704640+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 9,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 10096000000,
      "start_utc": "2026-11-18T12:06:15.708600+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 10100000000,
      "end_ns": 10800000000,
      "end_utc": "2026-11-18T12:06:15.712590+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 10,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 10800000000,
      "start_utc": "2026-11-18T12:06:15.717577+00:00",
      "status": "COMPLETED",
      "end_ns": 10946000000,
      "end_utc": "2026-11-18T12:06:15.739520+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 11,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 10946000000,
      "start_utc": "2026-11-18T12:06:15.744505+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 10950000000,
      "end_ns": 11650000000,
      "end_utc": "2026-11-18T12:06:15.747497+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 12,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 11650000000,
      "start_utc": "2026-11-18T12:06:15.753480+00:00",
      "status": "COMPLETED",
      "end_ns": 11988000000,
      "end_utc": "2026-11-18T12:06:15.789384+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 13,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 11988000000,
      "start_utc": "2026-11-18T12:06:15.793373+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 11992000000,
      "end_ns": 12692000000,
      "end_utc": "2026-11-18T12:06:15.799357+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 14,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 12692000000,
      "start_utc": "2026-11-18T12:06:15.808334+00:00",
      "status": "COMPLETED",
      "end_ns": 12838000000,
      "end_utc": "2026-11-18T12:06:15.836259+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 15,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 12838000000,
      "start_utc": "2026-11-18T12:06:15.841247+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 12842000000,
      "end_ns": 13542000000,
      "end_utc": "2026-11-18T12:06:15.845235+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 16,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 13542000000,
      "start_utc": "2026-11-18T12:06:15.850221+00:00",
      "status": "COMPLETED",
      "end_ns": 13880000000,
      "end_utc": "2026-11-18T12:06:15.884131+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 17,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 13880000000,
      "start_utc": "2026-11-18T12:06:15.890116+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 13884000000,
      "end_ns": 14584000000,
      "end_utc": "2026-11-18T12:06:15.895130+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 18,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 14584000000,
      "start_utc": "2026-11-18T12:06:15.900088+00:00",
      "status": "COMPLETED",
      "end_ns": 14730000000,
      "end_utc": "2026-11-18T12:06:15.925021+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 19,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 14730000000,
      "start_utc": "2026-11-18T12:06:15.929009+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 14734000000,
      "end_ns": 15434000000,
      "end_utc": "2026-11-18T12:06:15.933016+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 20,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 15434000000,
      "start_utc": "2026-11-18T12:06:15.938011+00:00",
      "status": "COMPLETED",
      "end_ns": 15580000000,
      "end_utc": "2026-11-18T12:06:15.964914+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 21,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 15580000000,
      "start_utc": "2026-11-18T12:06:15.971896+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 15584000000,
      "end_ns": 16284000000,
      "end_utc": "2026-11-18T12:06:15.976882+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 22,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 16284000000,
      "start_utc": "2026-11-18T12:06:15.980870+00:00",
      "status": "COMPLETED",
      "end_ns": 16430000000,
      "end_utc": "2026-11-18T12:06:16.010791+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 23,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 16430000000,
      "start_utc": "2026-11-18T12:06:16.015807+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 16434000000,
      "end_ns": 17134000000,
      "end_utc": "2026-11-18T12:06:16.020793+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 24,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 17134000000,
      "start_utc": "2026-11-18T12:06:16.026750+00:00",
      "status": "COMPLETED",
      "end_ns": 17472000000,
      "end_utc": "2026-11-18T12:06:16.059662+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 25,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 17472000000,
      "start_utc": "2026-11-18T12:06:16.064647+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 17476000000,
      "end_ns": 18176000000,
      "end_utc": "2026-11-18T12:06:16.068636+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 26,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 18176000000,
      "start_utc": "2026-11-18T12:06:16.073651+00:00",
      "status": "COMPLETED",
      "end_ns": 18514000000,
      "end_utc": "2026-11-18T12:06:16.107533+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 27,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 18514000000,
      "start_utc": "2026-11-18T12:06:16.113544+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 18518000000,
      "end_ns": 19218000000,
      "end_utc": "2026-11-18T12:06:16.118503+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 28,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 19218000000,
      "start_utc": "2026-11-18T12:06:16.123488+00:00",
      "status": "COMPLETED",
      "end_ns": 19364000000,
      "end_utc": "2026-11-18T12:06:16.151414+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 29,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 19364000000,
      "start_utc": "2026-11-18T12:06:16.156401+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 19368000000,
      "end_ns": 20068000000,
      "end_utc": "2026-11-18T12:06:16.160392+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 30,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 20068000000,
      "start_utc": "2026-11-18T12:06:16.166375+00:00",
      "status": "COMPLETED",
      "end_ns": 20406000000,
      "end_utc": "2026-11-18T12:06:16.203302+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 31,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 20406000000,
      "start_utc": "2026-11-18T12:06:16.208263+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 20410000000,
      "end_ns": 21110000000,
      "end_utc": "2026-11-18T12:06:16.215245+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 32,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 21110000000,
      "start_utc": "2026-11-18T12:06:16.224219+00:00",
      "status": "COMPLETED",
      "end_ns": 21352000000,
      "end_utc": "2026-11-18T12:06:16.259125+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 33,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 21352000000,
      "start_utc": "2026-11-18T12:06:16.265110+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 21356000000,
      "end_ns": 22056000000,
      "end_utc": "2026-11-18T12:06:16.269098+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 34,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 22056000000,
      "start_utc": "2026-11-18T12:06:16.276080+00:00",
      "status": "COMPLETED",
      "end_ns": 22202000000,
      "end_utc": "2026-11-18T12:06:16.303008+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 35,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 22202000000,
      "start_utc": "2026-11-18T12:06:16.310997+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 22206000000,
      "end_ns": 22906000000,
      "end_utc": "2026-11-18T12:06:16.316973+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 36,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 22906000000,
      "start_utc": "2026-11-18T12:06:16.323953+00:00",
      "status": "COMPLETED",
      "end_ns": 23148000000,
      "end_utc": "2026-11-18T12:06:16.361853+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 37,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 23148000000,
      "start_utc": "2026-11-18T12:06:16.368832+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 23152000000,
      "end_ns": 23852000000,
      "end_utc": "2026-11-18T12:06:16.372823+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 38,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 23852000000,
      "start_utc": "2026-11-18T12:06:16.377836+00:00",
      "status": "COMPLETED",
      "end_ns": 24190000000,
      "end_utc": "2026-11-18T12:06:16.416705+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 39,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 24190000000,
      "start_utc": "2026-11-18T12:06:16.422689+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 24194000000,
      "end_ns": 24894000000,
      "end_utc": "2026-11-18T12:06:16.426678+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 40,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 24894000000,
      "start_utc": "2026-11-18T12:06:16.434656+00:00",
      "status": "COMPLETED",
      "end_ns": 25040000000,
      "end_utc": "2026-11-18T12:06:16.470561+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 41,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 25040000000,
      "start_utc": "2026-11-18T12:06:16.478540+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 25044000000,
      "end_ns": 25744000000,
      "end_utc": "2026-11-18T12:06:16.482528+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 42,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 25744000000,
      "start_utc": "2026-11-18T12:06:16.493497+00:00",
      "status": "COMPLETED",
      "end_ns": 25986000000,
      "end_utc": "2026-11-18T12:06:16.528406+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 43,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 25986000000,
      "start_utc": "2026-11-18T12:06:16.537382+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 25990000000,
      "end_ns": 26690000000,
      "end_utc": "2026-11-18T12:06:16.541370+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 44,
      "color": "RED",
      "duration_ms": 100,
      "role": "SHORT_PULSE",
      "start_ns": 26690000000,
      "start_utc": "2026-11-18T12:06:16.550345+00:00",
      "status": "COMPLETED",
      "end_ns": 26836000000,
      "end_utc": "2026-11-18T12:06:16.582260+00:00",
      "host_elapsed_ms": 146.0
    },
    {
      "index": 45,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 26836000000,
      "start_utc": "2026-11-18T12:06:16.589243+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 26840000000,
      "end_ns": 27540000000,
      "end_utc": "2026-11-18T12:06:16.593231+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 46,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 27540000000,
      "start_utc": "2026-11-18T12:06:16.599216+00:00",
      "status": "COMPLETED",
      "end_ns": 27782000000,
      "end_utc": "2026-11-18T12:06:16.659056+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 47,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 27782000000,
      "start_utc": "2026-11-18T12:06:16.667034+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 27786000000,
      "end_ns": 28486000000,
      "end_utc": "2026-11-18T12:06:16.673018+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 48,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 28486000000,
      "start_utc": "2026-11-18T12:06:16.680000+00:00",
      "status": "COMPLETED",
      "end_ns": 28728000000,
      "end_utc": "2026-11-18T12:06:16.719891+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 49,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 28728000000,
      "start_utc": "2026-11-18T12:06:16.726872+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 28732000000,
      "end_ns": 29432000000,
      "end_utc": "2026-11-18T12:06:16.730862+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 50,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 29432000000,
      "start_utc": "2026-11-18T12:06:16.740836+00:00",
      "status": "COMPLETED",
      "end_ns": 29674000000,
      "end_utc": "2026-11-18T12:06:16.777738+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 51,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 29674000000,
      "start_utc": "2026-11-18T12:06:16.787711+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 29678000000,
      "end_ns": 30378000000,
      "end_utc": "2026-11-18T12:06:16.792697+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 52,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 30378000000,
      "start_utc": "2026-11-18T12:06:16.802672+00:00",
      "status": "COMPLETED",
      "end_ns": 30716000000,
      "end_utc": "2026-11-18T12:06:16.852537+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 53,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 30716000000,
      "start_utc": "2026-11-18T12:06:16.859519+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 30720000000,
      "end_ns": 31420000000,
      "end_utc": "2026-11-18T12:06:16.863507+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 54,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 31420000000,
      "start_utc": "2026-11-18T12:06:16.869493+00:00",
      "status": "COMPLETED",
      "end_ns": 31758000000,
      "end_utc": "2026-11-18T12:06:16.915370+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 55,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 31758000000,
      "start_utc": "2026-11-18T12:06:16.923346+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 31762000000,
      "end_ns": 32462000000,
      "end_utc": "2026-11-18T12:06:16.928333+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 56,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 32462000000,
      "start_utc": "2026-11-18T12:06:16.938306+00:00",
      "status": "COMPLETED",
      "end_ns": 32800000000,
      "end_utc": "2026-11-18T12:06:16.981193+00:00",
      "host_elapsed_ms": 338.0
    },
    {
      "index": 57,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 32800000000,
      "start_utc": "2026-11-18T12:06:16.991166+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 32804000000,
      "end_ns": 33504000000,
      "end_utc": "2026-11-18T12:06:16.995155+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 58,
      "color": "RED",
      "duration_ms": 300,
      "role": "SHORT_PULSE",
      "start_ns": 33504000000,
      "start_utc": "2026-11-18T12:06:17.005129+00:00",
      "status": "COMPLETED",
      "end_ns": 33838000000,
      "end_utc": "2026-11-18T12:06:17.051006+00:00",
      "host_elapsed_ms": 334.0
    },
    {
      "index": 59,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 33838000000,
      "start_utc": "2026-11-18T12:06:17.058984+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 33842000000,
      "end_ns": 34542000000,
      "end_utc": "2026-11-18T12:06:17.063971+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 60,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 34542000000,
      "start_utc": "2026-11-18T12:06:17.071949+00:00",
      "status": "COMPLETED",
      "end_ns": 34784000000,
      "end_utc": "2026-11-18T12:06:17.112841+00:00",
      "host_elapsed_ms": 242.0
    },
    {
      "index": 61,
      "color": "OFF",
      "duration_ms": 700,
      "role": "EXPERIMENT",
      "start_ns": 34784000000,
      "start_utc": "2026-11-18T12:06:17.119821+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 34788000000,
      "end_ns": 35488000000,
      "end_utc": "2026-11-18T12:06:17.123810+00:00",
      "host_elapsed_ms": 704.0
    },
    {
      "index": 62,
      "color": "RED",
      "duration_ms": 200,
      "role": "SHORT_PULSE",
      "start_ns": 35488000000,
      "start_utc": "2026-11-18T12:06:17.133783+00:00",
      "status": "COMPLETED",
      "end_ns": 35726000000,
      "end_utc": "2026-11-18T12:06:17.171683+00:00",
      "host_elapsed_ms": 238.0
    },
    {
      "index": 63,
      "color": "OFF",
      "duration_ms": 5000,
      "role": "EXPERIMENT",
      "start_ns": 35726000000,
      "start_utc": "2026-11-18T12:06:17.177667+00:00",
      "status": "COMPLETED",
      "off_confirmed_ns": 35730000000,
      "end_ns": 40730000000,
      "end_utc": "2026-11-18T12:06:17.192624+00:00",
      "host_elapsed_ms": 5004.0
    }
  ]
}
```

Electrical measurements: see measurements.csv; full TX/RX: events.jsonl.
Safety / diagnostics / video / alignment: see session.json.
