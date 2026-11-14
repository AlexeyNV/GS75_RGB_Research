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
| ADCSTATUS | режим ADC, текущие EOC/OVR, счётчики запусков/выборок/ошибок, возраст данных; без изменения ADC или выходов |
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

## ADCSTATUS (FW 0.1.1)

Одна строка `OK ADCSTATUS MODE=SINGLE_SW …`. Поля:

| Поле | Значение |
|---|---|
| PERIOD_MS | заданный период запуска, сейчас 1 мс; реальная частота зависит от обслуживания main |
| EOC / OVR | текущие биты SR при снимке; EOC=1 до чтения результата допустим |
| PENDING | есть запущенное и ещё не обработанное преобразование |
| STARTS | успешно запущенные преобразования |
| SAMPLES / VALID_SAMPLES | прочитанные завершения / допустимые raw, включая сбор в DISARMED/FAULT |
| ERRORS | сумма событий OVR, timeout, start error, stop error и invalid raw |
| OVR_COUNT / TIMEOUTS | обнаруженные overrun / отсутствие своевременного результата |
| START_ERRORS / STOP_ERRORS / INVALID_SAMPLES | ошибки HAL/включения ADC, остановки при восстановлении и недопустимые raw |
| HAS_SAMPLE | получен хотя бы один допустимый отсчёт после старта прошивки |
| AGE_MS | возраст последнего допустимого отсчёта от момента его запуска; при HAS_SAMPLE=0 поле 0 не означает свежие данные |
| VALID | данные допустимы и AGE_MS≤5; это не разрешение выходов и не отсутствие FAULT |
| SR / LAST_SR / CR2 / HAL_ERROR | текущий SR, SR последнего ADC_Poll, CR2 и текущий HAL ErrorCode, hex |

Счётчики uint32 действуют с запуска прошивки, имеют переполнение и не
сбрасываются CLEARFAULT. LAST_SR не является защёлкнутым снимком аварии;
после восстановления текущий OVR может быть нулём, OVR_COUNT сохраняется.
HAL_ERROR может быть нулём после восстановления: polling не вызывает
HAL_ADC_IRQHandler, а HAL_Start очищает HAL ErrorCode. История — в счётчиках.
SAMPLES включает недопустимый raw; OVR/просроченный EOC отбрасываются без
чтения DR. OVR+EOC считается одним overrun, не успешным измерением.
OVERCURRENT отражается в STATUS/DONE FAULT; допустимый raw с высоким током
считается измерением, а не ошибкой чтения ADC. Потеря обслуживания main может
вызвать stale FAULT из SysTick до изменения счётчиков ADCSTATUS.
