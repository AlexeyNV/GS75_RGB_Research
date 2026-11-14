# GS75_RGB_Research

Для продолжения на другом компьютере или в новом сеансе VSCode:
[контекст проекта, статус испытаний и команды переноса](PROJECT_CONTEXT.md).

Диагностическая прошивка STM32F411RET6 для исследования контактов RGB-платы
MSI GS75. Независимый проект; [основной проект клавиатуры](https://github.com/AlexeyNV/GS75_Keyboard)
изучен как пример организации HAL, USB и host-тестов и не изменялся.

**Первый запуск — без оригинальной RGB-платы и с разомкнутой U13.**

## Статус

| Статус | Результат |
|---|---|
| Implemented | FW 0.1.1: USB CDC, все команды, ADCSTATUS, одиночный ADC около 1 кГц с обработкой OVR/тайм-аута, ARM/FAULT и отключение SysTick, Python-консоль |
| Build verified | ARM GCC 14.3.1, CubeF4 1.28.3, CMake/Ninja; ELF/BIN/HEX собраны; host-тесты MSVC и проверка соединений EasyEDA |
| Hardware verified | FW 0.1.1 записана через USB DFU; оператор подтвердил USB CDC, PING/INFO/STATUS, ADC без ошибок, SELFTEST=PASS и направления KP35→KP27 / KP27→KP35 на 1 кОм при U13 open. Остальные каналы, физический OFF и точность тока ещё не проверены |

Протокол: [docs/hardware_validation.md](docs/hardware_validation.md).
ADCSTATUS: SAMPLES=VALID_SAMPLES=146796, ERRORS=0, OVR_COUNT=0,
AGE_MS=0, VALID=1. На нагрузке получены средние токи 1249/1253 мкА
для PAIR 35 27 300 и 1254/1254 мкА для PAIR 27 35 300; каждый опыт
содержал 299–300 отсчётов, FAULT=NONE, REASON=TIMEOUT. После испытаний
STATUS=IDLE, SRC_EN=0, SNK_EN=0. Это не проверка всех 40 контактов
и не подтверждение точности калибровки.

`.ioc` содержит конфигурацию для CubeMX; открытие и регенерация в GUI ещё не
проверены. Проверяемый исходный проект — CMake с включёнными в репозиторий
официальными библиотеками ST. Подробнее: [firmware/README.md](firmware/README.md).

## Аппаратура

U21 — STM32F411RET6, LQFP64, питание 3,3 В; U22 — кварц 8 МГц.
U1–U5 (74HCT4051) подключают SOURCE, U6–U10 — SINK. U11/U12 (74HCT138)
выбирают один из пяти банков. Логика HCT питается от USB 5 В.
FPC1 имеет 40 сигнальных контактов KP1–KP40 и два контакта экрана GND.
R1=2,7 кОм ограничивает ток, R2=100 Ом измеряет его, R3=1 кОм и C15=10 нФ
образуют входную цепь ADC. R18=1,5 кОм с U13 — дополнительная ветвь,
в первой версии U13 должна быть разомкнута.

`channel=(pin-1)%8`, `bank=4-(pin-1)/8`. Формула проверена по исходной
EasyEDA-схеме для обеих групп. Перед сменой адресов обе группы отключаются;
после пауз 10 мкс на отключение и 10 мкс на установление адреса включается
сначала SINK, затем SOURCE. Таблицы и источники: [docs/hardware.md](docs/hardware.md),
[docs/pin_mapping.md](docs/pin_mapping.md).

## Сборка и прошивка

В терминале с ARM GCC, CMake и Ninja в PATH, из корня проекта:

```powershell
cmake -S firmware -B build/firmware -G Ninja '-DCMAKE_TOOLCHAIN_FILE=cmake/arm-gcc.cmake'
cmake --build build/firmware
STM32_Programmer_CLI -c port=SWD -w build/firmware/GS75_RGB_Research.elf -v -rst
```

Последняя команда требует физического ST-Link и подготовленной платы; здесь
не выполнялась. ELF/BIN/HEX находятся в `build/firmware/` и не включаются в Git.
Сборка не требует скачивания SDK. CubeIDE: импортировать CMake-проект, выбрать
STM32 toolchain и файл `firmware/cmake/arm-gcc.cmake`; импорт в GUI не проверен.

## USB CDC

```powershell
python -m pip install -r tools/requirements.txt
python tools/serial_console.py --port COM7
```

Начать с `PING`, `INFO`, `ADCSTATUS`, `CURRENT`, `SELFTEST`, `STATUS`.
В DISARMED счётчик SAMPLES должен увеличиваться примерно на 1000 в секунду,
AGE_MS оставаться малым, ERRORS/OVR_COUNT/TIMEOUTS не расти, VALID=1.
Причина и проверка исправления описаны в [docs/adc.md](docs/adc.md).
Только после проверки приборами
и установки контрольного резистора 1 кОм между испытанными KP27/KP35:

```text
ARM 60
PAIR 35 27 300
CURRENT
OFF
```

PAIR выдаёт `ACK ID=…`, затем асинхронный `DONE ID=…` с фактическими выборками
ADC. При отсутствии выборок передаётся `MEASUREMENT=UNAVAILABLE`.
`OFF` немедленно отключает выходы и снимает ARM. Протокол описан в
[docs/protocol.md](docs/protocol.md).

## Проверки

```powershell
python -m unittest discover -s tests -p 'test_*.py' -v
cmake -S tests -B build/host -G 'Visual Studio 17 2022' -A x64
cmake --build build/host --config Debug
ctest --test-dir build/host -C Debug --output-on-failure
```

Host-тесты компилируют настоящий прикладной C-код; GPIO заменены моделью.
На Linux можно использовать обычный GCC и генератор Ninja. Итоги и ограничения:
[docs/verification.md](docs/verification.md).

## Ограничения и дальнейшие шаги

Импульсы 10–300 мс, ARM максимум 60 с, аварийный предел 2000 мкА.
Пределы задаются только при компиляции в `board_config.h`.
Неизвестная RGB-плата пока не подключается. Точность ADC не калибрована;
нулевой ADC не доказывает исправность цепи. Программная защита не заменяет R1.
VID/PID 0483:5740 используются только для прототипа; собственного USB VID нет.
Непроверенными остаются физическое аварийное отключение OFF во время
импульса, остальные каналы, точность измерения тока и подключение
оригинальной RGB-платы MSI. Следующий этап: тест OFF на контрольной
нагрузке, измерение резисторов на RGB-плате и подготовка безопасного
первого подключения. Порядок проверок: [docs/bringup.md](docs/bringup.md),
текущие результаты: [docs/hardware_validation.md](docs/hardware_validation.md).
Камера, GUI, PWM и массовое сканирование не реализованы.
