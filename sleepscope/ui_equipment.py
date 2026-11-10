"""Equipment tab: record the machine, mask and supplies, and read how the data says they are being used."""
from __future__ import annotations
import datetime as dt
from PySide6 import QtCore, QtWidgets, QtGui
from . import equipment

SETTINGS = QtCore.QSettings('SleepScope', 'SleepScope')
NO_DATE = QtCore.QDate(2000, 1, 1)


def _combo(items, editable=True, completions=None):
    c = QtWidgets.QComboBox(); c.setEditable(editable); c.addItems(items)
    if editable:
        c.setInsertPolicy(QtWidgets.QComboBox.NoInsert)
        if completions:
            comp = QtWidgets.QCompleter(completions, c); comp.setCaseSensitivity(QtCore.Qt.CaseInsensitive); comp.setFilterMode(QtCore.Qt.MatchContains); c.setCompleter(comp)
    return c


def _set(c, v):
    i = c.findText(v or '')
    if i >= 0: c.setCurrentIndex(i)
    elif c.isEditable(): c.setEditText(v or '')


class DateField(QtWidgets.QWidget):
    """Date with a 'not recorded' state and a Today button."""
    def __init__(self):
        super().__init__(); lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0)
        self.d = QtWidgets.QDateEdit(calendarPopup=True); self.d.setDisplayFormat('MMM d, yyyy'); self.d.setMinimumDate(NO_DATE)
        self.d.setSpecialValueText('not recorded'); self.d.setDate(NO_DATE); lay.addWidget(self.d, 1)
        t = QtWidgets.QPushButton('Today'); t.setFixedWidth(56); t.clicked.connect(lambda: self.d.setDate(QtCore.QDate.currentDate())); lay.addWidget(t)
    def value(self):
        return '' if self.d.date() == NO_DATE else self.d.date().toPython().isoformat()
    def set_value(self, iso):
        try: self.d.setDate(QtCore.QDate(dt.date.fromisoformat(iso)) if iso else NO_DATE)
        except ValueError: self.d.setDate(NO_DATE)


class EquipmentView(QtWidgets.QWidget):
    saved = QtCore.Signal()

    def __init__(self):
        super().__init__(); self.nights = []; self.ident = {}
        lay = QtWidgets.QHBoxLayout(self); lay.setContentsMargins(6, 6, 6, 6)
        split = QtWidgets.QSplitter(); lay.addWidget(split)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QtWidgets.QFrame.NoFrame); scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        form_w = QtWidgets.QWidget(); fl = QtWidgets.QVBoxLayout(form_w); fl.setContentsMargins(4, 4, 8, 4); scroll.setWidget(form_w)

        g = QtWidgets.QGroupBox('Machine'); f = QtWidgets.QFormLayout(g); fl.addWidget(g)
        self.machine_brand = _combo(equipment.MACHINE_BRANDS); f.addRow('Brand', self.machine_brand)
        self.machine_model = _combo(['', 'AirSense 10 AutoSet', 'AirSense 10 Elite', 'AirSense 10 CPAP', 'AirSense 11 AutoSet', 'AirSense 11 Elite']); f.addRow('Model', self.machine_model)
        self.humidifier = _combo(['', 'Off', 'Auto', 'Manual, level 1', 'Manual, level 2', 'Manual, level 3', 'Manual, level 4', 'Manual, level 5', 'Manual, level 6', 'Manual, level 7', 'Manual, level 8']); f.addRow('Humidifier', self.humidifier)
        self.heated_tube = _combo(['', 'Yes', 'No'], editable=False); f.addRow('Heated tube', self.heated_tube)

        g = QtWidgets.QGroupBox('Mask'); f = QtWidgets.QFormLayout(g); fl.addWidget(g)
        self.mask_type = _combo(equipment.MASK_TYPES, editable=False); f.addRow('Type', self.mask_type)
        self.mask_brand = _combo(equipment.MASK_BRANDS); f.addRow('Brand', self.mask_brand)
        self.mask_model = _combo([''] + equipment.MODEL_SUGGESTIONS, completions=equipment.MODEL_SUGGESTIONS)
        self.mask_model.setToolTip('Type to search, or enter any model'); f.addRow('Model', self.mask_model)
        self.mask_size = _combo(equipment.SIZES); f.addRow('Size', self.mask_size)
        self.chinstrap = _combo(['', 'Yes', 'No'], editable=False); f.addRow('Chinstrap', self.chinstrap)
        self.change_date = QtWidgets.QDateEdit(calendarPopup=True); self.change_date.setDisplayFormat('MMM d, yyyy'); self.change_date.setDate(QtCore.QDate.currentDate())
        self.change_date.setToolTip('When you change the mask, SleepScope keeps the old one and compares the nights before and after this date.')
        f.addRow('New mask started on', self.change_date)

        g = QtWidgets.QGroupBox('Last replaced'); f = QtWidgets.QFormLayout(g); fl.addWidget(g)
        self.dates = {}
        for item, label, _, _ in equipment.SUPPLIES:
            self.dates[item] = DateField(); f.addRow(label, self.dates[item])

        g = QtWidgets.QGroupBox('Notes (sent to Claude with your questions)'); gl = QtWidgets.QVBoxLayout(g); fl.addWidget(g)
        self.notes = QtWidgets.QPlainTextEdit(); self.notes.setFixedHeight(64); self.notes.setPlaceholderText('e.g. wake with a dry mouth, mask marks on the bridge of the nose, sleep on my side'); gl.addWidget(self.notes)
        row = QtWidgets.QHBoxLayout(); fl.addLayout(row)
        sv = QtWidgets.QPushButton('Save equipment'); sv.setDefault(True); sv.clicked.connect(self.save); row.addWidget(sv); row.addStretch()
        self.status = QtWidgets.QLabel(''); self.status.setStyleSheet('color:#52514e'); self.status.setWordWrap(True); fl.addWidget(self.status); fl.addStretch()

        self.report = QtWidgets.QTextBrowser(); self.report.setOpenExternalLinks(True); self.report.setStyleSheet('font-size:13px; padding:8px')
        split.addWidget(scroll); split.addWidget(self.report); split.setSizes([400, 800])
        self.load()

    # ------------------------------------------------------------------ profile
    def profile(self) -> dict:
        p = equipment.load_profile(SETTINGS)
        p.update(machine_brand=self.machine_brand.currentText().strip(), machine_model=self.machine_model.currentText().strip(),
                 humidifier=self.humidifier.currentText().strip(), heated_tube=self.heated_tube.currentText(),
                 mask_type=self.mask_type.currentText(), mask_brand=self.mask_brand.currentText().strip(), mask_model=self.mask_model.currentText().strip(),
                 mask_size=self.mask_size.currentText().strip(), chinstrap=self.chinstrap.currentText(), notes=self.notes.toPlainText().strip(),
                 replaced={k: w.value() for k, w in self.dates.items() if w.value()})
        return p

    def load(self):
        p = equipment.load_profile(SETTINGS)
        for c, k in ((self.machine_brand, 'machine_brand'), (self.machine_model, 'machine_model'), (self.humidifier, 'humidifier'), (self.heated_tube, 'heated_tube'),
                     (self.mask_type, 'mask_type'), (self.mask_brand, 'mask_brand'), (self.mask_model, 'mask_model'), (self.mask_size, 'mask_size'), (self.chinstrap, 'chinstrap')):
            _set(c, p.get(k, ''))
        self.notes.setPlainText(p.get('notes', ''))
        for k, w in self.dates.items(): w.set_value((p.get('replaced') or {}).get(k, ''))
        self.refresh()

    def save(self):
        p = self.profile()
        brand, model = equipment.split_brand(p['mask_model'])      # a model picked from the list carries its brand
        if brand:
            p['mask_brand'], p['mask_model'] = brand, model; _set(self.mask_brand, brand); _set(self.mask_model, model)
        before = equipment.load_profile(SETTINGS)
        equipment.save_profile(SETTINGS, p, self.change_date.date().toPython())
        changed = len(p.get('history') or []) > len(before.get('history') or [])
        self.status.setText('Saved.' + (f' The previous mask is kept, and the nights before and after {self.change_date.date().toPython():%b %d} are compared on the right.' if changed else ''))
        self.refresh(); self.saved.emit()

    # ------------------------------------------------------------------ data
    def set_nights(self, nights):
        self.nights = nights or []; self.refresh()

    def set_identification(self, ident):
        self.ident = ident or {}
        model = (self.ident.get('model') or '').strip()
        if model and model != '?':
            self.machine_model.lineEdit().setPlaceholderText(model)
            if not self.machine_model.currentText().strip(): _set(self.machine_model, model.replace('ResMed ', ''))
            if not self.machine_brand.currentText().strip() and self.ident.get('serial'): _set(self.machine_brand, 'ResMed')
        self.refresh()

    def refresh(self):
        self.report.setHtml(equipment.report_html(self.nights, self.profile(), self.ident))
