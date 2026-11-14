#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "board_config.h"
typedef struct {
    uint32_t raw, mv, ua, at, sum, count, avg_ua, max_ua;
    uint32_t window[ADC_AVERAGE_COUNT], window_sum, window_count, window_index, mean_raw, mean_mv, mean_ua;
    bool valid;
} CurrentSense;
bool Current_Feed(CurrentSense *s, uint32_t raw, uint32_t now);
void Current_ResetPulse(CurrentSense *s);
