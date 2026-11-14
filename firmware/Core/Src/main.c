#include "main.h"
#include "board.h"
#include "safety.h"
#include "cli.h"
#include "usb_device.h"
static void Clock_Init(void) {
    __HAL_RCC_PWR_CLK_ENABLE(); __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
    RCC_OscInitTypeDef o={0}; o.OscillatorType=RCC_OSCILLATORTYPE_HSE; o.HSEState=RCC_HSE_ON;
    o.PLL.PLLState=RCC_PLL_ON; o.PLL.PLLSource=RCC_PLLSOURCE_HSE;
    o.PLL.PLLM=8; o.PLL.PLLN=192; o.PLL.PLLP=RCC_PLLP_DIV2; o.PLL.PLLQ=4;
    if(HAL_RCC_OscConfig(&o)!=HAL_OK) Error_Handler();
    RCC_ClkInitTypeDef c={0}; c.ClockType=RCC_CLOCKTYPE_SYSCLK|RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
    c.SYSCLKSource=RCC_SYSCLKSOURCE_PLLCLK; c.AHBCLKDivider=RCC_SYSCLK_DIV1;
    c.APB1CLKDivider=RCC_HCLK_DIV2; c.APB2CLKDivider=RCC_HCLK_DIV1;
    if(HAL_RCC_ClockConfig(&c,FLASH_LATENCY_3)!=HAL_OK) Error_Handler();
    HAL_NVIC_SetPriority(SysTick_IRQn,0,0);
}
int main(void) {
    /* External R16/R17 hold EN low before software runs. */
    Board_Init(); Safety_Init(); HAL_Init(); Clock_Init(); ADC_Init(); USB_Init();
    for(;;) { ADC_Poll(); CLI_Poll(HAL_GetTick()); USB_Poll(); }
}
void SysTick_Handler(void) {
    HAL_IncTick(); uint32_t key=Board_Lock(); Safety_Tick(HAL_GetTick()); Board_Unlock(key);
}
void Error_Handler(void) { __disable_irq(); Board_Off(); for(;;) {} }
void HardFault_Handler(void) { Error_Handler(); }
void MemManage_Handler(void) { Error_Handler(); }
void BusFault_Handler(void) { Error_Handler(); }
void UsageFault_Handler(void) { Error_Handler(); }
void NMI_Handler(void) { Error_Handler(); }
