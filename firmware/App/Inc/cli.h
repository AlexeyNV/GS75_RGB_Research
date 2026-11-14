#pragma once
#include <stdint.h>
/* RX in USB IRQ, Poll in main; TX is bounded and never waits. */
void CLI_Receive(const uint8_t *data, uint32_t length);
void CLI_Poll(uint32_t now);
void CLI_Reset(void);
void CLI_Send(const char *text);
void USB_Queue(const char *text);
