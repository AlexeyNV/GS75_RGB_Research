#pragma once
#include <stdint.h>
#include <stdbool.h>
typedef struct {
    uint32_t starts, samples, valid_samples, errors, overruns, timeouts;
    uint32_t start_errors, stop_errors, invalid_samples, last_sample_ms;
    uint32_t sr, last_sr, cr2, hal_error;
    bool pending, has_sample;
} ADCStatus;
/* Snapshot only: must never read DR or clear EOC/OVR. */
void ADC_GetStatus(ADCStatus *out);
