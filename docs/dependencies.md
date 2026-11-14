# Зависимости

Официальный локальный SDK STM32Cube_FW_F4_V1.28.3:
CMSIS Core/Device, выбранные HAL F4, ST USB Device Core и CDC.
Источники: [ST CubeF4](https://github.com/STMicroelectronics/STM32CubeF4).
Использование примера CDC_Standalone SDK ограничено изучением HAL PCD glue;
сам USB-стек используется официальный. Версию SDK фиксируют эта запись и
включённые исходники, сборка не зависит от внешнего SDK.

Сохранены LICENSE.txt компонентов и Package_license.md CubeF4 в firmware/.
MIT в корне относится к оригинальному коду и документации проекта.
Startup/system взяты из STM32F4xx CMSIS Device, их условия см. Drivers/CMSIS/Device/ST/STM32F4xx/.
Настройки HAL основаны на официальном stm32f4xx_hal_conf_template.h.
Не используемые семейства CMSIS/Device headers оставлены как часть поставки,
цель сборки выбирается символом STM32F411xE.

Python-клиент: pyserial 3.5 (BSD); тесты схемы используют стандартную библиотеку.
Host C-тесты работают с MSVC либо GCC, target-сборка — ARM GNU toolchain.
Схема является пользовательским исходным документом, её происхождение и
лицензия не изменены данным проектом.
