# Синтетический пример RGB Vision

synthetic/ содержит маленькие reference.png, off.png, red.png, green.png,
blue.png и calibration.json. Позиции LED49/LED50 и SyntheticKey вымышлены;
настоящая клавиша LED49 неизвестна. Это пример программного pipeline,
не оптическая верификация платы MSI.

```powershell
.\.venv\Scripts\python.exe tools/board_calibrator.py --calibration examples/vision/synthetic/calibration.json
.\.venv\Scripts\python.exe tools/analyze_images.py --calibration examples/vision/synthetic/calibration.json --off examples/vision/synthetic/off.png --on examples/vision/synthetic/red.png --output build/vision/example_red
```

Для GREEN/BLUE заменить red.png и каталог вывода. OFF и ON сделаны с
разными синтетическими преобразованиями камеры. LED49 имеет key_name=null.
Для генерации отдельного набора: `python examples/vision/generate_example.py
--output build/vision/example`. Существующий каталог не перезаписывается
без --overwrite. Реальные пользовательские фото генератор не читает.
