# Отчёт о проверках

## FW 0.1.1 — исправление ADC

По сообщению оператора, первый аппаратный запуск FW 0.1.0 подтвердил USB
DFU/CDC, PING/INFO/STATUS и DISARMED с SRC_EN=SNK_EN=0. Обнаружены
устаревший ADC (AGE_MS=115331, VALID=0) и SELFTEST ADC_INVALID.
Исправление и границы вывода о причине описаны в [adc.md](adc.md).
Аппаратная проверка FW 0.1.1 ещё не выполнялась.

В FW 0.1.1 ADC_Init/ADC_Poll вынесены в Core/Src/adc.c: одиночные
программные преобразования около 1 кГц, обработка OVR и тайм-аута 2 мс,
диагностика ADCSTATUS. ADC_STALE_MS=5 мс и коммутация не изменены.

Пройдены оба CTest: `firmware_logic` и `adc_acquisition`, четыре Python-теста
схемы. ADC-тесты используют настоящий модуль adc.c с моделью HAL, проверяют
10 секунд DISARMED по сетке 1 мс, продолжение сбора после ошибки без снятия
FAULT, нормальные/зависшие EOC, OVR, invalid raw, overcurrent, ошибки HAL,
SELFTEST/ARM и независимое аварийное отключение при прекращении ADC_Poll.

ARM GCC 14.3.1, CubeF4 1.28.3, CMake/Ninja: ELF/BIN/HEX собраны без
предупреждений. FLASH 23 108 байт; RAM 12 480 байт с резервом стека 4096 байт.
Счётчики/частота на реальной плате и точность ADC ещё требуют проверки.

Ниже сохранён отчёт исходной FW 0.1.0; его формулировки о том, что USB
не проверялся, относятся к первоначальной разработке до сообщения оператора.

## Выполнено программно для исходной FW 0.1.0

* Схема EasyEDA разобрана в таблицу соединений `schematic_nets.json`.
  Четыре Python-теста проверяют GPIO, все 80 связей каналов SOURCE/SINK,
  FPC 1–40, дешифраторы, питания, шунт, ограничитель и USB D+/D− через R36/R37.
* C-тесты компилируют настоящие App/Src модули под MSVC x64: все 40 адресов,
  1560 различных направленных пар, границы и недопустимые адреса, выключение
  перед изменением адресов и включением. Программный перебор не подаёт
  напряжение и не является электрическим сканированием.
* Проверены корректный PING/CRLF, ARM и PAIR/ACK/DONE, неправильные числа,
  переполнение unsigned, неверное число аргументов, нулевая/слишком большая
  длительность, неизвестная команда, длинная строка и NUL, заполненная RX-
  очередь, приоритет OFF, запрет параллельных PAIR.
* Проверены отключение по времени без CLI/TX обслуживания, устаревший ADC,
  saturation и overcurrent, FAULT latch/CLEARFAULT, GPIO fault, истечение ARM
  внутри импульса и uint32 rollover. Проверена монотонная и точная целочисленная
  формула для всех raw 0…4094, насыщение 4095 отклоняется.
* ARM GCC 14.3.1 + CubeF4 1.28.3: ELF/BIN/HEX собраны CMake/Ninja, собственный
  код с -Wall -Wextra -Werror. Предупреждений в финальной сборке нет.
  Официальный HAL flash_ex собирается с исключением unused-parameter;
  vendor-код не изменялся.
  Финальный размер: FLASH 22 236 байт, RAM 12 416 байт с резервом стека 4096 байт.
* Python-клиент проверен py_compile и --help. Реальный COM-порт не открывался.

## Проверено чтением конфигурации и кода

PLL M=8/N=192/P=2/Q=4, HSE 8 МГц → SYSCLK 96 МГц/USB 48 МГц.
ADC1 channel 0, PA0 analog, 12 bit, 24 МГц, 480 cycles; SWD сохраняется.
PA9/PA10 не конфигурируются USB MSP, VBUS sensing disabled.
EN записываются низкими до MODER, SysTick priority 0, USB priority 5.
USB FIFO в сумме 320 слов; FS CDC bulk EP1 и interrupt EP2.
TX-буфер сохраняется до complete, ожиданий TX в основном цикле нет.

## Не проверено

Физическая плата, USB enumeration/Windows driver, реальный ток и его точность,
длительности и фронты, отключение при Reset/suspend на плате, ориентация
разъёма, соответствие PCB схеме. Нет связи с измерительными приборами.
Host-модель не эмулирует периферию STM32 или USB host; HAL/USB проверены
ARM-компиляцией и чтением, но не реальным обменом. `.ioc` подготовлен вручную;
GUI CubeMX/CubeIDE и регенерация не проверены. Доставка ответов при потере
USB или заполнении TX не гарантируется. Аппаратный watchdog не реализован.

## Файлы

Основные оригинальные файлы: корневые README/LICENSE/.gitignore;
firmware/CMakeLists.txt, cmake/arm-gcc.cmake, STM32F411RE_FLASH.ld,
GS75_RGB_Research.ioc; Core/Inc и Core/Src; App/Inc и App/Src;
USB_DEVICE/App и USB_DEVICE/Target; tools/serial_console.py,
requirements.txt, check_schematic.py; tests/CMakeLists.txt, test_firmware.c,
test_schematic.py; docs/hardware.md, pin_mapping.md, protocol.md, safety.md,
bringup.md, verification.md, schematic_nets.json, dependencies.md.
Исходная схема сохранена без изменений в hardware/easyeda/.
Drivers, Middlewares, system-файл и startup — официальные зависимости ST.

## Git и публикация

Локальный репозиторий main создан. GitHub CLI отсутствует в PATH, публикация
не выполнялась. После установки CLI и авторизации из корня проекта:

```powershell
gh auth login
gh repo create AlexeyNV/GS75_RGB_Research --private --source . --remote origin --push
```

Перед командой убедиться, что репозитория ещё нет; если он уже создан,
использовать его origin и обычный push. Видимость private выбрана для
первоначальной публикации; при необходимости пользователь может выбрать public.
Существующий GS75_Keyboard не изменялся. Из-за разного владельца каталога
в sandbox Git запускался с разовым `-c safe.directory=<точный путь>`, без
изменения глобальных настроек. Автор initial commit взят из существующего
GS75_Keyboard; настройки Git других проектов не меняются.
