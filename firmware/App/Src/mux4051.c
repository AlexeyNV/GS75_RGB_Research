#include "mux4051.h"
#include "board.h"
#include "board_config.h"
bool Mux_Map(unsigned pin, MuxAddress *out) {
    if (!out || pin < 1 || pin > FPC_PINS) return false;
    out->channel = (uint8_t)((pin - 1) % 8);
    out->bank = (uint8_t)(4 - (pin - 1) / 8);
    return true;
}
bool Mux_ValidPair(unsigned source, unsigned sink) {
    MuxAddress a, b;
    return source != sink && Mux_Map(source, &a) && Mux_Map(sink, &b);
}
void Mux_AllOff(void) { Board_Off(); }
bool Mux_Select(unsigned source, unsigned sink) {
    MuxAddress a, b;
    Mux_AllOff();
    if (!Mux_ValidPair(source, sink)) return false;
    (void)Mux_Map(source, &a); (void)Mux_Map(sink, &b);
    /* Caller holds a short critical section, including final enable. */
    Board_DelayUs(MUX_SETTLE_US); /* decoder + mux disable propagation */
    Board_Address(a.bank, a.channel, b.bank, b.channel);
    Board_DelayUs(MUX_SETTLE_US);
    Board_Enable();
    return true;
}
