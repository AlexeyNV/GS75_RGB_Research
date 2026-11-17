# RGB Vision v0.4.1 — программная приёмка 17.11.2026

**Результат: 104 Python-теста и 2 C-регрессии PASS.** Реальный STM32
агентом не подключался, выходы не включались. Новая вкладка ожидает
[операторского испытания](video_experiment.md#первое-реальное-испытание--выполняет-оператор).

Команды:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py' -v
ctest --test-dir build/host -C Debug --output-on-failure
```

Полный Python-прогон 81,145 с, exit=0; firmware_logic и adc_acquisition —
PASS, exit=0. Локальные полные логи: build/vision_v041/python-tests.log,
c-tests.log. Сохранены проверки прежнего калибратора, batch/реальных
OFF/R/G/B, видеоимпорта/seek/выбранных кадров, CLI, OFF-модели и Benchmark.

Состав изменения (30 файлов):

| Каталог | Созданы / изменены |
|---|---|
| software/hardware/ | новые __init__.py, scenario.py, experiment.py, journal.py, simulator.py, video_link.py |
| software/gui/ | новые experiment_pane.py, experiment_worker.py; изменён vision_window.py |
| tools/ | изменены photo_led49.py (общая диагностика/контроль) и docstring rgb_vision.py |
| tests/ | новые test_video_experiment.py, test_experiment_gui.py |
| корень | .gitignore, requirements-vision.txt, requirements-vision-lock.txt, README.md, PROJECT_CONTEXT.md |
| docs/ | hardware_validation.md, photo_mode.md |
| docs/vision/ | новые video_experiment.md, v041_validation.md, task_v0_4_1.md; изменены gui_architecture.md, video_performance.md |
| docs/vision/screenshots/ | новый v041_video_experiment.png |
| docs/vision/examples/v041_simulated/ | новые session.json, events.jsonl, measurements.csv, report.md |

Новый набор — 13 тестов исполнителя с множественными подслучаями и 8 GUI.
Сопоставление требований задания:

| Требование | Проверка |
|---|---|
| 1, 3, 4, 5, 6, 7, 20 | семь стадий OFF/R/OFF/G/OFF/B/OFF, три ARM 10, три PHOTO, ID 1/2/3, avg/max, MCU 5000 мс, полный OFF после подтверждения, финальные OFF+STATUS/EN0 |
| 2 | открытие GUI не запускает поток/порт; connect делает только диагностику; отмена диалога не отправляет ARM/PHOTO |
| 8, 9 | Event во время RED; OFF раньше DONE/TIMEOUT, нет GREEN/BLUE; тест и исполнителя, и кнопки Qt |
| 10, 11 | FAULT и ARM_EXPIRED прерывают первый цвет; нет повторного ARM/PHOTO/CLEARFAULT |
| 12, 13, 14 | USB, ADC на старте/при свечении, stale/OVR, неправильная FW/capability, SELFTEST/активные EN; журнал FAILED |
| 15 | ошибка доступа к занятому COM показывается, запуск блокируется |
| 16 | close во время RED: OFF, worker завершён, порт закрыт; при USB-потере отдельное предупреждение о питании |
| 17 | неполные аварийные JSON/JSONL, ошибка диска во время PHOTO всё равно инициирует OFF |
| 18 | новая уникальная сессия, прежние байты сохранены; последующие check/disconnect журнал не дописывают |
| 19 | внешний MP4, metadata/PTS, поздняя замена/history, без копирования; GUI передаёт путь в прежний просмотрщик и Benchmark |

Дополнительно: нет ACK/DONE/CURRENT, неверный ID, ток>2000/<100, отсутствие
выборок, неправильный elapsed, неподтверждённый OFF, Ctrl+C. Большое
расхождение с историческим током сохраняет предупреждение при соблюдении
жёстких ограничений. Все интервалы исполнителя используют управляемые
виртуальные часы; штатный сценарий не требует ожидания 31 реальной секунды.

Qt offscreen проверяет настоящие виджеты, диалог запуска, рабочий QThread
и передачу результатов. Отдельно запускалось обычное Windows-окно
(backend=windows) с имитатором, сохранён [скриншот](screenshots/v041_video_experiment.png).
Он явно помечен SIMULATOR ONLY и осмотрен визуально.

[session.json](examples/v041_simulated/session.json),
[events.jsonl](examples/v041_simulated/events.jsonl),
[measurements.csv](examples/v041_simulated/measurements.csv),
[report.md](examples/v041_simulated/report.md) — полный пример виртуального
31-секундного сценария. Это не новые электрические измерения. Токи заданы
имитатором по известным ориентирам; реальные UTC этого ускоренного прогона
не описывают длительность виртуальных импульсов.

Проверены SHA-256 **341 исходного файла** firmware/, data/, RGB_Vision/,
results/, docs/images/ и локальной карты: изменений 0. Git diff firmware/
пуст. Прошивка не собиралась заново и не прошивалась: исходники неизменны.
Пользовательские off_test_100ms.json, RGB_Vision/, config/gs75_board_calibration.json
и docs/images/ оставлены вне нового коммита.

Остались аппаратные вопросы: приёмка нового GUI/аварийного OFF, фактические
EN и время отключения, точность тока, поведение при зависании без IWDG,
реальный длинный MP4/VFR и его покадровая производительность. Наличие
USB ACK и программных тестов их не закрывает.
