import sys

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from coll.ui.main_window import MainWindow
from coll.ui.startup import open_session


def main():
    QCoreApplication.setOrganizationName("AltameerCollections")
    QCoreApplication.setApplicationName("Collections")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setLayoutDirection(Qt.RightToLeft)
    if sys.platform == "win32":
        app.setFont(QFont("Segoe UI", 10))
    session = open_session()
    if not session:
        return 0
    win = MainWindow(*session)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
