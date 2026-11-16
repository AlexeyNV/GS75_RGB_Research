"""One-shot hardware test: interrupt a GS75 RGB PAIR pulse with OFF.

Run only with a 1 kohm dummy load between verified KP27 and KP35,
with the MSI RGB board disconnected and U13 open.

This tests USB responses and reported switch state. It does NOT measure
physical BANK_EN waveforms or prove the actual OFF propagation delay.
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class TestFailure(RuntimeError):
    pass


class Session:
    def __init__(self, port):
        self.port = port
        self.partial = bytearray()
        self.events = []
        self.t0 = time.monotonic()

    def record(self, direction, value):
        event = {"t_ms": round((time.monotonic() - self.t0) * 1000, 2),
                 "direction": direction, "line": value}
        self.events.append(event)
        print(f"{event['t_ms']:9.2f} ms {direction:>2}  {value}", flush=True)
        return event

    def send(self, command):
        self.port.write(command.encode("ascii") + b"\n")
        self.port.flush()
        return self.record("TX", command)

    def read_line(self, deadline):
        while time.monotonic() < deadline:
            # Keep any trailing bytes: several USB CDC replies may arrive
            # together in a single read (notably DONE and OK DISARMED).
            if b"\n" in self.partial:
                line_bytes, _, rest = self.partial.partition(b"\n")
                self.partial = bytearray(rest)
                line = line_bytes.decode("ascii", errors="replace").rstrip("\r")
                if line:
                    self.record("RX", line)
                    return line
                continue
            data = self.port.read(256)
            self.partial.extend(data)
            if len(self.partial) > 4096:
                raise TestFailure("Device sent an oversized response")
        raise TestFailure("Timed out waiting for a device response")

    def expect(self, predicate, timeout_s=2):
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = self.read_line(deadline)
            if line.startswith("ERR "):
                raise TestFailure(f"Device error: {line}")
            if predicate(line):
                return line
        raise TestFailure("Required response not received")


def has_field(line, key, expected):
    return re.search(r"(?:^|\s)" + re.escape(key) + r"=" + re.escape(str(expected)) + r"(?:\s|$)", line) is not None


def verify_off(session):
    session.send("STATUS")
    line = session.expect(lambda s: s.startswith("OK STATE="))
    if not (has_field(line, "STATE", "DISARMED") and
            has_field(line, "SRC_EN", 0) and has_field(line, "SNK_EN", 0) and
            has_field(line, "FAULT", "NONE")):
        raise TestFailure(f"Unsafe or unexpected STATUS: {line}")


def run(session, delay_ms):
    # Force a safe state before arming. USB OFF is not a substitute for
    # verifying the physical assembly and installing a real dummy load.
    session.send("OFF")
    session.expect(lambda s: s == "OK DISARMED")
    verify_off(session)

    session.send("ADCSTATUS")
    adc = session.expect(lambda s: s.startswith("OK ADCSTATUS "))
    if not has_field(adc, "VALID", 1):
        raise TestFailure("ADC is stale/invalid; refusing to arm")

    session.send("SELFTEST")
    selftest = session.expect(lambda s: s.startswith("OK SELFTEST="))
    if not has_field(selftest, "SELFTEST", "PASS"):
        raise TestFailure("SELFTEST did not pass; refusing to arm")

    session.send("ARM 60")
    session.expect(lambda s: s == "OK ARM_TIMEOUT_S=60")
    session.send("PAIR 27 35 300")
    ack = session.expect(lambda s: s.startswith("ACK ID="), timeout_s=1)
    match = re.search(r"\bID=(\d+)\b", ack)
    if not match or not has_field(ack, "SRC", 27) or not has_field(ack, "SNK", 35):
        raise TestFailure(f"Unexpected ACK: {ack}")
    pair_id = int(match.group(1))

    time.sleep(delay_ms / 1000)
    session.send("OFF")
    done = None
    off_reply = False
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and (done is None or not off_reply):
        line = session.read_line(deadline)
        if line.startswith("ERR "):
            raise TestFailure(f"Device error: {line}")
        if line == "OK DISARMED":
            off_reply = True
        if line.startswith("DONE ID="):
            if not has_field(line, "ID", pair_id):
                raise TestFailure(f"Wrong DONE ID: {line}")
            done = line
    if done is None or not off_reply:
        raise TestFailure("Missing matching DONE and/or OFF acknowledgement")

    verify_off(session)
    if not (has_field(done, "REASON", "OFF") and
            has_field(done, "FAULT", "NONE") and has_field(done, "STATE", "OFF")):
        raise TestFailure(f"Pair did not end with REASON=OFF: {done}")
    match = re.search(r"\bSAMPLES=(\d+)\b", done)
    if match and int(match.group(1)) >= 300:
        raise TestFailure(f"Samples reached full pulse duration: {done}")
    return done


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--port", required=True, help="COM19, COM7, /dev/ttyACM0, etc.")
    p.add_argument("--delay-ms", type=int, default=50,
                   help="Delay after ACK before OFF (default 50 ms)")
    p.add_argument("--log", type=Path, help="Optional JSON test log path")
    p.add_argument("--confirm-load", action="store_true",
                   help="Confirm 1 kohm on KP27/KP35, original RGB disconnected, U13 open")
    args = p.parse_args()
    if not args.confirm_load:
        p.error("For hardware safety, first verify the test setup and pass --confirm-load")
    if not 10 <= args.delay_ms <= 100:
        p.error("--delay-ms must be between 10 and 100")

    try:
        import serial
    except ImportError:
        p.error("pyserial is required: python -m pip install pyserial")

    result = {"timestamp_utc": datetime.now(timezone.utc).isoformat(),
              "firmware_expected": "0.1.1", "pair": [27, 35],
              "load_ohm_nominal": 1000, "duration_ms": 300,
              "delay_after_ack_ms_requested": args.delay_ms,
              "u13_open_operator_confirmed": True,
              "hardware_en_waveforms_measured": False,
              "port": args.port, "result": "FAIL"}
    session = None
    try:
        with serial.Serial(args.port, 115200, timeout=0.01, write_timeout=1) as port:
            session = Session(port)
            # Do not open this port in the existing interactive serial_console.py simultaneously.
            try:
                result["done"] = run(session, args.delay_ms)
                result["result"] = "PASS_PROTOCOL"
                print("PASS: OFF ended the pulse; firmware reported both BANK_EN disabled.")
                print("Physical OFF delay still requires oscilloscope/logic-analyzer verification.")
            finally:
                # Safe command on every exit; it does not override a latched FAULT.
                try:
                    session.send("OFF")
                except (serial.SerialException, OSError):
                    pass
    except (TestFailure, serial.SerialException, OSError) as exc:
        result["error"] = str(exc)
        print(f"FAIL: {exc}", file=sys.stderr)
    finally:
        result["events"] = session.events if session else []
        if args.log:
            args.log.parent.mkdir(parents=True, exist_ok=True)
            args.log.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(f"Log: {args.log}")
    return 0 if result["result"] == "PASS_PROTOCOL" else 1


if __name__ == "__main__":
    sys.exit(main())
