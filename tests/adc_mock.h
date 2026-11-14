#pragma once
#include <stdbool.h>
#include "main.h"
extern uint32_t mock_now, mock_reads, mock_starts, mock_stops;
extern bool mock_inflight, mock_start_fail, mock_stop_fail, mock_enable_fail;
void Mock_Reset(void);
void Mock_Complete(uint32_t raw);
