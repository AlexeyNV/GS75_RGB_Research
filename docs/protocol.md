# USB CDC протокол v0.1

ASCII, регистр команд верхний. Одна команда на строку, LF или CRLF.
Максимум 95 принятых байтов до LF (94 символа команды при CRLF).
Числа — только десятичные без знака; переполнение отклоняется.
Пустые строки игнорируются. Отправлять следующую команду после её ответа;
PAIR можно прервать OFF, а диагностику запрашивать во время импульса.
Не более трёх ожидающих команд. При переполнении/недопустимых байтах —
выключение, снятие ARM, `ERR RX_OVERFLOW`; остаток неверной строки игнорируется.
OFF/DISARM сбрасывают накопленную очередь и исполняются в RX callback до ответа.

| Команда | Ответ и действие |
|---|---|
| PING | `PONG` |
| INFO | поля `FW:`, `MCU:`, `BOARD:`, …, `STATE:`; конец `END INFO` |
| HELP | `OK COMMANDS=…`; ARM_s означает ARM с аргументом секунд |
| STATUS | `OK STATE=… SRC=… SNK=… SRC_EN=… SNK_EN=… REMAIN_MS=… FAULT=…` |
| ARM s | 1…60 с, `OK ARM_TIMEOUT_S=s`; DISARMED→IDLE; запрещена при ACTIVE/FAULT |
| PAIR src snk ms | KP 1…40, разные, 10…300 мс, только IDLE после ARM |
| OFF | немедленно выключить, снять ARM, `OK DISARMED`; FAULT сохраняется |
| DISARM | как OFF |
| CURRENT | последний корректный RAW/MV/CURRENT_UA, AVG_RAW/AVG_MV/AVG_UA до 8 отсчётов, AGE_MS, VALID=0/1 |
| DUMP | GPIOA_IDR/GPIOC_IDR, выбранные BANK/CH, raw ADC и FAULT |
| SELFTEST | пассивная проверка банков off, MODER/OTYPER, PA0 analog, свежести ADC; при ACTIVE — BUSY, при FAULT — FAULT_LATCHED |
| CLEARFAULT | выходы off, свежий допустимый ADC, GPIO; переход в DISARMED, требуется новый ARM |

`SRC/SNK` и адреса — последняя выбранная пара, даже после выключения.
Фактическое разрешение показывают EN. ID — uint32, начинается с 1 после Reset,
с переполнением; не является глобально уникальным между включениями питания.

```text
ACK ID=1 SRC=12 SNK=34 DURATION_MS=300
DONE ID=1 STATE=OFF CURRENT_AVG_UA=... CURRENT_MAX_UA=... SAMPLES=... FAULT=NONE REASON=TIMEOUT
```

ACK означает запуск, DONE — выключение и статистику взятых ADC-отсчётов.
Точки `...` здесь обозначают поля фактических данных, не демонстрационные измерения.
Без отсчётов DONE содержит `MEASUREMENT=UNAVAILABLE`, без подставных токов.
При OFF и аварии DONE также завершает текущий ID; причина OFF/ARM_EXPIRED/
USB_LOST/ADC_INVALID/OVERCURRENT. USB reset очищает транспорт, поэтому доставка
DONE при потере связи не гарантируется; после восстановления запросить STATUS.
`STATE=OFF` в DONE означает состояние выходов; машина может быть IDLE,
DISARMED или FAULT. При FAULT OFF подтверждает действие, но не снимает блокировку.

Ошибки: `ERR INVALID_PIN`, `SAME_PIN`, `INVALID_DURATION`, `INVALID_TIMEOUT`,
`NOT_ARMED`, `BUSY`, `ADC_INVALID`, `OVERCURRENT`, `GPIO_INVALID`,
`FAULT_LATCHED`, `SYNTAX`, `UNKNOWN_COMMAND`, `RX_OVERFLOW`.
FAULT хранится в STATUS и DONE; `TX_OVERFLOW` защёлкивается при заполнении TX.
Нельзя гарантировать отправку ERR через уже переполненный/отключённый USB.

RX callback принимает строки, работа команд идёт в main. TX имеет семь
доступных слотов по 512 байт, память пакета не меняется до TransmitCplt.
Заполненный TX не блокирует SysTick: выходы выключаются и защёлкивается FAULT.
Python-консоль выводит отдельные метки ACK/DONE/ERR, не запускает сканирование.
