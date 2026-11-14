#pragma once
/* Only the peripheral boundary is modeled; adc.c itself is production code. */
#include <stdint.h>
#define ENABLE 1u
#define DISABLE 0u
#define ADC_FLAG_EOC (1u<<1)
#define ADC_FLAG_OVR (1u<<5)
#define ADC_FLAG_STRT (1u<<4)
#define ADC_CR2_ADON 1u
#define ADC_CR2_CONT 2u
#define ADC_CR2_EOCS (1u<<10)
#define ADC_CR2_SWSTART (1u<<30)
#define ADC_CLOCK_SYNC_PCLK_DIV4 1u
#define ADC_RESOLUTION_12B 0u
#define ADC_EXTERNALTRIGCONVEDGE_NONE 0u
#define ADC_SOFTWARE_START 0u
#define ADC_DATAALIGN_RIGHT 0u
#define ADC_EOC_SINGLE_CONV 1u
#define HAL_ADC_ERROR_NONE 0u
#define GPIO_PIN_0 1u
#define GPIO_MODE_ANALOG 3u
#define ADC_CHANNEL_0 0u
#define ADC_SAMPLETIME_480CYCLES 7u
typedef enum { HAL_OK, HAL_ERROR, HAL_BUSY } HAL_StatusTypeDef;
typedef struct { uint32_t SR, CR2, DR; } ADC_TypeDef;
extern ADC_TypeDef mock_adc;
#define ADC1 (&mock_adc)
#define GPIOA ((void*)0)
typedef struct { uint32_t Pin, Mode; } GPIO_InitTypeDef;
typedef struct {
    uint32_t ClockPrescaler, Resolution, ContinuousConvMode, ScanConvMode, DiscontinuousConvMode;
    uint32_t DMAContinuousRequests, ExternalTrigConvEdge, ExternalTrigConv, DataAlign, NbrOfConversion, EOCSelection;
} ADC_InitTypeDef;
typedef struct { ADC_TypeDef *Instance; ADC_InitTypeDef Init; uint32_t ErrorCode; } ADC_HandleTypeDef;
typedef struct { uint32_t Channel, Rank, SamplingTime; } ADC_ChannelConfTypeDef;
#define __HAL_RCC_ADC1_CLK_ENABLE() ((void)0)
#define __HAL_ADC_CLEAR_FLAG(h,flags) ((h)->Instance->SR &= ~(flags))
void HAL_GPIO_Init(void *port,GPIO_InitTypeDef *g);
uint32_t HAL_GetTick(void);
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef *a);
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *a,ADC_ChannelConfTypeDef *c);
HAL_StatusTypeDef HAL_ADC_Start(ADC_HandleTypeDef *a);
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef *a);
uint32_t HAL_ADC_GetValue(ADC_HandleTypeDef *a);
uint32_t HAL_ADC_GetError(ADC_HandleTypeDef *a);
void Error_Handler(void);
void ADC_Init(void);
void ADC_Poll(void);
