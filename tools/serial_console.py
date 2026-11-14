"""Interactive USB CDC console; one reader thread prints async ACK/DONE/ERR."""
import argparse
import threading
import sys


def classify(line):
    word = line.split(' ', 1)[0]
    return word if word in ('ACK', 'DONE', 'ERR') else 'REPLY'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True, help='e.g. COM7')
    args = parser.parse_args()
    import serial
    stop = threading.Event()
    try:
        with serial.Serial(args.port, 115200, timeout=0.2, write_timeout=1) as port:
            def reader():
                buffer = bytearray()
                try:
                    while not stop.is_set():
                        chunk = port.read(256)
                        for c in chunk:
                            if c == 10:
                                line = buffer.decode('ascii', errors='replace').rstrip('\r')
                                buffer.clear()
                                print(f'[{classify(line)}] {line}', flush=True)
                            elif len(buffer) < 4096:
                                buffer.append(c)
                            else:
                                buffer.clear()
                                print('[ERR] Host receive line too long', file=sys.stderr)
                except (serial.SerialException, OSError) as exc:
                    if not stop.is_set():
                        print(f'[ERR] {exc}', file=sys.stderr)
                    stop.set()
            thread = threading.Thread(target=reader, daemon=True)
            thread.start()
            try:
                print('Commands: HELP; exit: quit or Ctrl+C')
                while not stop.is_set():
                    line = input('> ')
                    if line.strip().lower() in ('quit', 'exit'):
                        break
                    payload = line.encode('ascii')
                    if len(payload) > 94 or b'\r' in payload or b'\n' in payload or b'\0' in payload:
                        print('[ERR] Command must be one ASCII line, <=94 characters')
                        continue
                    port.write(payload + b'\n')
            except (EOFError, KeyboardInterrupt):
                pass
            finally:
                try:
                    port.write(b'OFF\n')
                except (serial.SerialException, OSError):
                    pass
                stop.set()
                thread.join(timeout=1)
    except (serial.SerialException, OSError, UnicodeError) as exc:
        print(f'[ERR] {exc}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
