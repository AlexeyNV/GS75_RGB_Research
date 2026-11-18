# Журналы и электрические/оптические таблицы v0.4.4

Детектор сохраняет прежний формат `events.json` v0.4.3. Ни план PHOTO,
ни USB-времена не используются при поиске свечения. Новые таблицы — отдельный
post-hoc слой; ручные решения не переписывают автоматические события.

## Электрический журнал

`session.json` остаётся schema_version=1. Добавлены необязательные поля:

| Поле | Содержание |
|---|---|
| scenario | LED49_RGB_VIDEO_TEST / LED49_SHORT_PULSE_TEST |
| scenario_config | color, durations, repeats, pause_ms, initial_ms, final_ms, order, seed, marker |
| simulation | true только у имитатора; не аппаратная приёмка |
| project_binding | project_path, calibration link/version/hash и data_root; null, если ещё не выбран |
| analysis_profile | выбранный профиль анализа сценария |
| planned[].role / actual[].role | SHORT_PULSE, SYNC_MARKER или прежний EXPERIMENT |
| measurements[].stage_index / role | связь измерения с конкретной записью плана |
| measurements[].tx_ns / ack_ns / done_ns | фактические host monotonic timestamps |
| measurements[].off_confirmed | подтверждение OFF/STATUS после успешного PHOTO |

Существующие color/source/sink/id/duration_ms/current_avg_ua/current_max_ua/
samples/elapsed_ms/reason/fault/status сохранены. `events.jsonl` инкрементально
фиксирует TX/RX/этапы; `measurements.csv` — снимок измерений. JSON сохраняется
атомарно на важных переходах, ACK/DONE и окончании этапа. Частые CURRENT/ADC
не заставляют переписывать весь JSON, но остаются в инкрементальном JSONL.

При ошибке/отмене журнал сохраняет ABORTED/FAILED, незавершённое измерение и
полный planned. Нормализованный список включает ещё не выполненные операции
со статусом NOT_EXECUTED, ID/токами/timestamps=null. Подтверждение симуляции
не определяется только названием порта: это свойство внедрённого транспорта.

## Снимок соответствий

После оптического анализа создаётся новый `correspondence_<UUID>/`:

```text
electrical_operations.csv
optical_events.csv
electrical_optical_mapping.csv
short_pulse_summary.csv
experiment_mapping.json
```

`correspondence_link.json` указывает последний снимок и session.json;
`alignment.json` — последнее post-hoc соответствие. Их обновление не меняет
`events.json`, `frame_results.jsonl`, старые снимки и ручную историю
`manual_decisions.jsonl`. JSON использует null; CSV — пустую ячейку для
неизвестных значений. CSV имеет UTF-8 BOM для открытия в Windows.

## Нормализованные операции и события

`electrical_operations.csv` содержит каждую запланированную операцию:
experiment_id, уникальный operation_key (OP0001…), исходный operation_id MCU,
mode, stage_index, role, SOURCE/SINK, requested/measured duration, AVG/MAX,
ADC samples, fault, reason, electrical_status, command, host_tx_s/ack_s/done_s,
исходные ns, off_confirmed, UTC и simulation. operation_key отличает даже
неисполненные операции без ID и повторы одной электрической пары.

`optical_events.csv` использует все существующие поля автоматического события,
добавляя optical_track_id и отдельное operator_confirmation. Включены также
CANDIDATE/REJECTED; ни электрический ток, ни соседство не назначают PCB ID.

## electrical_optical_mapping.csv

Одна операция может иметь **несколько строк**, по одной на оптический источник.
При отсутствии события остаётся одна строка с пустыми оптическими полями.

| Группа полей | Значение |
|---|---|
| experiment_id, operation_key, operation_id, role | сессия, уникальная строка плана, MCU ID, роль маркера/опыта |
| source_kp, sink_kp | электрическое направление из журнала |
| requested_duration_ms, measured_duration_ms | запрос PHOTO и MCU ELAPSED_MS, не PTS-длительность света |
| current_avg_ua, current_max_ua, adc_samples, fault, electrical_status | данные STM32; неизвестное не заполняется нулём |
| optical_event_id, optical_track_id | событие и неизвестная позиция; track_id не является PCB LED ID |
| pcb_led_id, key_name, color | карта KNOWN или явно введённый оператором ID; неизвестный ID пуст |
| optical_start_pts, optical_end_pts | первый/последний ON PTS; границы наблюдений, не электрические фронты |
| optical_confidence, roi_coverage | эвристика детектора и покрытие ROI |
| signal_mean, chroma_mean | средние по сохранённым ON-строкам наблюдений этого события |
| alignment_confidence | UNIQUE_SEQUENCE / UNIQUE_SEQUENCE_WITH_MARKER либо пусто |
| alignment_uncertainty_s | observed residual + frame cadence + USB bracket envelope; не физический bound |
| operator_confirmation | ACCEPTED / REJECTED / RESET / пусто, отдельно от алгоритма |
| mapping_status, optical_status | состояние связи и состояние оптического результата |
| rejection_or_uncertainty_reason, simulation | объяснение и происхождение данных |

| mapping_status | Когда используется |
|---|---|
| VERIFIED | однозначная связь и явное ACCEPTED оператора; само по себе не доказывает PCB identity |
| OPTICAL_CANDIDATE | найдено однозначное алгоритмическое соответствие, ручная проверка ожидается |
| ELECTRICAL_ONLY | электрическая операция успешна, но времени/наблюдаемости для оптического вывода недостаточно |
| NO_OPTICAL_OBSERVATION | однозначная шкала и достоверный sampled OFF без события (optical_status=MISSED) |
| AMBIGUOUS | несколько равно поддержанных временных соответствий; offset пуст |
| REJECTED | оператор отклонил эту оптическую связь |
| FAILED_OPERATION | операция FAILED/ABORTED/NOT_EXECUTED; оптический успех ей не назначается |

## Short pulse summary

Маркер SYNC_MARKER исключён. Строки группируются по requested_duration_ms.
Сохраняются requested, completed, detected_operations, optical_events,
confirmed/candidate (события), confirmed_operations, missed, unobservable,
unaligned, failed_or_not_executed. Одна операция с двумя позициями увеличивает
optical_events, но не requested/detected_operations.

`start_residuals_s` / `end_residuals_s` и их средние — отклонения относительно
эмпирического USB/video преобразования; это не физическая точность фронтов.
`confidence_mean`, signal/chroma lists/means позволяют проверить уровень сигнала.
`confirmation_rate_wilson95` — интервал для доли подтверждённых операций среди
успешных электрических, а не гарантия экспозиции следующего видео.

`extra_optical_events_global` считает лишние несопоставленные CONFIRMED/CANDIDATE
всего опыта; это глобальная величина, её **не суммировать по длительностям**.
`operator_rejected_extras_global` — вручную отклонённые лишние события.
`false_detections` остаётся null, если есть непроверенные лишние события;
автоматика не объявляет их отражениями или ложными LED.
`false_detections_unreviewed` тоже null, пока нет полной проверки, иначе 0.

`series_minimum_all_confirmed_ms` в JSON требует ≥10 запросов, все успешно
завершены и подтверждены оптически, лишних событий нет. Это условный результат
данной серии с явным simulation flag. `minimum_reliable_duration_ms` остаётся
null до реальной повторной квалификации камеры/экспозиции/платы. Нельзя вывести
физическую надёжность из идеального имитатора или одного удачного импульса.

## Сопоставление шкал

Новый matcher использует не менее трёх разных завершённых операций, совместимый
цвет/KNOWN ID/наблюдаемый span, временную последовательность и при наличии
длинный маркер. Кандидатные сдвиги проверяются по всем операциям; каждый event
может принадлежать только одной операции, одна операция — нескольким разным
оптическим entity. Конкуренция событий одного entity/операции или равно
поддержанные разные сдвиги не разрешаются выбором ближайшего.

Связь: `host_relative_s = video_PTS_s + offset_s`. Используются фактические
TX/ACK/DONE и PTS; номинальное расписание не заменяет наблюдения, UTC телефона
и ПК не синхронизируются. Неподдержанный offset даёт NO_MATCH, конкурирующие
гипотезы — AMBIGUOUS. Медленный drift не подгоняется: drift_s_per_s=null,
статус NOT_FITTED_NO_INDEPENDENT_DRIFT_CALIBRATION. При несовместимом темпе
данные остаются несопоставленными. Успешный статус — ESTIMATED_NOT_HARDWARE_SYNC.

## Будущий PAIR scanner

`operations_from_probe(report)` — чистый read-only адаптер старых records
tools/rgb_probe.py: SOURCE/SINK, command_id, requested duration 10…300 мс,
AVG/MAX/samples/fault/status, UTC, current_candidate и simulation. Старые записи
не имеют host monotonic anchors, поэтому host_tx_s/ack_s/done_s остаются null.
Адаптер не восстанавливает их из UTC и не открывает порт.

Будущий исполнитель должен записывать каждую PAIR в единой monotonic шкале,
сохранять проверки FW/ARM/ADC/FAULT/OFF и ограничения 10…300 мс. Затем список
операций может использовать тот же `align_operations`/табличный контракт.
Автоматический PCB ID не появляется. Публичный `build_tables` пока читает
PHOTO session.json; готового GUI массового PAIR scan в этой версии нет.
