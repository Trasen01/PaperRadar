from __future__ import annotations

QSS = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 14px;
    color: #172033;
}
QMainWindow, QWidget#AppRoot {
    background: #F6F8FB;
}
QFrame#Sidebar {
    background: #EDF3FA;
    border-right: 1px solid #DDE6F0;
}
QLabel#BrandTitle {
    font-size: 22px;
    font-weight: 800;
    color: #111827;
}
QLabel#BrandSubTitle, QLabel#Muted, QLabel#SmallMuted {
    color: #6B7890;
}
QLabel#SmallMuted { font-size: 12px; }
QPushButton#NavButton {
    background: transparent;
    border: none;
    border-radius: 12px;
    padding: 12px 14px;
    text-align: left;
    color: #344054;
    font-weight: 650;
    outline: none;
}
QPushButton#NavButton:hover {
    background: #F8FBFF;
    border: none;
}
QPushButton#NavButton:focus {
    outline: none;
    border: none;
}
QPushButton#NavButton[active="true"] {
    background: #EAF2FF;
    color: #2563EB;
    border-left: 4px solid #2563EB;
    padding-left: 10px;
}
QScrollArea { border: none; background: transparent; }
QWidget#PageCanvas { background: #F6F8FB; }
QFrame#Card, QFrame#HeaderCard, QFrame#DetailCard {
    background: #FFFFFF;
    border: 1px solid #E3EAF3;
    border-radius: 16px;
}
QFrame#MetricCard {
    background: #FFFFFF;
    border: 1px solid #E3EAF3;
    border-radius: 14px;
}
QFrame#HeroSignal {
    background: #0F172A;
    border-radius: 18px;
}
QFrame#EmptyPanel {
    background: #FBFDFF;
    border: 1px dashed #CBD8EA;
    border-radius: 14px;
}
QFrame#SummaryPanel {
    background: #F8FBFF;
    border: 1px solid #E3EAF3;
    border-radius: 14px;
}
QLabel#PageTitle {
    font-size: 28px;
    font-weight: 850;
    color: #101828;
}
QLabel#PageSubtitle {
    font-size: 14px;
    color: #66758F;
}
QLabel#SectionTitle {
    font-size: 17px;
    font-weight: 800;
    color: #172033;
}
QLabel#ProfileTitle {
    font-size: 24px;
    font-weight: 850;
    color: #101828;
}
QLabel#MetricLabel {
    color: #6B7890;
    font-size: 12px;
    font-weight: 650;
}
QLabel#MetricValue {
    color: #111827;
    font-size: 26px;
    font-weight: 850;
}
QLabel#Badge {
    border-radius: 8px;
    padding: 3px 10px;
    min-height: 24px;
    font-weight: 750;
    font-size: 12px;
}
QLabel#Badge[tone="blue"] { background: #E8F1FF; color: #1D4ED8; }
QLabel#Badge[tone="green"] { background: #EAF7EF; color: #15803D; }
QLabel#Badge[tone="amber"] { background: #FFF7E6; color: #B45309; }
QLabel#Badge[tone="red"] { background: #FFF1F0; color: #B42318; }
QLabel#Badge[tone="gray"] { background: #EEF2F7; color: #52637A; }
QPushButton {
    min-height: 34px;
    border-radius: 10px;
    padding: 8px 14px;
    font-weight: 750;
    outline: none;
}
QPushButton#PrimaryButton {
    background: #2563EB;
    border: 1px solid #2563EB;
    color: white;
}
QPushButton#PrimaryButton:hover { background: #1D4ED8; border-color: #1D4ED8; }
QPushButton#SecondaryButton {
    background: #FFFFFF;
    border: 1px solid #D7E0EA;
    color: #243449;
}
QPushButton#SecondaryButton:hover { background: #F3F7FC; border-color: #C7D6E8; }
QPushButton#DangerButton {
    background: #FFF1F0;
    border: 1px solid #FFD1CC;
    color: #B42318;
}
QPushButton#DangerButton:hover { background: #FFE3E0; }
QPushButton:disabled {
    background: #EEF2F7;
    border-color: #E4EAF2;
    color: #98A2B3;
}
QLineEdit, QTextEdit, QPlainTextEdit {
    background: #FFFFFF;
    border: 1px solid #D7E0EA;
    border-radius: 10px;
    padding: 8px 10px;
    min-height: 34px;
    selection-background-color: #DBEAFE;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #2563EB;
}
QComboBox {
    background: #FFFFFF;
    border: 1px solid #D7E0EA;
    border-radius: 10px;
    padding: 0px 34px 0px 12px;
    min-height: 36px;
    max-height: 36px;
    selection-background-color: #DBEAFE;
}
QComboBox:hover { border-color: #BFD0E5; background: #FBFDFF; }
QComboBox:focus { border: 1px solid #2563EB; background: #FFFFFF; }
QComboBox:disabled { background: #EEF2F7; color: #98A2B3; border-color: #E4EAF2; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 30px;
    border: none;
    background: transparent;
}
QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #64748B;
    margin-right: 12px;
}
QComboBox QAbstractItemView {
    show-decoration-selected: 0;
    background: #FFFFFF;
    border: 1px solid #D7E0EA;
    border-radius: 10px;
    padding: 6px;
    outline: none;
    selection-background-color: #EAF2FF;
    selection-color: #1D4ED8;
}
QComboBox QAbstractItemView::item {
    min-height: 30px;
    padding: 7px 10px;
    border-radius: 8px;
}
QComboBox QAbstractItemView::item:hover { background: #F3F7FC; }
QCheckBox {
    spacing: 9px;
    color: #344054;
    font-weight: 650;
}
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border-radius: 6px;
    border: 1px solid #BFD0E5;
    background: #FFFFFF;
}
QCheckBox::indicator:hover { border-color: #7AA7F7; background: #F3F7FC; }
QCheckBox::indicator:checked { border: 1px solid #2563EB; background: #2563EB; image: none; }
QCheckBox::indicator:checked:hover { background: #1D4ED8; border-color: #1D4ED8; }
QCheckBox::indicator:disabled { background: #EEF2F7; border-color: #E4EAF2; }
QCheckBox:disabled { color: #98A2B3; }
QTableWidget {
    background: #FFFFFF;
    alternate-background-color: #FBFDFF;
    border: 1px solid #E3EAF3;
    border-radius: 12px;
    gridline-color: transparent;
    selection-background-color: #DBEAFE;
    selection-color: #172033;
    outline: none;
}
QHeaderView::section {
    background: #F3F7FC;
    color: #66758F;
    border: none;
    border-bottom: 1px solid #E3EAF3;
    min-height: 38px;
    padding: 9px 8px;
    font-weight: 800;
}
QTableWidget::item {
    padding: 7px 8px;
    border-bottom: 1px solid #F1F4F8;
}
QTableWidget::item:hover { background: #F7FAFE; }


QPushButton#TableActionButton {
    min-width: 68px;
    max-width: 68px;
    min-height: 28px;
    max-height: 28px;
    padding: 3px 8px;
    border-radius: 8px;
    background: #FFFFFF;
    border: 1px solid #D7E0EA;
    color: #243449;
    font-weight: 750;
}
QPushButton#TableActionButton:hover { background: #F3F7FC; border-color: #C7D6E8; }
QPushButton#TableActionButton:disabled { background: #EEF2F7; border-color: #E4EAF2; color: #98A2B3; }

QTableWidget QPushButton#SecondaryButton {
    min-height: 26px;
    max-height: 28px;
    padding: 3px 10px;
    border-radius: 8px;
}

QScrollBar:vertical {
    background: transparent;
    border: none;
    margin: 0;
    width: 9px;
}
QScrollBar:horizontal {
    background: transparent;
    border: none;
    margin: 0;
    height: 9px;
}
QScrollBar::handle:vertical {
    background: #C6D4E6;
    border-radius: 4px;
    min-height: 32px;
}
QScrollBar::handle:horizontal {
    background: #C6D4E6;
    border-radius: 4px;
    min-width: 32px;
}
QScrollBar::handle:vertical:hover, QScrollBar::handle:horizontal:hover { background: #93A8C3; }
QScrollBar::add-line, QScrollBar::sub-line,
QScrollBar::add-page, QScrollBar::sub-page {
    border: none;
    background: transparent;
    width: 0;
    height: 0;
}

QDialog#ModernDialog, QMessageBox {
    background: #FFFFFF;
}
QLabel#DialogTitle {
    font-size: 20px;
    font-weight: 850;
    color: #101828;
}
QMessageBox QLabel {
    color: #344054;
    font-size: 14px;
}
QMessageBox QPushButton {
    min-width: 78px;
    min-height: 32px;
    border-radius: 9px;
    padding: 7px 14px;
    background: #FFFFFF;
    border: 1px solid #D7E0EA;
    color: #243449;
    font-weight: 750;
}
QMessageBox QPushButton:hover {
    background: #F3F7FC;
    border-color: #C7D6E8;
}

QProgressBar {
    border: none;
    border-radius: 8px;
    background: #EAF0F7;
    height: 10px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk {
    border-radius: 8px;
    background: #2563EB;
}
"""
