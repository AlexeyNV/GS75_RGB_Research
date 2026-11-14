"""Compare firmware wiring assumptions with extracted EasyEDA connectivity."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from check_schematic import extract


class Wiring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parts = extract()

    def pin(self, ref, name):
        return next(p for p in self.parts[ref]['pins'].values() if p['name'] == name)

    def test_gpio(self):
        for port, start, prefix in [('PA', 4, 'SRC'), ('PC', 6, 'SNK')]:
            for i, name in enumerate(['CH0', 'CH1', 'CH2', 'BANK0', 'BANK1', 'BANK2', 'BANK_EN']):
                self.assertEqual(self.pin('U21', f'{port}{start+i}')['net'], [f'{prefix}_{name}'])
        self.assertEqual(self.pin('U21', 'PA0')['net'], ['ADC_SENSE'])

    def test_all_fpc_and_mux_channels(self):
        for pin in range(1, 41):
            self.assertEqual(self.parts['FPC1']['pins'][str(pin)]['net'], [f'KP{pin}'])
            for offset in [1, 6]:
                ref = 'U'+str(offset+(pin-1)//8)
                self.assertEqual(self.pin(ref, f'Y{(pin-1)%8}')['net'], [f'KP{pin}'])

    def test_decoders_and_rails(self):
        for decoder, offset, prefix, bus in [('U11', 1, 'SRC', 'SRC_BUS'), ('U12', 6, 'SNK', 'SINK_BUS')]:
            for group in range(5):
                mux = 'U'+str(offset+group)
                self.assertEqual(self.pin(decoder, f'#Y{4-group}')['node'], self.pin(mux, '#E')['node'])
                self.assertEqual(self.pin(mux, 'Z')['net'], [bus])
                self.assertEqual(self.pin(mux, 'VCC')['net'], ['USB_+5V'])
                self.assertEqual(self.pin(mux, 'VEE')['net'], ['GND'])
                for bit in range(3):
                    self.assertEqual(self.pin(mux, f'S{bit}')['net'], [f'{prefix}_CH{bit}'])
            for name in ['#E1', '#E2', 'GND']:
                self.assertEqual(self.pin(decoder, name)['net'], ['GND'])
            self.assertEqual(self.pin(decoder, 'E3')['net'], [prefix+'_BANK_EN'])
            for bit in range(3):
                self.assertEqual(self.pin(decoder, f'A{bit}')['net'], [f'{prefix}_BANK{bit}'])

    def test_resistors_and_usb(self):
        for ref, value, nets in [('R1', '2.7k', ['SRC_BUS', 'USB_+5V']), ('R2', '100', ['GND', 'SINK_BUS']), ('R3', '1k', ['ADC_SENSE', 'SINK_BUS']), ('R16', '10k', ['GND', 'SRC_BANK_EN']), ('R17', '10k', ['GND', 'SNK_BANK_EN'])]:
            self.assertEqual(self.parts[ref]['value'], value)
            self.assertEqual(sorted(p['net'][0] for p in self.parts[ref]['pins'].values()), sorted(nets))
        for mcu, resistor, net in [('PA11', 'R37', 'D-'), ('PA12', 'R36', 'D+')]:
            self.assertEqual(self.pin('U21', mcu)['node'], self.parts[resistor]['pins']['1']['node'])
            self.assertEqual(self.parts[resistor]['pins']['2']['net'], [net])
        self.assertEqual(self.pin('U22', '1')['node'], self.pin('U21', 'PH1_OSC_OUT')['node'])
        self.assertEqual(self.pin('U22', '2')['node'], self.pin('U21', 'PH0_OSC_IN')['node'])
        self.assertEqual(self.parts['U22']['value'], '8MHz')


if __name__ == '__main__':
    unittest.main()
