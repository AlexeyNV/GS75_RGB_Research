#include "mux4051.h"
#include "safety.h"
#include "board_config.h"
#include "board.h"
#include "cli.h"
#include "adc_mock.h"
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
static void reset(void) { Mock_Reset(); Safety_Init(); CLI_Reset(); output[0]=0; gpio_ok=true; Safety_Sample(0,0); }
static void feed(const char *s,uint32_t now) { mock_now=now; output[0]=0; CLI_Receive((const uint8_t*)s,(uint32_t)strlen(s)); CLI_Poll(now); }
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
    const unsigned durations[]={100,5000,10000};
    const char *colors[]={"RED","GREEN","BLUE"};
    for(unsigned i=0;i<3;i++) {
        reset(); feed("ARM 60\n",0);
        char cmd[80]; snprintf(cmd,sizeof cmd,"PHOTO LED49 %s %u\n",colors[i],durations[i]);
        feed(cmd,0); expect("ACK ID=1 MODE=PHOTO LED=49"); assert(enabled && safety.source==14 && safety.sink==32+i);
        feed("STATUS\n",0); expect("MODE=PHOTO");
        feed("PAIR 1 2 100\n",0); expect("ERR BUSY");
        feed("PHOTO LED49 RED 100\n",0); expect("ERR BUSY");
        feed("ARM 60\n",0); expect("ERR BUSY");
        /* No CLI polling throughout continuous operation. */
        for(unsigned t=1;t<=durations[i];t++) {
            mock_now=t; Safety_Sample(100,t); Safety_Tick(t);
            assert(enabled==(t<durations[i]));
        }
        assert(!Board_GpioA() && !Board_GpioC() && safety.current.count==durations[i]);
        feed("STATUS\n",durations[i]); expect("REASON=TIMEOUT"); expect("MODE=PHOTO LED=49");
        assert(safety.elapsed_ms==durations[i] && safety.state==IDLE);
    }
    const char *badphoto[]={"PHOTO LED49 RED 99\n","PHOTO LED49 RED 10001\n","PHOTO LED50 RED 100\n",
        "PHOTO 14 32 100\n","PHOTO LED49 WHITE 100\n","PHOTO LED49 RED+GREEN 100\n","PHOTO LED49 RED -1\n",
        "PHOTO LED49 RED 42949672960\n","PHOTO LED49 RED 100 extra\n"};
    reset(); feed("PHOTO LED49 RED 100\n",0); expect("ERR NOT_ARMED"); feed("ARM 60\n",0);
    for(unsigned i=0;i<sizeof badphoto/sizeof badphoto[0];i++) { feed(badphoto[i],0); expect("ERR "); assert(!enabled); }
    feed("PAIR 14 32 301\n",0); expect("ERR INVALID_DURATION");
    feed("PAIR 14 32 300\n",0); feed("PHOTO LED49 RED 100\n",0); expect("ERR BUSY");
    for(unsigned failure=0;failure<7;failure++) {
        reset(); feed("ARM 1\n",0); feed("PHOTO LED49 RED 5000\n",0);
        if(failure==0) { mock_now=50; CLI_Receive((const uint8_t*)"PING\nPING\nPING\nOFF\n",19); }
        if(failure==1) { mock_now=1000; Safety_Sample(100,1000); Safety_Tick(1000); }
        if(failure==2) { mock_now=6; Safety_Tick(6); }
        if(failure==3) { mock_now=1; Safety_Sample(4095,1); }
        if(failure==4) { mock_now=1; Safety_Sample(300,1); }
        if(failure==5) { mock_now=3; Safety_Stop("USB_LOST",true); CLI_Reset(); }
        if(failure==6) { mock_now=4; Safety_Fault("TX_OVERFLOW"); }
        assert(!enabled && !Board_GpioA() && !Board_GpioC() && safety.done);
        unsigned previous_enables=enables; Safety_Sample(0,mock_now); CLI_Poll(mock_now);
        Safety_Tick(mock_now+1); assert(enables==previous_enables && !enabled);
        if(safety.state==FAULT) { feed("OFF\n",mock_now); feed("PHOTO LED49 RED 100\n",mock_now); expect("FAULT_LATCHED"); }
        if(failure==0) { expect("REASON=OFF"); assert(safety.elapsed_ms==50); }
        if(failure==1) { expect("REASON=ARM_EXPIRED"); assert(safety.elapsed_ms==1000); }
        if(failure==5) expect("REASON=USB_LOST");
    }
    for(unsigned expiry=0;expiry<2;expiry++) {
        reset(); uint32_t start=UINT32_MAX-200;
        mock_now=start; Safety_Sample(0,start); assert(!Safety_Arm(expiry?1:20,start));
        assert(!Safety_Photo("LED49","RED",5000,start));
        unsigned end=expiry?1000:5000;
        for(unsigned t=1;t<=end;t++) { mock_now=start+t; Safety_Sample(100,mock_now); Safety_Tick(mock_now); assert(enabled==(t<end)); }
        assert(safety.elapsed_ms==end); Safety_Init(); assert(!enabled && safety.state==DISARMED);
    }
    puts("PASS: PAIR regressions and PHOTO routes, bounds, deadlines, faults, OFF, USB loss, ARM expiry and wraparound");
    return 0;
}
