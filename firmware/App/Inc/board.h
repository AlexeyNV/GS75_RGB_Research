#pragma once
#include <stdint.h>
#include <stdbool.h>
void Board_Off(void);
void Board_Address(uint8_t src_bank, uint8_t src_ch, uint8_t snk_bank, uint8_t snk_ch);
void Board_Enable(void);
void Board_DelayUs(uint32_t us);
bool Board_Check(void);
uint32_t Board_GpioA(void);
uint32_t Board_GpioC(void);
uint32_t Board_Lock(void);
void Board_Unlock(uint32_t key);
