#include "main.h"
#include "board.h"
#include "safety.h"
#include "board_config.h"
static ADC_HandleTypeDef adc;
static uint32_t last_sample;
uint32_t Board_Lock(void) { uint32_t key=__get_PRIMASK(); __disable_irq(); return key; }
void Board_Unlock(uint32_t key) { __set_PRIMASK(key); }
void Board_Off(void) {
    GPIOA->BSRR=(uint32_t)GPIO_PIN_10<<16;
    GPIOC->BSRR=(uint32_t)GPIO_PIN_12<<16;
    __DSB();
}
uint32_t Board_GpioA(void) { return GPIOA->IDR; }
uint32_t Board_GpioC(void) { return GPIOC->IDR; }
void Board_Init(void) {
    __HAL_RCC_GPIOA_CLK_ENABLE(); __HAL_RCC_GPIOC_CLK_ENABLE();
    Board_Off(); /* preload output latches BEFORE changing MODER */
    GPIOA->BSRR=0x07f00000u; GPIOC->BSRR=0x1fc00000u;
    GPIO_InitTypeDef g={0}; g.Mode=GPIO_MODE_OUTPUT_PP; g.Pull=GPIO_PULLDOWN; g.Speed=GPIO_SPEED_FREQ_LOW;
    g.Pin=0x07f0; HAL_GPIO_Init(GPIOA,&g);
    g.Pin=0x1fc0; HAL_GPIO_Init(GPIOC,&g);
    CoreDebug->DEMCR|=CoreDebug_DEMCR_TRCENA_Msk; DWT->CYCCNT=0; DWT->CTRL|=DWT_CTRL_CYCCNTENA_Msk;
}
void Board_DelayUs(uint32_t us) {
    uint32_t start=DWT->CYCCNT, cycles=(SystemCoreClock/1000000u)*us;
    while(DWT->CYCCNT-start<cycles) { __NOP(); }
}
void Board_Address(uint8_t sb,uint8_t sc,uint8_t tb,uint8_t tc) {
    uint32_t a=((uint32_t)sc<<4)|((uint32_t)sb<<7),c=((uint32_t)tc<<6)|((uint32_t)tb<<9);
    GPIOA->BSRR=((0x3f0u & ~a)<<16)|a;
    GPIOC->BSRR=((0xfc0u & ~c)<<16)|c;
}
void Board_Enable(void) { GPIOC->BSRR=GPIO_PIN_12; GPIOA->BSRR=GPIO_PIN_10; }
bool Board_Check(void) {
    if((GPIOA->IDR&GPIO_PIN_10)||(GPIOC->IDR&GPIO_PIN_12)) return false;
    for(unsigned i=4;i<=10;i++) if(((GPIOA->MODER>>(2*i))&3)!=1 || (GPIOA->OTYPER&(1u<<i))) return false;
    for(unsigned i=6;i<=12;i++) if(((GPIOC->MODER>>(2*i))&3)!=1 || (GPIOC->OTYPER&(1u<<i))) return false;
    return (GPIOA->MODER&3)==3; /* PA0 analog */
}
void ADC_Init(void) {
    __HAL_RCC_ADC1_CLK_ENABLE();
    GPIO_InitTypeDef g={0}; g.Pin=GPIO_PIN_0; g.Mode=GPIO_MODE_ANALOG; HAL_GPIO_Init(GPIOA,&g);
    adc.Instance=ADC1; adc.Init.ClockPrescaler=ADC_CLOCK_SYNC_PCLK_DIV4;
    adc.Init.Resolution=ADC_RESOLUTION_12B; adc.Init.ContinuousConvMode=ENABLE;
    adc.Init.ExternalTrigConvEdge=ADC_EXTERNALTRIGCONVEDGE_NONE;
    adc.Init.ExternalTrigConv=ADC_SOFTWARE_START; adc.Init.DataAlign=ADC_DATAALIGN_RIGHT;
    adc.Init.NbrOfConversion=1; adc.Init.EOCSelection=ADC_EOC_SINGLE_CONV;
    if(HAL_ADC_Init(&adc)!=HAL_OK) Error_Handler();
    ADC_ChannelConfTypeDef ch={0}; ch.Channel=ADC_CHANNEL_0; ch.Rank=1; ch.SamplingTime=ADC_SAMPLETIME_480CYCLES;
    if(HAL_ADC_ConfigChannel(&adc,&ch)!=HAL_OK || HAL_ADC_Start(&adc)!=HAL_OK) Error_Handler();
    last_sample=HAL_GetTick()-1;
}
void ADC_Poll(void) {
    uint32_t now=HAL_GetTick();
    if(now==last_sample || !__HAL_ADC_GET_FLAG(&adc,ADC_FLAG_EOC)) return;
    last_sample=now;
    uint32_t raw=HAL_ADC_GetValue(&adc);
    uint32_t key=Board_Lock(); Safety_Sample(raw,now); Board_Unlock(key);
}
