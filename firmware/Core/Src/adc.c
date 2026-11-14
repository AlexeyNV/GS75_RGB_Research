#include "main.h"
#include "board.h"
#include "board_config.h"
#include "adc_status.h"
#include "safety.h"
#include <string.h>

static ADC_HandleTypeDef adc;
static ADCStatus status;
static uint32_t last_start;

/* Caller serializes against SysTick/CLI. Do not accept a lost/old result. */
static void recover(uint32_t now) {
    status.errors++;
    safety.current.valid=false;
    Safety_Fault("ADC_INVALID");
    if(HAL_ADC_Stop(&adc)!=HAL_OK) { status.stop_errors++; status.errors++; }
    __HAL_ADC_CLEAR_FLAG(&adc,ADC_FLAG_EOC | ADC_FLAG_OVR | ADC_FLAG_STRT);
    status.pending=false;
    last_start=now; /* retry next period, never spin/restart in a burst */
}

void ADC_Init(void) {
    memset(&adc,0,sizeof adc); memset(&status,0,sizeof status);
    __HAL_RCC_ADC1_CLK_ENABLE();
    GPIO_InitTypeDef g={0}; g.Pin=GPIO_PIN_0; g.Mode=GPIO_MODE_ANALOG; HAL_GPIO_Init(GPIOA,&g);
    adc.Instance=ADC1; adc.Init.ClockPrescaler=ADC_CLOCK_SYNC_PCLK_DIV4;
    adc.Init.Resolution=ADC_RESOLUTION_12B; adc.Init.ContinuousConvMode=DISABLE;
    adc.Init.ScanConvMode=DISABLE; adc.Init.DiscontinuousConvMode=DISABLE;
    adc.Init.DMAContinuousRequests=DISABLE;
    adc.Init.ExternalTrigConvEdge=ADC_EXTERNALTRIGCONVEDGE_NONE;
    adc.Init.ExternalTrigConv=ADC_SOFTWARE_START; adc.Init.DataAlign=ADC_DATAALIGN_RIGHT;
    adc.Init.NbrOfConversion=1; adc.Init.EOCSelection=ADC_EOC_SINGLE_CONV;
    if(HAL_ADC_Init(&adc)!=HAL_OK) Error_Handler();
    ADC_ChannelConfTypeDef ch={0}; ch.Channel=ADC_CHANNEL_0; ch.Rank=1; ch.SamplingTime=ADC_SAMPLETIME_480CYCLES;
    if(HAL_ADC_ConfigChannel(&adc,&ch)!=HAL_OK) Error_Handler();
    __HAL_ADC_CLEAR_FLAG(&adc,ADC_FLAG_EOC | ADC_FLAG_OVR | ADC_FLAG_STRT);
    last_start=HAL_GetTick()-ADC_SAMPLE_PERIOD_MS;
}

void ADC_Poll(void) {
    uint32_t key=Board_Lock(), now=HAL_GetTick();
    uint32_t sr=adc.Instance->SR;
    status.last_sr=sr;
    /* OVR wins over EOC. DR may contain lost/ambiguous data. */
    if(sr & ADC_FLAG_OVR) {
        status.overruns++; recover(now); Board_Unlock(key); return;
    }
    if(status.pending) {
        /* A late EOC must not refresh freshness with an old acquisition. */
        if(now-last_start>=ADC_CONVERSION_TIMEOUT_MS) {
            status.timeouts++; recover(now); Board_Unlock(key); return;
        }
        if(sr & ADC_FLAG_EOC) {
            uint32_t raw=HAL_ADC_GetValue(&adc); /* hardware clears EOC on DR read */
            status.pending=false; status.samples++;
            /* Acquisition age is measured from trigger, not late DR consumption. */
            Safety_Sample(raw,last_start);
            if(safety.current.valid) {
                status.valid_samples++; status.has_sample=true; status.last_sample_ms=last_start;
            } else { status.invalid_samples++; status.errors++; }
        }
    }
    if(!status.pending && now-last_start>=ADC_SAMPLE_PERIOD_MS) {
        /* HAL_ADC_Start clears EOC/OVR; only call AFTER the previous DR read. */
        last_start=now;
        HAL_StatusTypeDef result=HAL_ADC_Start(&adc);
        if(result!=HAL_OK || !(adc.Instance->CR2 & ADC_CR2_ADON) || HAL_ADC_GetError(&adc)!=HAL_ADC_ERROR_NONE) {
            status.start_errors++; recover(now);
        } else { status.starts++; status.pending=true; }
    }
    Board_Unlock(key);
}

void ADC_GetStatus(ADCStatus *out) {
    uint32_t key=Board_Lock();
    *out=status;
    out->sr=adc.Instance->SR; out->cr2=adc.Instance->CR2;
    out->hal_error=HAL_ADC_GetError(&adc);
    Board_Unlock(key);
}
