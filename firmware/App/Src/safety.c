#include "safety.h"
#include "mux4051.h"
#include "board.h"
#include "board_config.h"
#include <string.h>
Safety safety;
const char *Safety_State(void) {
    static const char *names[]={"DISARMED","IDLE","ACTIVE","FAULT"};
    return names[safety.state];
}
static bool expired(uint32_t now, uint32_t until) { return (int32_t)(now-until)>=0; }
void Safety_Init(void) {
    Mux_AllOff(); memset(&safety,0,sizeof safety); safety.fault="NONE"; safety.reason="NONE";
}
void Safety_Stop(const char *reason, bool disarm) {
    Mux_AllOff();
    if (safety.state==ACTIVE) { safety.done=true; safety.reason=reason; }
    if (safety.state!=FAULT) safety.state=disarm?DISARMED:(safety.state==DISARMED?DISARMED:IDLE);
}
void Safety_Fault(const char *code) {
    Safety_Stop(code,true); safety.fault=code; safety.state=FAULT;
}
void Safety_Tick(uint32_t now) {
    if ((safety.state==IDLE || safety.state==ACTIVE) && expired(now,safety.arm_until)) Safety_Stop("ARM_EXPIRED",true);
    if (safety.state==ACTIVE) {
        if (!safety.current.valid || now-safety.current.at>ADC_STALE_MS) Safety_Fault("ADC_INVALID");
        else if (expired(now,safety.pulse_until)) Safety_Stop("TIMEOUT",false);
    }
}
void Safety_Sample(uint32_t raw, uint32_t now) {
    if (!Current_Feed(&safety.current,raw,now)) { Safety_Fault("ADC_INVALID"); return; }
    if (safety.state==ACTIVE) {
        CurrentSense *c=&safety.current;
        c->sum+=c->ua; c->count++; c->avg_ua=c->sum/c->count;
        if (c->ua>c->max_ua) c->max_ua=c->ua;
    }
    if (safety.current.ua>CURRENT_TRIP_UA) Safety_Fault("OVERCURRENT");
}
const char *Safety_Arm(unsigned seconds,uint32_t now) {
    if (safety.state==FAULT) return "FAULT_LATCHED";
    if (safety.state==ACTIVE || safety.done) return "BUSY";
    if (!seconds || seconds>ARM_MAX_S) return "INVALID_TIMEOUT";
    if (!safety.current.valid || now-safety.current.at>ADC_STALE_MS) return "ADC_INVALID";
    if (!Board_Check()) { Safety_Fault("GPIO_INVALID"); return "GPIO_INVALID"; }
    safety.arm_until=now+seconds*1000u; safety.state=IDLE; return 0;
}
const char *Safety_Pair(unsigned src,unsigned snk,unsigned ms,uint32_t now) {
    Safety_Tick(now);
    if (safety.state==FAULT) return "FAULT_LATCHED";
    if (src<1 || src>FPC_PINS || snk<1 || snk>FPC_PINS) return "INVALID_PIN";
    if (src==snk) return "SAME_PIN";
    if (ms<PULSE_MIN_MS || ms>PULSE_MAX_MS) return "INVALID_DURATION";
    if (safety.state==ACTIVE || safety.done) return "BUSY";
    if (safety.state!=IDLE) return "NOT_ARMED";
    if (!safety.current.valid || now-safety.current.at>ADC_STALE_MS) return "ADC_INVALID";
    if (!Board_Check()) { Safety_Fault("GPIO_INVALID"); return "GPIO_INVALID"; }
    safety.source=src; safety.sink=snk; safety.id++; safety.pulse_until=now+ms;
    Current_ResetPulse(&safety.current);
    if (!Mux_Select(src,snk)) { Safety_Fault("GPIO_INVALID"); return "GPIO_INVALID"; }
    safety.state=ACTIVE; return 0;
}
const char *Safety_Clear(uint32_t now) {
    if (safety.state==ACTIVE) { Safety_Stop("CLEARFAULT",true); return "BUSY"; }
    Mux_AllOff();
    if (safety.state==ACTIVE || safety.done) return "BUSY";
    if (!Board_Check()) return "GPIO_INVALID";
    if (!safety.current.valid || now-safety.current.at>ADC_STALE_MS || safety.current.ua>CURRENT_TRIP_UA) return "ADC_INVALID";
    safety.state=DISARMED; safety.fault="NONE"; return 0;
}
