#include "cli.h"
#include "safety.h"
#include "board.h"
#include "board_config.h"
#include "mux4051.h"
#include "adc_status.h"
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include <limits.h>
static char rx[96], pending[4][96];
static unsigned len, head, tail;
static bool discard, overflow, stop_requested;
void CLI_Send(const char *text) { USB_Queue(text); }
static void reply(const char *fmt,...) {
    char text[512]; va_list args; va_start(args,fmt); vsnprintf(text,sizeof text,fmt,args); va_end(args); CLI_Send(text);
}
void CLI_Reset(void) { len=head=tail=0; discard=overflow=stop_requested=false; }
void CLI_Receive(const uint8_t *data,uint32_t length) {
    /* Constant bounded work per byte. OFF bypasses a full command queue. */
    for (uint32_t i=0;i<length;i++) {
        unsigned char c=data[i];
        if (c=='\n') {
            rx[len]=0;
            if (!discard) {
                unsigned n=len; if(n && rx[n-1]=='\r') rx[--n]=0;
                while(n && (rx[n-1]==' ' || rx[n-1]=='\t')) rx[--n]=0;
                char *command=rx;
                while(*command==' ' || *command=='\t') command++;
                if (!strcmp(command,"OFF") || !strcmp(command,"DISARM")) {
                    Safety_Stop("OFF",true); head=tail=0; stop_requested=true;
                } else if (n) {
                    unsigned next=(head+1)%4;
                    if (next==tail) { overflow=true; Safety_Stop("RX_OVERFLOW",true); head=tail=0; }
                    else { memcpy(pending[head],rx,n+1); head=next; }
                }
            } else { overflow=true; Safety_Stop("RX_INVALID",true); }
            len=0; discard=false;
        } else if (c==0 || (c<32 && c!='\r' && c!='\t') || c>126 || len>=sizeof(rx)-1) discard=true;
        else if (!discard) rx[len++]=(char)c;
    }
}
static bool number(const char *s,unsigned *out) {
    unsigned v=0;
    if(!s || !*s) return false;
    while(*s) { if(*s<'0'||*s>'9'||v>(UINT_MAX-(unsigned)(*s-'0'))/10) return false; v=v*10+(unsigned)(*s++-'0'); }
    *out=v; return true;
}
static void execute(char *line,uint32_t now) {
    char *tokens[5], *p=line; unsigned n=0,a=0,b=0,c=0;
    while(*p) {
        while(*p==' '||*p=='\t') p++;
        if(!*p) break;
        if(n==5) { CLI_Send("ERR SYNTAX\r\n"); return; }
        tokens[n++]=p;
        while(*p && *p!=' ' && *p!='\t') p++;
        if(*p) *p++=0;
    }
    if(!n) return;
    const char *cmd=tokens[0],*err=0;
    if (!strcmp(cmd,"ARM")) {
        if(n!=2||!number(tokens[1],&a)) err="SYNTAX";
        else { err=Safety_Arm(a,now); if(!err) reply("OK ARM_TIMEOUT_S=%u\r\n",a); }
    } else if (!strcmp(cmd,"PAIR")) {
        if(n!=4||!number(tokens[1],&a)||!number(tokens[2],&b)||!number(tokens[3],&c)) err="SYNTAX";
        else { err=Safety_Pair(a,b,c,now); if(!err) reply("ACK ID=%lu SRC=%u SNK=%u DURATION_MS=%u\r\n",(unsigned long)safety.id,a,b,c); }
    } else if(n!=1) err="SYNTAX";
    else if(!strcmp(cmd,"OFF")||!strcmp(cmd,"DISARM")) { Safety_Stop("OFF",true); CLI_Send("OK DISARMED\r\n"); }
    else if(!strcmp(cmd,"PING")) CLI_Send("PONG\r\n");
    else if(!strcmp(cmd,"HELP")) CLI_Send("OK COMMANDS=PING,INFO,HELP,STATUS,OFF,ARM_s,DISARM,PAIR_src_snk_ms,CURRENT,ADCSTATUS,DUMP,SELFTEST,CLEARFAULT\r\n");
    else if(!strcmp(cmd,"INFO")) reply("FW: %s\r\nMCU: STM32F411RET6\r\nBOARD: %s\r\nINTERFACE: USB_CDC\r\nFPC_PINS: %u\r\nMUX_SOURCE: 5x74HCT4051\r\nMUX_SINK: 5x74HCT4051\r\nADC: PA0\r\nSHUNT_OHM: %u\r\nCURRENT_LIMIT_RESISTOR_OHM: %u\r\nSTATE: %s\r\nEND INFO\r\n",FW_VERSION,BOARD_NAME,FPC_PINS,SHUNT_OHM,LIMIT_RESISTOR_OHM,Safety_State());
    else if(!strcmp(cmd,"STATUS")) reply("OK STATE=%s SRC=%lu SNK=%lu SRC_EN=%lu SNK_EN=%lu REMAIN_MS=%lu FAULT=%s\r\n",Safety_State(),(unsigned long)safety.source,(unsigned long)safety.sink,(unsigned long)((Board_GpioA()>>10)&1),(unsigned long)((Board_GpioC()>>12)&1),(unsigned long)(safety.state==ACTIVE?safety.pulse_until-now:0),safety.fault);
    else if(!strcmp(cmd,"CURRENT")) {
        if(!safety.current.valid) err="ADC_INVALID";
        else reply("OK RAW=%lu MV=%lu CURRENT_UA=%lu AVG_RAW=%lu AVG_MV=%lu AVG_UA=%lu AGE_MS=%lu VALID=%u\r\n",(unsigned long)safety.current.raw,(unsigned long)safety.current.mv,(unsigned long)safety.current.ua,(unsigned long)safety.current.mean_raw,(unsigned long)safety.current.mean_mv,(unsigned long)safety.current.mean_ua,(unsigned long)(now-safety.current.at),now-safety.current.at<=ADC_STALE_MS);
    } else if(!strcmp(cmd,"ADCSTATUS")) {
        ADCStatus d; ADC_GetStatus(&d);
        reply("OK ADCSTATUS MODE=SINGLE_SW PERIOD_MS=%u EOC=%u OVR=%u PENDING=%u STARTS=%lu SAMPLES=%lu VALID_SAMPLES=%lu ERRORS=%lu OVR_COUNT=%lu TIMEOUTS=%lu START_ERRORS=%lu STOP_ERRORS=%lu INVALID_SAMPLES=%lu HAS_SAMPLE=%u AGE_MS=%lu VALID=%u SR=0x%lx LAST_SR=0x%lx CR2=0x%lx HAL_ERROR=0x%lx\r\n",
            ADC_SAMPLE_PERIOD_MS,(unsigned)((d.sr>>1)&1),(unsigned)((d.sr>>5)&1),(unsigned)d.pending,
            (unsigned long)d.starts,(unsigned long)d.samples,(unsigned long)d.valid_samples,(unsigned long)d.errors,
            (unsigned long)d.overruns,(unsigned long)d.timeouts,(unsigned long)d.start_errors,(unsigned long)d.stop_errors,
            (unsigned long)d.invalid_samples,(unsigned)d.has_sample,(unsigned long)(d.has_sample?now-d.last_sample_ms:0),
            (unsigned)(d.has_sample && safety.current.valid && now-d.last_sample_ms<=ADC_STALE_MS),
            (unsigned long)d.sr,(unsigned long)d.last_sr,(unsigned long)d.cr2,(unsigned long)d.hal_error);
    } else if(!strcmp(cmd,"DUMP")) {
        MuxAddress s={0},t={0}; (void)Mux_Map(safety.source,&s); (void)Mux_Map(safety.sink,&t);
        reply("OK GPIOA_IDR=0x%lx GPIOC_IDR=0x%lx SRC_BANK=%u SRC_CH=%u SNK_BANK=%u SNK_CH=%u RAW=%lu FAULT=%s\r\n",(unsigned long)Board_GpioA(),(unsigned long)Board_GpioC(),s.bank,s.channel,t.bank,t.channel,(unsigned long)safety.current.raw,safety.fault);
    } else if(!strcmp(cmd,"SELFTEST")) {
        if(safety.state==ACTIVE) err="BUSY";
        else if(safety.state==FAULT) err="FAULT_LATCHED";
        else if(!Board_Check()) err="GPIO_INVALID";
        else if(!safety.current.valid||now-safety.current.at>ADC_STALE_MS) err="ADC_INVALID";
        else reply("OK SELFTEST=PASS STATE=%s FAULT=%s PHYSICAL_MUX=UNTESTED\r\n",Safety_State(),safety.fault);
    } else if(!strcmp(cmd,"CLEARFAULT")) { err=Safety_Clear(now); if(!err) CLI_Send("OK DISARMED\r\n"); }
    else err="UNKNOWN_COMMAND";
    if(err) reply("ERR %s\r\n",err);
}
void CLI_Poll(uint32_t now) {
    uint32_t key=Board_Lock();
    Safety_Tick(now);
    if(safety.done) {
        CurrentSense *c=&safety.current;
        if(c->count) reply("DONE ID=%lu STATE=OFF CURRENT_AVG_UA=%lu CURRENT_MAX_UA=%lu SAMPLES=%lu FAULT=%s REASON=%s\r\n",(unsigned long)safety.id,(unsigned long)c->avg_ua,(unsigned long)c->max_ua,(unsigned long)c->count,safety.fault,safety.reason);
        else reply("DONE ID=%lu STATE=OFF MEASUREMENT=UNAVAILABLE FAULT=%s REASON=%s\r\n",(unsigned long)safety.id,safety.fault,safety.reason);
        safety.done=false;
    }
    if(stop_requested) { CLI_Send("OK DISARMED\r\n"); stop_requested=false; }
    if(overflow) { CLI_Send("ERR RX_OVERFLOW\r\n"); overflow=false; }
    if(tail!=head) { char line[96]; strcpy(line,pending[tail]); tail=(tail+1)%4; execute(line,now); }
    Board_Unlock(key);
}
