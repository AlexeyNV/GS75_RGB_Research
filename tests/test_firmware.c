#include "mux4051.h"
#include "safety.h"
#include "board_config.h"
#include "board.h"
#include "cli.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
static bool enabled, gpio_ok=true;
static unsigned addresses, enables;
static char output[32768];
void Board_Off(void) { enabled=false; }
void Board_Address(uint8_t a,uint8_t b,uint8_t c,uint8_t d) { assert(!enabled); assert(a<5&&b<8&&c<5&&d<8); addresses++; }
void Board_Enable(void) { enabled=true; enables++; }
void Board_DelayUs(uint32_t us) { assert(!enabled); assert(us>=10); }
bool Board_Check(void) { return !enabled && gpio_ok; }
uint32_t Board_GpioA(void) { return enabled?1u<<10:0; }
uint32_t Board_GpioC(void) { return enabled?1u<<12:0; }
uint32_t Board_Lock(void) { return 0; }
void Board_Unlock(uint32_t key) { (void)key; }
void USB_Queue(const char *s) { assert(strlen(output)+strlen(s)<sizeof output); strcat(output,s); }
static void reset(void) { Safety_Init(); CLI_Reset(); output[0]=0; gpio_ok=true; Safety_Sample(0,0); }
static void feed(const char *s,uint32_t now) { output[0]=0; CLI_Receive((const uint8_t*)s,(uint32_t)strlen(s)); CLI_Poll(now); }
static void expect(const char *s) { if(!strstr(output,s)) { fprintf(stderr,"Expected %s; got %s\n",s,output); assert(0); } }
int main(void) {
    CurrentSense sense={0}; uint32_t previous=0;
    for(unsigned raw=0;raw<4095;raw++) {
        assert(Current_Feed(&sense,raw,raw)); assert(sense.ua>=previous);
        assert(sense.ua==(uint32_t)(((uint64_t)raw*3300000+204750)/409500));
        previous=sense.ua;
    }
    assert(previous>32900 && !Current_Feed(&sense,4095,0));
    MuxAddress a;
    bool seen[5][8]={{false}};
    assert(!Mux_Map(0,&a)&&!Mux_Map(41,&a)&&!Mux_Map(UINT_MAX,&a)&&!Mux_Map(1,0));
    for(unsigned pin=1;pin<=40;pin++) {
        assert(Mux_Map(pin,&a)); assert(a.bank==4-(pin-1)/8 && a.channel==(pin-1)%8);
        assert(!seen[a.bank][a.channel]); seen[a.bank][a.channel]=true;
    }
    unsigned pairs=0;
    for(unsigned src=1;src<=40;src++) for(unsigned snk=1;snk<=40;snk++) {
        assert(Mux_ValidPair(src,snk)==(src!=snk));
        if(src!=snk) { assert(Mux_Select(src,snk)); Mux_AllOff(); pairs++; }
    }
    assert(pairs==1560 && enables==1560 && addresses==1560);
    reset(); assert(!enabled && safety.state==DISARMED);
    feed("PING\r\n",0); expect("PONG");
    feed("PAIR 12 34 10\n",0); expect("ERR NOT_ARMED");
    feed("ARM 60\n",0); expect("OK ARM_TIMEOUT_S=60");
    const char *bad[]={"PAIR 0 1 10\n","PAIR 41 1 10\n","PAIR 1 1 10\n","PAIR 1 2 0\n","PAIR 1 2 301\n","PAIR -1 2 10\n","PAIR 1x 2 10\n","PAIR 42949672960 2 10\n","PAIR 1 2\n","PAIR 1 2 10 extra\n","ARM 0\n","ARM 61\n","ARM +1\n","PING extra\n","WHAT\n"};
    for(unsigned i=0;i<sizeof bad/sizeof bad[0];i++) { feed(bad[i],0); expect("ERR "); assert(!enabled); }
    feed("PAIR 12 34 10\n",0); expect("ACK ID=1"); assert(enabled);
    feed("PAIR 1 2 10\n",0); expect("ERR BUSY"); assert(enabled);
    for(unsigned t=1;t<=10;t++) { Safety_Sample(t, t); Safety_Tick(t); }
    assert(!enabled && safety.done); CLI_Poll(10); expect("DONE ID=1 STATE=OFF CURRENT_AVG_UA="); assert(safety.current.count==10);
    reset(); feed("ARM 60\n",0); feed("PAIR 1 2 300\n",0);
    /* No CLI/TX service: deadline still cuts outputs. */
    for(unsigned t=1;t<=300;t++) { Safety_Sample(100,t); Safety_Tick(t); }
    assert(!enabled && safety.state==IDLE && safety.done);
    reset(); feed("ARM 60\n",0); feed("PAIR 1 2 300\n",0);
    Safety_Tick(6); assert(!enabled && safety.state==FAULT);
    feed("SELFTEST\n",6); expect("ERR FAULT_LATCHED");
    feed("OFF\n",6); assert(safety.state==FAULT); feed("ARM 60\n",6); expect("FAULT_LATCHED");
    Safety_Sample(0,7); feed("CLEARFAULT\n",7); expect("OK DISARMED");
    feed("ARM 60\n",7); feed("PAIR 1 2 300\n",7); Safety_Sample(300,8);
    assert(!enabled && safety.state==FAULT && !strcmp(safety.fault,"OVERCURRENT"));
    Safety_Sample(4095,9); assert(!safety.current.valid && !enabled);
    reset(); feed("ARM 1\n",0); Safety_Sample(0,995); assert(!Safety_Pair(1,2,300,995));
    Safety_Sample(0,1000); Safety_Tick(1000); assert(!enabled && safety.state==DISARMED);
    reset(); feed("ARM 60\n",0); feed("PAIR 1 2 300\n",0);
    CLI_Receive((const uint8_t*)"PING\nPING\nPING\nOFF\n",19);
    assert(!enabled && safety.state==DISARMED); CLI_Poll(0); expect("OK DISARMED");
    reset(); char longline[200]; memset(longline,'x',sizeof longline); longline[198]='\n'; longline[199]=0;
    feed(longline,0); expect("ERR RX_OVERFLOW"); feed("PING\n",0); expect("PONG");
    const uint8_t nul[]={'A','R','M',0,' ','6','0','\n'}; CLI_Receive(nul,sizeof nul); CLI_Poll(0); assert(safety.state==DISARMED);
    reset(); gpio_ok=false; feed("ARM 60\n",0); expect("GPIO_INVALID"); assert(safety.state==FAULT);
    reset(); feed("ARM 60\n",0); feed("PAIR 1 2 300\n",0);
    const char *off="PING\nPING\nPING\n \tOFF \t\r\n";
    CLI_Receive((const uint8_t*)off,(uint32_t)strlen(off)); assert(!enabled && safety.state==DISARMED);
    reset(); const char *flood="ARM 60\nPAIR 1 2 300\nPING\nPING\n";
    CLI_Receive((const uint8_t*)flood,(uint32_t)strlen(flood));
    CLI_Poll(0); assert(!enabled && safety.state==DISARMED); expect("ERR RX_OVERFLOW");
    reset(); Safety_Sample(0,UINT32_MAX-10); assert(!Safety_Arm(1,UINT32_MAX-10));
    assert(!Safety_Pair(1,2,10,UINT32_MAX-10)); Safety_Sample(0,UINT32_MAX); Safety_Tick(UINT32_MAX); assert(!enabled);
    puts("PASS: 40 mappings, 1560 directed pairs, parser errors, asynchronous deadlines, OFF priority, ADC faults, ARM expiry, wraparound, break-before-make");
    return 0;
}
