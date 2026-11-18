"""Bounded, immutable LED49-only video scenario."""
from dataclasses import dataclass, asdict
import random

NAME = 'LED49_RGB_VIDEO_TEST'
VERSION = '0.4.4'
SHORT_NAME = 'LED49_SHORT_PULSE_TEST'
SINKS = {'RED': 32, 'GREEN': 33, 'BLUE': 34}
EXPECTED_UA = {'RED': 1035, 'GREEN': 886, 'BLUE': 797}
CONDITIONS = ('u13_open', 'r1_2700_ohm', 'original_rgb_board', 'power_accessible', 'operator_present')


@dataclass(frozen=True)
class Stage:
    color: str
    duration_ms: int
    role: str = 'EXPERIMENT'


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


def short_scenario(color='RED', durations=(100, 200, 300), repeats=10, pause_ms=700,
                   initial_ms=5000, final_ms=5000, order='ordered', seed=49, marker=False):
    """Only bounded LED49 PHOTO presets, never arbitrary contacts or commands."""
    if color not in SINKS or order not in ('ordered', 'shuffled') or type(marker) is not bool:
        raise ValueError('Invalid short-pulse color/order/marker')
    if (not durations or len(set(durations)) != len(durations)
            or any(type(d) is not int or d not in (100, 200, 300) for d in durations)):
        raise ValueError('Choose distinct durations from 100/200/300 ms')
    if type(repeats) is not int or not 1 <= repeats <= 30:
        raise ValueError('Repeats must be 1..30')
    if type(seed) is not int or not 0 <= seed <= 2147483647:
        raise ValueError('Seed must be 0..2147483647')
    for value in (initial_ms, pause_ms, final_ms):
        if type(value) is not int or not 100 <= value <= 60000:
            raise ValueError('OFF pauses require 100..60000 ms')
    pulses = [duration for duration in durations for _ in range(repeats)]
    if order == 'shuffled': random.Random(seed).shuffle(pulses)
    stages = [Stage('OFF', initial_ms)]
    if marker: stages += [Stage('RED', 1000, 'SYNC_MARKER'), Stage('OFF', 2000)]
    for index, duration in enumerate(pulses):
        stages.append(Stage(color, duration, 'SHORT_PULSE'))
        if index < len(pulses)-1: stages.append(Stage('OFF', pause_ms))
    stages.append(Stage('OFF', final_ms))
    return stages


def validate_scenario(stages, name=NAME, config=None):
    if name == NAME:
        expected = scenario(stages[0].duration_ms, stages[1].duration_ms,
                            stages[2].duration_ms, stages[-1].duration_ms)
    elif name == SHORT_NAME:
        expected = short_scenario(**(config or {}))
    else:
        raise ValueError('Unknown bounded experiment scenario')
    if list(stages) != expected: raise ValueError('Scenario differs from authorized preset')
    return expected
