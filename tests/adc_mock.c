#include "adc_mock.h"
#include <assert.h>
#include <stdlib.h>
#include <string.h>
ADC_TypeDef mock_adc;
uint32_t mock_now, mock_reads, mock_starts, mock_stops;
bool mock_inflight, mock_start_fail, mock_stop_fail, mock_enable_fail;
void Mock_Reset(void) {
    memset(&mock_adc,0,sizeof mock_adc);
    mock_now=mock_reads=mock_starts=mock_stops=0;
    mock_inflight=mock_start_fail=mock_stop_fail=mock_enable_fail=false;
}
void Mock_Complete(uint32_t raw) {
    assert(mock_inflight);
    if(mock_adc.SR & ADC_FLAG_EOC) mock_adc.SR|=ADC_FLAG_OVR;
    mock_adc.DR=raw; mock_adc.SR|=ADC_FLAG_EOC;
    mock_adc.CR2&=~ADC_CR2_SWSTART; mock_inflight=false;
}
void HAL_GPIO_Init(void *port,GPIO_InitTypeDef *g) { (void)port; assert(g->Pin==GPIO_PIN_0 && g->Mode==GPIO_MODE_ANALOG); }
uint32_t HAL_GetTick(void) { return mock_now; }
uint32_t Board_Millis(void) { return mock_now; }
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef *a) {
    assert(a->Init.ContinuousConvMode==DISABLE && a->Init.ScanConvMode==DISABLE);
    assert(a->Init.ExternalTrigConvEdge==0 && a->Init.NbrOfConversion==1 && a->Init.DMAContinuousRequests==DISABLE);
    assert(a->Init.ClockPrescaler==ADC_CLOCK_SYNC_PCLK_DIV4 && a->Init.Resolution==ADC_RESOLUTION_12B);
    a->Instance->CR2=ADC_CR2_EOCS; return HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *a,ADC_ChannelConfTypeDef *c) {
    (void)a; assert(c->Channel==ADC_CHANNEL_0 && c->Rank==1 && c->SamplingTime==ADC_SAMPLETIME_480CYCLES); return HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_Start(ADC_HandleTypeDef *a) {
    mock_starts++;
    if(mock_start_fail) return HAL_BUSY;
    assert(!mock_inflight); /* no retrigger before a result is consumed or recovery */
    a->Instance->SR&=~(ADC_FLAG_EOC|ADC_FLAG_OVR);
    if(!mock_enable_fail) a->Instance->CR2|=ADC_CR2_ADON;
    a->Instance->CR2|=ADC_CR2_SWSTART;
    mock_inflight=true; a->ErrorCode=HAL_ADC_ERROR_NONE; return HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef *a) {
    mock_stops++; a->Instance->CR2&=~ADC_CR2_ADON; mock_inflight=false;
    return mock_stop_fail?HAL_ERROR:HAL_OK;
}
uint32_t HAL_ADC_GetValue(ADC_HandleTypeDef *a) {
    assert(a->Instance->SR & ADC_FLAG_EOC); mock_reads++;
    a->Instance->SR&=~ADC_FLAG_EOC; return a->Instance->DR;
}
uint32_t HAL_ADC_GetError(ADC_HandleTypeDef *a) { return a->ErrorCode; }
void Error_Handler(void) { abort(); }
