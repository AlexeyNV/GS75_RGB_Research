#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef struct { uint8_t bank, channel; } MuxAddress;
bool Mux_Map(unsigned pin, MuxAddress *out);
bool Mux_ValidPair(unsigned source, unsigned sink);
void Mux_AllOff(void);
bool Mux_Select(unsigned source, unsigned sink);
