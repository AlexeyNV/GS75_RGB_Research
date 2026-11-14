#pragma once
#define FW_VERSION "0.1.0"
#define BOARD_NAME "GS75_RGB_Research"
#define FPC_PINS 40u
#define PULSE_MIN_MS 10u
#define PULSE_MAX_MS 300u
#define ARM_MAX_S 60u
#define VREF_MV 3300u
#define SHUNT_OHM 100u
#define LIMIT_RESISTOR_OHM 2700u
/* U13 MUST be open. 5.25 V / (2700 + 100) < 1875 uA. */
#define CURRENT_TRIP_UA 2000u
#define ADC_STALE_MS 5u
#define ADC_AVERAGE_COUNT 8u
#define MUX_SETTLE_US 10u
