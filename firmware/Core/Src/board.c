#include "main.h"
#include "board.h"
#include "board_config.h"
uint32_t Board_Lock(void) { uint32_t key=__get_PRIMASK(); __disable_irq(); return key; }
void Board_Unlock(uint32_t key) { __set_PRIMASK(key); }
void Board_Off(void) {
    GPIOA->BSRR=(uint32_t)GPIO_PIN_10<<16;
    GPIOC->BSRR=(uint32_t)GPIO_PIN_12<<16;
    __DSB();
}
uint32_t Board_GpioA(void) { return GPIOA->IDR; }
uint32_t Board_GpioC(void) { return GPIOC->IDR; }
uint32_t Board_Millis(void) { return HAL_GetTick(); }
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
