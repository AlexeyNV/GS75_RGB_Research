#include "adc_mock.h"
#include "adc_status.h"
#include "safety.h"
#include "cli.h"
#include "board.h"
#include <assert.h>
#include <string.h>
#include <stdio.h>
static bool enabled;
static char output[4096];
void Board_Off(void) { enabled=false; }
void Board_Address(uint8_t a,uint8_t b,uint8_t c,uint8_t d) { (void)a;(void)b;(void)c;(void)d; assert(!enabled); }
void Board_Enable(void) { enabled=true; }
void Board_DelayUs(uint32_t us) { (void)us; }
bool Board_Check(void) { return !enabled; }
uint32_t Board_GpioA(void) { return enabled?1u<<10:0; }
uint32_t Board_GpioC(void) { return enabled?1u<<12:0; }
uint32_t Board_Lock(void) { return 0; }
void Board_Unlock(uint32_t key) { (void)key; }
void USB_Queue(const char *s) { assert(strlen(output)+strlen(s)<sizeof output); strcat(output,s); }
static void reset(void) { Mock_Reset(); Safety_Init(); CLI_Reset(); ADC_Init(); output[0]=0; }
static void command(const char *s,const char *want) {
    output[0]=0; CLI_Receive((const uint8_t*)s,(uint32_t)strlen(s)); CLI_Poll(mock_now);
    if(!strstr(output,want)) { fprintf(stderr,"Expected %s, got %s\n",want,output); assert(0); }
}
static ADCStatus diagnostic(void) { ADCStatus d; ADC_GetStatus(&d); return d; }
static void sample(uint32_t time,uint32_t raw) {
    mock_now=time; ADC_Poll(); assert(mock_inflight);
    Mock_Complete(raw); ADC_Poll(); assert(!diagnostic().pending);
}
int main(void) {
    reset(); assert(ADC_STALE_MS==5); /* do not mask failures by loosening safety */
    command("ADCSTATUS\n","HAS_SAMPLE=0 AGE_MS=0 VALID=0");
    command("SELFTEST\n","ERR ADC_INVALID"); command("ARM 60\n","ERR ADC_INVALID");
    /* 10 seconds in DISARMED, no USB required, one result per ms. */
    for(uint32_t t=0;t<10000;t++) { sample(t,2); Safety_Tick(t); assert(!enabled && safety.state==DISARMED); }
    ADCStatus d=diagnostic(); assert(d.samples==10000 && d.valid_samples==10000 && !d.errors);
    assert(mock_reads==10000 && mock_starts==10000 && safety.current.at==9999);
    command("SELFTEST\n","SELFTEST=PASS"); command("CURRENT\n","AGE_MS=0 VALID=1");
    command("ADCSTATUS\n","SAMPLES=10000 VALID_SAMPLES=10000 ERRORS=0");
    command("ADCSTATUS extra\n","ERR SYNTAX"); command("HELP\n","ADCSTATUS");
    command("ARM 60\n","OK ARM_TIMEOUT_S=60"); assert(!enabled);
    command("PAIR 12 34 300\n","ACK ID=1"); assert(enabled);
    for(uint32_t t=10000;t<10299;t++) { Safety_Tick(t); sample(t,100); }
    Safety_Tick(10299); assert(!enabled && safety.done && safety.state==IDLE);

    /* Pending result must not be cleared/retriggered by a new ms. */
    reset(); ADC_Poll(); for(unsigned i=0;i<100;i++) ADC_Poll(); assert(mock_starts==1 && mock_reads==0);
    mock_now=1; ADC_Poll(); assert(mock_starts==1);
    Mock_Complete(2); uint32_t sr=mock_adc.SR;
    d=diagnostic(); command("ADCSTATUS\n","EOC=1 OVR=0");
    assert(mock_adc.SR==sr && mock_reads==0 && d.pending);
    ADC_Poll(); assert(mock_reads==1 && mock_starts==2 && safety.current.at==0);

    /* EOC+OVR and OVR alone discard DR, clear flags, latch FAULT, resume sampling only. */
    for(unsigned eoc=0;eoc<2;eoc++) {
        reset(); sample(0,2); command("ARM 60\n","OK"); command("PAIR 1 2 300\n","ACK");
        mock_now=1; ADC_Poll(); mock_adc.SR=ADC_FLAG_OVR|(eoc?ADC_FLAG_EOC:0);
        ADC_Poll(); d=diagnostic(); assert(d.overruns==1 && d.errors==1 && d.samples==1 && mock_reads==1);
        assert(!(mock_adc.SR&(ADC_FLAG_OVR|ADC_FLAG_EOC)) && !enabled && safety.state==FAULT && !safety.current.valid);
        command("ADCSTATUS\n","OVR_COUNT=1");
        sample(2,2); assert(safety.state==FAULT && !enabled);
        command("ARM 60\n","ERR FAULT_LATCHED"); command("SELFTEST\n","ERR FAULT_LATCHED");
        command("CLEARFAULT\n","OK DISARMED"); assert(!enabled);
    }
    /* Stuck conversion, including an EOC arriving too late, must not refresh age. */
    for(unsigned eoc=0;eoc<2;eoc++) {
        reset(); sample(0,2); command("ARM 60\n","OK"); command("PAIR 1 2 300\n","ACK");
        mock_now=1; ADC_Poll(); mock_now=3; if(eoc) Mock_Complete(2);
        ADC_Poll(); assert(!enabled && safety.state==FAULT && diagnostic().timeouts==1 && mock_reads==1);
        assert(safety.current.at==0); sample(4,2); assert(!enabled && safety.state==FAULT);
    }
    /* Entire main/ADC service stops: independent SysTick still trips after 5 ms. */
    reset(); sample(0,2); command("ARM 60\n","OK"); command("PAIR 1 2 300\n","ACK");
    Safety_Tick(5); assert(enabled); Safety_Tick(6); assert(!enabled && safety.state==FAULT);
    mock_now=6; command("ADCSTATUS\n","AGE_MS=6 VALID=0");
    reset(); sample(0,2); mock_now=6; command("SELFTEST\n","ERR ADC_INVALID"); command("ARM 60\n","ERR ADC_INVALID");

    reset(); ADC_Poll(); Mock_Complete(4095); ADC_Poll();
    assert(!enabled && safety.state==FAULT && diagnostic().invalid_samples==1 && diagnostic().valid_samples==0);
    command("SELFTEST\n","ERR FAULT_LATCHED");
    reset(); sample(0,2); command("ARM 60\n","OK"); command("PAIR 1 2 300\n","ACK");
    sample(1,300); assert(!enabled && !strcmp(safety.fault,"OVERCURRENT"));
    reset(); mock_start_fail=true; ADC_Poll(); assert(diagnostic().start_errors==1 && !enabled && safety.state==FAULT);
    mock_start_fail=false; sample(1,2); assert(safety.state==FAULT);
    reset(); mock_enable_fail=true; ADC_Poll(); assert(diagnostic().start_errors==1 && safety.state==FAULT);
    reset(); mock_stop_fail=true; mock_adc.SR=ADC_FLAG_OVR; ADC_Poll(); assert(diagnostic().stop_errors==1 && diagnostic().errors==2);
    reset(); mock_now=UINT32_MAX; ADC_Init(); sample(UINT32_MAX,2); sample(0,2);
    assert(diagnostic().samples==2 && diagnostic().errors==0 && safety.current.at==0);
    puts("PASS ADC: 1 kHz DISARMED, EOC/OVR, timeout/recovery, status, SELFTEST/ARM, stale/off, invalid/overcurrent, HAL errors, wraparound");
    return 0;
}
