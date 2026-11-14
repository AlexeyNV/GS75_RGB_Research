#include "usbd_core.h"
#include "usbd_cdc.h"
#include "main.h"
#include "safety.h"
#include "cli.h"
#include "usb_device.h"
PCD_HandleTypeDef hpcd;
static uint32_t class_memory[(sizeof(USBD_CDC_HandleTypeDef)+3)/4];
void *USBD_static_malloc(uint32_t size) { return size<=sizeof class_memory?class_memory:0; }
void USBD_static_free(void *p) { (void)p; }
void HAL_PCD_MspInit(PCD_HandleTypeDef *p) {
    (void)p; __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_USB_OTG_FS_CLK_ENABLE();
    GPIO_InitTypeDef g={0}; g.Pin=GPIO_PIN_11|GPIO_PIN_12; g.Mode=GPIO_MODE_AF_PP;
    g.Speed=GPIO_SPEED_FREQ_VERY_HIGH; g.Alternate=GPIO_AF10_OTG_FS; HAL_GPIO_Init(GPIOA,&g);
    /* PA9 and PA10 remain GPIO; no VBUS or ID pin configuration. */
    HAL_NVIC_SetPriority(OTG_FS_IRQn,5,0); HAL_NVIC_EnableIRQ(OTG_FS_IRQn);
}
void HAL_PCD_MspDeInit(PCD_HandleTypeDef *p) { (void)p; HAL_NVIC_DisableIRQ(OTG_FS_IRQn); __HAL_RCC_USB_OTG_FS_CLK_DISABLE(); }
void OTG_FS_IRQHandler(void) { HAL_PCD_IRQHandler(&hpcd); }
void HAL_PCD_SetupStageCallback(PCD_HandleTypeDef *p) { USBD_LL_SetupStage(p->pData,(uint8_t*)p->Setup); }
void HAL_PCD_DataOutStageCallback(PCD_HandleTypeDef *p,uint8_t ep) { USBD_LL_DataOutStage(p->pData,ep,p->OUT_ep[ep].xfer_buff); }
void HAL_PCD_DataInStageCallback(PCD_HandleTypeDef *p,uint8_t ep) { USBD_LL_DataInStage(p->pData,ep,p->IN_ep[ep].xfer_buff); }
void HAL_PCD_SOFCallback(PCD_HandleTypeDef *p) { USBD_LL_SOF(p->pData); }
static void transport_stop(void) { Safety_Stop("USB_LOST",true); CLI_Reset(); USB_ResetTransport(); }
void HAL_PCD_ResetCallback(PCD_HandleTypeDef *p) {
    transport_stop(); USBD_LL_SetSpeed(p->pData,USBD_SPEED_FULL); USBD_LL_Reset(p->pData);
}
void HAL_PCD_SuspendCallback(PCD_HandleTypeDef *p) { transport_stop(); USBD_LL_Suspend(p->pData); }
void HAL_PCD_ResumeCallback(PCD_HandleTypeDef *p) { USBD_LL_Resume(p->pData); }
void HAL_PCD_ConnectCallback(PCD_HandleTypeDef *p) { USBD_LL_DevConnected(p->pData); }
void HAL_PCD_DisconnectCallback(PCD_HandleTypeDef *p) { transport_stop(); USBD_LL_DevDisconnected(p->pData); }
void HAL_PCD_ISOOUTIncompleteCallback(PCD_HandleTypeDef *p,uint8_t ep) { USBD_LL_IsoOUTIncomplete(p->pData,ep); }
void HAL_PCD_ISOINIncompleteCallback(PCD_HandleTypeDef *p,uint8_t ep) { USBD_LL_IsoINIncomplete(p->pData,ep); }
USBD_StatusTypeDef USBD_LL_Init(USBD_HandleTypeDef *d) {
    hpcd.Instance=USB_OTG_FS; hpcd.Init.dev_endpoints=4; hpcd.Init.speed=PCD_SPEED_FULL;
    hpcd.Init.phy_itface=PCD_PHY_EMBEDDED; hpcd.Init.vbus_sensing_enable=DISABLE;
    hpcd.Init.dma_enable=DISABLE; hpcd.Init.low_power_enable=DISABLE; hpcd.Init.Sof_enable=DISABLE;
    hpcd.pData=d; d->pData=&hpcd;
    if(HAL_PCD_Init(&hpcd)!=HAL_OK) return USBD_FAIL;
    HAL_PCDEx_SetRxFiFo(&hpcd,128); HAL_PCDEx_SetTxFiFo(&hpcd,0,64);
    HAL_PCDEx_SetTxFiFo(&hpcd,1,96); HAL_PCDEx_SetTxFiFo(&hpcd,2,32);
    return USBD_OK;
}
static USBD_StatusTypeDef status(HAL_StatusTypeDef s) { return s==HAL_OK?USBD_OK:USBD_FAIL; }
USBD_StatusTypeDef USBD_LL_DeInit(USBD_HandleTypeDef *d) { return status(HAL_PCD_DeInit(d->pData)); }
USBD_StatusTypeDef USBD_LL_Start(USBD_HandleTypeDef *d) { return status(HAL_PCD_Start(d->pData)); }
USBD_StatusTypeDef USBD_LL_Stop(USBD_HandleTypeDef *d) { return status(HAL_PCD_Stop(d->pData)); }
USBD_StatusTypeDef USBD_LL_OpenEP(USBD_HandleTypeDef *d,uint8_t a,uint8_t t,uint16_t m) { return status(HAL_PCD_EP_Open(d->pData,a,m,t)); }
USBD_StatusTypeDef USBD_LL_CloseEP(USBD_HandleTypeDef *d,uint8_t a) { return status(HAL_PCD_EP_Close(d->pData,a)); }
USBD_StatusTypeDef USBD_LL_FlushEP(USBD_HandleTypeDef *d,uint8_t a) { return status(HAL_PCD_EP_Flush(d->pData,a)); }
USBD_StatusTypeDef USBD_LL_StallEP(USBD_HandleTypeDef *d,uint8_t a) { return status(HAL_PCD_EP_SetStall(d->pData,a)); }
USBD_StatusTypeDef USBD_LL_ClearStallEP(USBD_HandleTypeDef *d,uint8_t a) { return status(HAL_PCD_EP_ClrStall(d->pData,a)); }
uint8_t USBD_LL_IsStallEP(USBD_HandleTypeDef *d,uint8_t a) {
    PCD_HandleTypeDef *p=d->pData; return (uint8_t)((a&0x80)?p->IN_ep[a&0x7f].is_stall:p->OUT_ep[a&0x7f].is_stall);
}
USBD_StatusTypeDef USBD_LL_SetUSBAddress(USBD_HandleTypeDef *d,uint8_t a) { return status(HAL_PCD_SetAddress(d->pData,a)); }
USBD_StatusTypeDef USBD_LL_Transmit(USBD_HandleTypeDef *d,uint8_t a,uint8_t *p,uint32_t n) { return status(HAL_PCD_EP_Transmit(d->pData,a,p,n)); }
USBD_StatusTypeDef USBD_LL_PrepareReceive(USBD_HandleTypeDef *d,uint8_t a,uint8_t *p,uint32_t n) { return status(HAL_PCD_EP_Receive(d->pData,a,p,n)); }
uint32_t USBD_LL_GetRxDataSize(USBD_HandleTypeDef *d,uint8_t a) { return HAL_PCD_EP_GetRxCount(d->pData,a); }
void USBD_LL_Delay(uint32_t ms) { HAL_Delay(ms); }
