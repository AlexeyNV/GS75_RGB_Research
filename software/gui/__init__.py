"""Qt graphical calibration and review tools."""


def ensure_fonts():
    """Qt offscreen on Windows may not enumerate fonts; load a system font only."""
    from pathlib import Path
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QFontDatabase,QFont
    if QFontDatabase.families(): return
    for name in ['C:/Windows/Fonts/segoeui.ttf','C:/Windows/Fonts/arial.ttf',
                 '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']:
        if Path(name).exists():
            identifier=QFontDatabase.addApplicationFont(name)
            families=QFontDatabase.applicationFontFamilies(identifier)
            if families:
                QApplication.instance().setFont(QFont(families[0],10)); return
