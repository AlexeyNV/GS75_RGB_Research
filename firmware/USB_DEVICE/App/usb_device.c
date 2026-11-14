#include "usb_device.h"
#include "main.h"
#include "usbd_core.h"
#include "usbd_cdc.h"
#include "usbd_ctlreq.h"
#include "cli.h"
#include "safety.h"
#include "board.h"
#include <stdio.h>
static USBD_HandleTypeDef device;
static uint8_t rx[64];
static char tx[8][512];
static unsigned head,tail;
static bool inflight;
static uint8_t coding[7]={0x00,0xc2,0x01,0,0,0,8};
void USB_ResetTransport(void) { head=tail=0; inflight=false; }
void USB_Queue(const char *text) {
    unsigned next=(head+1)%8;
    if(next==tail) { Safety_Fault("TX_OVERFLOW"); return; }
    size_t n=strlen(text);
    if(n>=sizeof tx[0]) { Safety_Fault("TX_OVERFLOW"); return; }
    memcpy(tx[head],text,n+1); head=next;
}
static int8_t init(void) {
    USBD_CDC_SetTxBuffer(&device,(uint8_t*)tx[0],0); USBD_CDC_SetRxBuffer(&device,rx); return USBD_OK;
}
static int8_t deinit(void) { Safety_Stop("USB_LOST",true); CLI_Reset(); USB_ResetTransport(); return USBD_OK; }
static int8_t control(uint8_t cmd,uint8_t *p,uint16_t n) {
    if(cmd==CDC_SET_LINE_CODING && n==7) memcpy(coding,p,7);
    if(cmd==CDC_GET_LINE_CODING && n==7) memcpy(p,coding,7);
    return USBD_OK;
}
static int8_t receive(uint8_t *p,uint32_t *n) {
    uint32_t key=Board_Lock(); CLI_Receive(p,*n); Board_Unlock(key);
    USBD_CDC_SetRxBuffer(&device,rx); USBD_CDC_ReceivePacket(&device); return USBD_OK;
}
static int8_t complete(uint8_t *p,uint32_t *n,uint8_t ep) {
    (void)p; (void)n; (void)ep;
    if(inflight) { tail=(tail+1)%8; inflight=false; }
    return USBD_OK;
}
static USBD_CDC_ItfTypeDef interface={init,deinit,control,receive,complete};
static uint8_t dev_desc[]={18,1,0,2,2,2,0,64,0x83,0x04,0x40,0x57,0,1,1,2,3,1};
static uint8_t lang[]={4,3,9,4}, str[256];
static uint8_t *descriptor(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; *n=sizeof dev_desc; return dev_desc; }
static uint8_t *language(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; *n=sizeof lang; return lang; }
static uint8_t *string(const char *s,uint16_t *n) { USBD_GetString((uint8_t*)s,str,n); return str; }
static uint8_t *manufacturer(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; return string("GS75 Research",n); }
static uint8_t *product(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; return string("GS75 RGB Research CDC",n); }
static uint8_t *serial(USBD_SpeedTypeDef speed,uint16_t *n) {
    (void)speed; char uid[25]; snprintf(uid,sizeof uid,"%08lX%08lX%08lX",(unsigned long)HAL_GetUIDw0(),(unsigned long)HAL_GetUIDw1(),(unsigned long)HAL_GetUIDw2()); return string(uid,n);
}
static uint8_t *configuration(USBD_SpeedTypeDef speed,uint16_t *n) { (void)speed; return string("CDC",n); }
static USBD_DescriptorsTypeDef descriptors={descriptor,language,manufacturer,product,serial,configuration,configuration};
void USB_Init(void) {
    if(USBD_Init(&device,&descriptors,0)!=USBD_OK || USBD_RegisterClass(&device,&USBD_CDC)!=USBD_OK || USBD_CDC_RegisterInterface(&device,&interface)!=USBD_OK || USBD_Start(&device)!=USBD_OK) Error_Handler();
}
void USB_Poll(void) {
    uint32_t key=Board_Lock();
    if(device.dev_state==USBD_STATE_CONFIGURED && device.pClassData && !inflight && tail!=head) {
        USBD_CDC_HandleTypeDef *cdc=device.pClassData;
        if(!cdc->TxState) {
            USBD_CDC_SetTxBuffer(&device,(uint8_t*)tx[tail],(uint32_t)strlen(tx[tail]));
            inflight=true;
            if(USBD_CDC_TransmitPacket(&device)!=USBD_OK) inflight=false;
        }
    }
    Board_Unlock(key);
}
