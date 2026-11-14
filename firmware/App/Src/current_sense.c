#include "current_sense.h"
#include "board_config.h"
void Current_ResetPulse(CurrentSense *s) { s->sum=0; s->count=0; s->avg_ua=0; s->max_ua=0; }
bool Current_Feed(CurrentSense *s, uint32_t raw, uint32_t now) {
    s->valid = false;
    if (raw >= 4095u) return false; /* rail saturation is invalid */
    s->raw=raw; s->mv=(raw*VREF_MV+2047u)/4095u;
    s->ua=(uint32_t)(((uint64_t)raw*VREF_MV*1000u+4095u*SHUNT_OHM/2)/(4095u*SHUNT_OHM));
    s->window_sum-=s->window[s->window_index];
    s->window[s->window_index]=raw; s->window_sum+=raw;
    s->window_index=(s->window_index+1)%ADC_AVERAGE_COUNT;
    if(s->window_count<ADC_AVERAGE_COUNT) s->window_count++;
    s->mean_raw=s->window_sum/s->window_count;
    s->mean_mv=(s->mean_raw*VREF_MV+2047u)/4095u;
    s->mean_ua=(uint32_t)(((uint64_t)s->mean_raw*VREF_MV*1000u+4095u*SHUNT_OHM/2)/(4095u*SHUNT_OHM));
    s->at=now; s->valid=true;
    return true;
}
