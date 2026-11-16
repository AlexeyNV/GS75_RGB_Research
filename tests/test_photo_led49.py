import io
import json
import unittest
from tools.photo_led49 import PhotoSession, PhotoError


class FakeCDC:
    """Actual FW spelling: PONG, multiline INFO, OK, ACK and correlated DONE."""
    def __init__(self, failure=None):
        self.t=0.; self.queue=[]; self.commands=[]; self.end=None; self.failure=failure

    def send(self, command):
        self.commands.append(command)
        if self.failure=='usb' and command.startswith('PHOTO'):
            raise OSError('USB removed')
        if command=='PING': self.queue.append('PONG')
        elif command=='INFO':
            version='0.1.1' if self.failure=='version' else '0.1.2'
            self.queue += [f'FW: {version}','MCU: STM32F411RET6','CAPABILITIES: PHOTO_LED49','END INFO']
        elif command=='STATUS':
            self.queue.append('OK STATE=DISARMED SRC=0 SNK=0 SRC_EN=0 SNK_EN=0 REMAIN_MS=0 FAULT=NONE MODE=NONE')
        elif command=='ADCSTATUS':
            valid=0 if self.failure=='adc' else 1
            self.queue.append(f'OK ADCSTATUS MODE=SINGLE_SW VALID={valid} HAS_SAMPLE=1 AGE_MS=0 ERRORS=0 OVR_COUNT=0')
        elif command=='SELFTEST': self.queue.append('OK SELFTEST=PASS STATE=DISARMED FAULT=NONE PHYSICAL_MUX=UNTESTED')
        elif command.startswith('ARM '): self.queue.append('OK ARM_TIMEOUT_S='+command.split()[1])
        elif command.startswith('PHOTO '):
            _,_,self.color,duration=command.split(); self.duration=int(duration)
            self.end=self.t+self.duration/1000
            sink={'RED':32,'GREEN':33,'BLUE':34}[self.color]
            self.queue.append(f'ACK ID=7 MODE=PHOTO LED=49 COLOR={self.color} SRC=14 SNK={sink} DURATION_MS={duration}')
            if self.failure=='err': self.queue=['ERR NOT_ARMED']
            if self.failure=='noack': self.queue=[]
        elif command=='CURRENT': self.queue.append('OK RAW=100 CURRENT_UA=806 AGE_MS=0 VALID=1')
        elif command=='OFF': self.queue.append('OK DISARMED')

    def read(self, timeout):
        self.t+=min(timeout,.01)
        if self.queue: return self.queue.pop(0)
        if self.end is not None and self.t>=self.end and self.failure!='missing':
            self.end=None
            if self.failure=='ctrlc': raise KeyboardInterrupt()
            ident=8 if self.failure=='id' else 7
            reason='ARM_EXPIRED' if self.failure=='expired' else 'TIMEOUT'
            fault='OVERCURRENT' if self.failure=='fault' else 'NONE'
            return f'DONE ID={ident} STATE=OFF CURRENT_AVG_UA=806 CURRENT_MAX_UA=900 SAMPLES={self.duration-1} FAULT={fault} REASON={reason} MODE=PHOTO LED=49 COLOR={self.color} ELAPSED_MS={self.duration}'
        return None


class PhotoTests(unittest.TestCase):
    def test_one_arm_photo_off_actual_protocol_and_timestamped_log(self):
        for color,duration in [('red',100),('green',5000),('blue',10000)]:
            fake=FakeCDC(); log=io.StringIO()
            session=PhotoSession(fake,log,lambda:fake.t,lambda _:None)
            done=session.run(color,duration)
            self.assertEqual(done['REASON'],'TIMEOUT'); self.assertTrue(session.off_confirmed)
            self.assertEqual(len([c for c in fake.commands if c.startswith('ARM ')]),1)
            self.assertEqual(len([c for c in fake.commands if c.startswith('PHOTO ')]),1)
            self.assertFalse(any(c.startswith('PAIR') for c in fake.commands))
            self.assertLess(fake.commands.index('ADCSTATUS'),next(i for i,c in enumerate(fake.commands) if c.startswith('ARM')))
            self.assertEqual(fake.commands[-1],'OFF')
            self.assertTrue(all('utc' in json.loads(line) for line in log.getvalue().splitlines()))

    def test_preflight_blocks_old_fw_or_bad_adc(self):
        for failure in ('version','adc'):
            fake=FakeCDC(failure); session=PhotoSession(fake,clock=lambda:fake.t,progress=lambda _:None)
            with self.assertRaises(PhotoError): session.run('red',100)
            self.assertFalse(any(c.startswith(('ARM ','PHOTO ')) for c in fake.commands))
            self.assertEqual(fake.commands[-1],'OFF')

    def test_protocol_and_transport_failures_stop_without_retry(self):
        for failure in ('usb','err','id','noack','missing','expired','fault','ctrlc'):
            with self.subTest(failure=failure):
                fake=FakeCDC(failure); session=PhotoSession(fake,clock=lambda:fake.t,progress=lambda _:None)
                with self.assertRaises((RuntimeError,OSError,KeyboardInterrupt)): session.run('red',100)
                self.assertEqual(fake.commands[-1],'OFF')
                self.assertEqual(len([c for c in fake.commands if c.startswith('ARM ')]),1)
                self.assertEqual(len([c for c in fake.commands if c.startswith('PHOTO ')]),1)

    def test_missing_usb_off_is_not_claimed_success(self):
        fake=FakeCDC('usb'); original=fake.send
        def send(command):
            if command=='OFF': raise OSError('Disconnected')
            original(command)
        fake.send=send; session=PhotoSession(fake,clock=lambda:fake.t,progress=lambda _:None)
        with self.assertRaises(OSError): session.run('red',100)
        self.assertFalse(session.off_confirmed)
        self.assertTrue(any(e['direction']=='ERROR' for e in session.events))

    def test_log_failure_during_active_photo_still_sends_off(self):
        fake=FakeCDC()
        class FailingLog:
            def write(self, text):
                if fake.end is not None: raise OSError('Disk full')
            def flush(self): pass
        session=PhotoSession(fake,FailingLog(),lambda:fake.t,lambda _:None)
        with self.assertRaises(OSError): session.run('red',5000)
        self.assertEqual(fake.commands[-1],'OFF')
        self.assertTrue(session.off_confirmed)
