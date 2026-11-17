"""Bounded, immutable LED49-only video scenario."""
from dataclasses import dataclass, asdict

NAME = 'LED49_RGB_VIDEO_TEST'
VERSION = '0.4.1'
SINKS = {'RED': 32, 'GREEN': 33, 'BLUE': 34}
EXPECTED_UA = {'RED': 1035, 'GREEN': 886, 'BLUE': 797}
CONDITIONS = ('u13_open', 'r1_2700_ohm', 'original_rgb_board', 'power_accessible', 'operator_present')


@dataclass(frozen=True)
class Stage:
    color: str
    duration_ms: int


def scenario(initial_ms=5000, photo_ms=5000, pause_ms=3000, final_ms=5000):
    for value in (initial_ms, photo_ms, pause_ms, final_ms):
        if type(value) is not int:
            raise ValueError('Durations must be integer milliseconds')
    if not 100 <= photo_ms <= 10000:
        raise ValueError('PHOTO requires 100..10000 ms')
    if any(not 100 <= value <= 60000 for value in (initial_ms, pause_ms, final_ms)):
        raise ValueError('OFF pauses require 100..60000 ms')
    return [Stage('OFF', initial_ms), Stage('RED', photo_ms), Stage('OFF', pause_ms),
            Stage('GREEN', photo_ms), Stage('OFF', pause_ms), Stage('BLUE', photo_ms), Stage('OFF', final_ms)]


def planned(stages):
    offset = 0
    result = []
    for index, stage in enumerate(stages):
        result.append(dict(index=index + 1, **asdict(stage), planned_start_ms=offset,
                           planned_end_ms=offset + stage.duration_ms))
        offset += stage.duration_ms
    return result
