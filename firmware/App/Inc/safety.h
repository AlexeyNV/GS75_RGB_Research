#pragma once
#include "current_sense.h"
typedef enum { DISARMED, IDLE, ACTIVE, FAULT } SafetyState;
typedef struct {
    SafetyState state;
    const char *fault, *reason;
    uint32_t arm_until, pulse_until, id, source, sink;
    bool done;
    CurrentSense current;
} Safety;
extern Safety safety;
const char *Safety_State(void);
void Safety_Init(void);
void Safety_Stop(const char *reason, bool disarm);
void Safety_Fault(const char *code);
void Safety_Tick(uint32_t now);
void Safety_Sample(uint32_t raw, uint32_t now);
const char *Safety_Arm(unsigned seconds, uint32_t now);
const char *Safety_Pair(unsigned source, unsigned sink, unsigned ms, uint32_t now);
const char *Safety_Clear(uint32_t now);
