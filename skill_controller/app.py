from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from qfluentwidgets import (
    ComboBox as FluentComboBox,
    DoubleSpinBox as FluentDoubleSpinBox,
    LineEdit as FluentLineEdit,
    ListWidget as FluentListWidget,
    PrimaryPushButton,
    PushButton as FluentPushButton,
    TableWidget as FluentTableWidget,
    Theme,
    setTheme,
    setThemeColor,
)

# Keep the Qt class names in the editor code so the existing dialogs and
# configuration behavior remain unchanged while the visible controls use the
# Fluent component library.
QComboBox = FluentComboBox
QDoubleSpinBox = FluentDoubleSpinBox
QLineEdit = FluentLineEdit
QListWidget = FluentListWidget
QPushButton = FluentPushButton
QTableWidget = FluentTableWidget

from .engine import SkillEngine
from .models import (
    IndependentAction,
    Profile,
    DEFAULT_TAP_SECONDS,
    SequenceAction,
    SequenceStep,
    SkillDefinition,
)
from .storage import load_profile, save_profile


APP_STYLE = """
QMainWindow, QWidget {
    background: #f4f7fb;
    color: #1f2937;
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    font-size: 13px;
}
QGroupBox {
    background: #ffffff;
    border: 1px solid #dbe3ee;
    border-radius: 10px;
    margin-top: 12px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 6px;
    color: #334155;
    background: #ffffff;
}
QLineEdit, QComboBox, QDoubleSpinBox {
    min-height: 31px;
    padding: 2px 9px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
}
QLineEdit:focus, QComboBox:focus, QDoubleSpinBox:focus {
    border: 1px solid #4f8cff;
}
QPushButton {
    min-height: 32px;
    padding: 0 14px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    color: #334155;
}
QPushButton:hover {
    background: #eef4ff;
    border-color: #8bb3ff;
}
QPushButton:pressed {
    background: #dceaff;
}
QPushButton#primaryButton {
    background: #2563eb;
    border-color: #2563eb;
    color: #ffffff;
    font-weight: 600;
}
QPushButton#primaryButton:hover {
    background: #1d4ed8;
}
QPushButton#masterButton {
    min-width: 128px;
    font-weight: 600;
}
QListWidget, QTableWidget {
    background: #ffffff;
    border: 1px solid #dbe3ee;
    border-radius: 8px;
    alternate-background-color: #f8fafc;
    selection-background-color: #dbeafe;
    selection-color: #1e3a8a;
}
QListWidget {
    padding: 5px;
}
QListWidget::item {
    padding: 10px 12px;
    border-radius: 6px;
}
QListWidget::item:selected {
    background: #dbeafe;
    color: #1d4ed8;
    font-weight: 600;
}
QHeaderView::section {
    background: #f1f5f9;
    border: none;
    border-bottom: 1px solid #dbe3ee;
    padding: 8px;
    color: #475569;
    font-weight: 600;
}
QTableWidget {
    gridline-color: #e5eaf1;
}
QLabel#pageTitle {
    color: #0f172a;
    font-size: 21px;
    font-weight: 700;
}
QLabel#pageSubtitle {
    color: #64748b;
    font-size: 12px;
}
QLabel#statusLabel {
    padding: 7px 12px;
    background: #eef2ff;
    border: 1px solid #c7d2fe;
    border-radius: 6px;
    color: #4338ca;
}
"""


def seconds_box(value: float = 0.0) -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setRange(0.0, 86400.0)
    box.setDecimals(3)
    box.setSingleStep(0.1)
    box.setValue(value)
    return box


def text_box(value: str = "") -> QLineEdit:
    box = QLineEdit()
    box.setText(value)
    return box


def table_box(rows: int, columns: int) -> QTableWidget:
    table = QTableWidget()
    table.setRowCount(rows)
    table.setColumnCount(columns)
    return table


class StatusBridge(QObject):
    message = Signal(str)


class IndependentActionDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        action: IndependentAction | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加独立循环动作")
        form = QFormLayout(self)
        action = action or IndependentAction()
        self.name = text_box(action.name)
        self.kind = QComboBox()
        self.kind.addItems(["key", "mouse"])
        self.kind.setCurrentText(action.kind)
        self.value = text_box(action.value)
        self.value.setPlaceholderText("键：ctrl_l / alt_l；鼠标：left / right / middle")
        self.press_mode = QComboBox()
        self.press_mode.addItems(["tap", "hold"])
        self.press_mode.setCurrentText(action.press_mode)
        self.tap_seconds = seconds_box(action.tap_seconds)
        self.interval = seconds_box(action.interval_seconds)
        self.initial_delay = seconds_box(action.initial_delay_seconds)
        self.hold_seconds = seconds_box(action.hold_seconds)
        form.addRow("名称", self.name)
        form.addRow("类型", self.kind)
        form.addRow("按键/鼠标", self.value)
        form.addRow("动作", self.press_mode)
        form.addRow("点按持续（秒）", self.tap_seconds)
        form.addRow("循环间隔（秒）", self.interval)
        form.addRow("首次延迟（秒）", self.initial_delay)
        form.addRow("按住时长（秒）", self.hold_seconds)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result(self) -> IndependentAction:
        return IndependentAction(
            name=self.name.text().strip() or "新动作",
            kind=self.kind.currentText(),
            value=self.value.text().strip(),
            press_mode=self.press_mode.currentText(),
            tap_seconds=self.tap_seconds.value(),
            interval_seconds=self.interval.value(),
            initial_delay_seconds=self.initial_delay.value(),
            hold_seconds=self.hold_seconds.value(),
        )


class SequenceDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        action: SequenceAction | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加顺序动作组")
        action = action or SequenceAction()
        self.steps: list[SequenceStep] = list(action.steps)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = text_box(action.name)
        self.interval = seconds_box(action.interval_seconds)
        self.initial_delay = seconds_box(action.initial_delay_seconds)
        form.addRow("名称", self.name)
        form.addRow("循环间隔（秒）", self.interval)
        form.addRow("首次延迟（秒）", self.initial_delay)
        layout.addLayout(form)

        self.table = table_box(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["类型", "按键/鼠标", "动作", "点按秒数", "按住秒数", "动作后等待"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table)

        add_row = QHBoxLayout()
        self.step_kind = QComboBox()
        self.step_kind.addItems(["key", "mouse", "wait"])
        self.step_value = text_box("t")
        self.step_value.setPlaceholderText("键名或 left / right / middle")
        self.step_mode = QComboBox()
        self.step_mode.addItems(["tap", "hold"])
        self.step_tap = seconds_box(DEFAULT_TAP_SECONDS)
        self.step_hold = seconds_box(0.0)
        self.step_wait = seconds_box(0.0)
        add_row.addWidget(self.step_kind)
        add_row.addWidget(self.step_value)
        add_row.addWidget(self.step_mode)
        add_row.addWidget(self.step_tap)
        add_row.addWidget(self.step_hold)
        add_row.addWidget(self.step_wait)
        add_button = QPushButton("添加步骤")
        add_button.clicked.connect(self.add_step)
        remove_button = QPushButton("删除步骤")
        remove_button.clicked.connect(self.remove_step)
        add_row.addWidget(add_button)
        add_row.addWidget(remove_button)
        layout.addLayout(add_row)

        for step in self.steps:
            self.add_step_row(step)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(760, 420)

    def add_step(self) -> None:
        step = SequenceStep(
            kind=self.step_kind.currentText(),
            value=self.step_value.text().strip(),
            press_mode=self.step_mode.currentText(),
            tap_seconds=self.step_tap.value(),
            hold_seconds=self.step_hold.value(),
            wait_after_seconds=self.step_wait.value(),
        )
        self.steps.append(step)
        self.add_step_row(step)

    def add_step_row(self, step: SequenceStep) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        values = [
            step.kind,
            step.value,
            step.press_mode,
            str(step.tap_seconds),
            str(step.hold_seconds),
            str(step.wait_after_seconds),
        ]
        for column, value in enumerate(values):
            self.table.setItem(row, column, QTableWidgetItem(value))

    def remove_step(self) -> None:
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
            self.steps.pop(row)

    def result(self) -> SequenceAction:
        return SequenceAction(
            name=self.name.text().strip() or "新顺序动作",
            interval_seconds=self.interval.value(),
            initial_delay_seconds=self.initial_delay.value(),
            steps=self.steps,
        )


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Skill Controller - 技能循环配置器")
        self.resize(1100, 720)
        self.setMinimumSize(900, 620)
        self.profile: Profile = load_profile()
        self.status_bridge = StatusBridge()
        self.status_bridge.message.connect(self.show_status)
        self.engine = SkillEngine(self.status_bridge.message.emit)
        self.engine.set_skills(self.profile.skills)
        self.engine.set_master_toggle_key(self.profile.master_toggle_key)
        self.loaded_row = -1
        self._build_ui()
        self._load_skill_list()
        self.engine.set_master_enabled(self.profile.master_enabled_by_default)
        self.master_button.setChecked(self.engine.master_enabled)
        self.engine.start_listener()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        title_layout = QVBoxLayout()
        title_layout.setSpacing(0)
        title = QLabel("Skill Controller")
        title.setObjectName("pageTitle")
        subtitle = QLabel("可视化配置键鼠技能循环")
        subtitle.setObjectName("pageSubtitle")
        title_layout.addWidget(title)
        title_layout.addWidget(subtitle)
        toolbar.addLayout(title_layout)
        toolbar.addStretch()
        self.master_button = QPushButton("总开关")
        self.master_button.setObjectName("masterButton")
        self.master_button.setCheckable(True)
        self.master_button.clicked.connect(self.toggle_master)
        toolbar.addWidget(self.master_button)
        toolbar.addWidget(QLabel("总开关热键"))
        self.master_key_edit = text_box(self.profile.master_toggle_key)
        self.master_key_edit.setPlaceholderText("例如 f2")
        self.master_key_edit.setMaximumWidth(90)
        self.master_key_edit.editingFinished.connect(self.update_master_hotkey)
        toolbar.addWidget(self.master_key_edit)
        save_button = PrimaryPushButton("保存配置")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self.save_current_profile)
        toolbar.addWidget(save_button)
        self.status_label = QLabel("准备就绪")
        self.status_label.setObjectName("statusLabel")
        toolbar.addWidget(self.status_label)
        root.addLayout(toolbar)

        body = QHBoxLayout()
        body.setSpacing(16)
        root.addLayout(body)

        left = QVBoxLayout()
        left.setSpacing(10)
        left_widget = QWidget()
        left_widget.setLayout(left)
        left_widget.setMinimumWidth(220)
        left_widget.setMaximumWidth(280)
        left.addWidget(QLabel("技能列表"))
        self.skill_list = QListWidget()
        self.skill_list.currentRowChanged.connect(self.load_selected_skill)
        left.addWidget(self.skill_list)
        skill_buttons = QHBoxLayout()
        add_skill = QPushButton("新建")
        add_skill.clicked.connect(self.add_skill)
        remove_skill = QPushButton("删除")
        remove_skill.clicked.connect(self.remove_skill)
        skill_buttons.addWidget(add_skill)
        skill_buttons.addWidget(remove_skill)
        left.addLayout(skill_buttons)
        body.addWidget(left_widget, 1)

        editor = QVBoxLayout()
        editor.setSpacing(12)
        trigger_box = QGroupBox("技能基本设置")
        trigger_layout = QGridLayout(trigger_box)
        self.name_edit = QLineEdit()
        self.trigger_edit = QLineEdit()
        self.trigger_edit.setPlaceholderText(
            "例如 d、f2、ctrl_l、alt_l；鼠标动作请在类型中选 mouse，再填 right"
        )
        self.trigger_mode = QComboBox()
        self.trigger_mode.addItem("按一下切换", "toggle")
        self.trigger_mode.addItem("按住运行", "hold")
        self.trigger_mode.addItem("按一下执行一次", "once")
        self.switch_wait = seconds_box(0.15)
        trigger_layout.addWidget(QLabel("名称"), 0, 0)
        trigger_layout.addWidget(self.name_edit, 0, 1)
        trigger_layout.addWidget(QLabel("触发键"), 0, 2)
        trigger_layout.addWidget(self.trigger_edit, 0, 3)
        trigger_layout.addWidget(QLabel("触发方式"), 1, 0)
        trigger_layout.addWidget(self.trigger_mode, 1, 1)
        trigger_layout.addWidget(QLabel("切换等待（秒）"), 1, 2)
        trigger_layout.addWidget(self.switch_wait, 1, 3)
        editor.addWidget(trigger_box)

        actions_box = QGroupBox("动作配置")
        actions_layout = QVBoxLayout(actions_box)
        self.action_table = table_box(0, 5)
        self.action_table.setHorizontalHeaderLabels(["类别", "名称", "内容", "间隔", "步骤数"])
        header = self.action_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self.action_table.cellDoubleClicked.connect(self.edit_action)
        actions_layout.addWidget(self.action_table)
        action_buttons = QHBoxLayout()
        add_independent = QPushButton("添加独立循环")
        add_independent.clicked.connect(self.add_independent)
        add_sequence = QPushButton("添加顺序动作组")
        add_sequence.clicked.connect(self.add_sequence)
        remove_action = QPushButton("删除选中动作")
        remove_action.clicked.connect(self.remove_action)
        action_buttons.addWidget(add_independent)
        action_buttons.addWidget(add_sequence)
        action_buttons.addWidget(remove_action)
        actions_layout.addLayout(action_buttons)
        editor.addWidget(actions_box, 1)
        body.addLayout(editor, 4)

    def _load_skill_list(self) -> None:
        self.skill_list.blockSignals(True)
        self.skill_list.clear()
        for skill in self.profile.skills:
            self.skill_list.addItem(QListWidgetItem(skill.name))
        self.skill_list.blockSignals(False)
        if self.profile.skills:
            self.skill_list.setCurrentRow(0)

    def current_skill(self) -> SkillDefinition | None:
        row = self.skill_list.currentRow()
        return self.profile.skills[row] if 0 <= row < len(self.profile.skills) else None

    def save_editor(self) -> None:
        if not (0 <= self.loaded_row < len(self.profile.skills)):
            return
        skill = self.profile.skills[self.loaded_row]
        skill.name = self.name_edit.text().strip() or "新技能"
        skill.trigger_key = self.trigger_edit.text().strip().lower()
        skill.trigger_mode = self.trigger_mode.currentData()
        skill.switch_wait_seconds = self.switch_wait.value()
        item = self.skill_list.item(self.loaded_row)
        if item is not None:
            item.setText(skill.name)
        self.engine.set_skills(self.profile.skills)

    def update_master_hotkey(self) -> None:
        key = self.master_key_edit.text().strip().lower()
        if not key:
            self.master_key_edit.setText(self.profile.master_toggle_key)
            return
        try:
            self.engine.set_master_toggle_key(key)
        except ValueError as exc:
            QMessageBox.warning(self, "热键无效", str(exc))
            self.master_key_edit.setText(self.profile.master_toggle_key)
            return
        self.profile.master_toggle_key = key
        self.show_status(f"总开关热键已设置为：{key}")

    def load_selected_skill(self, row: int) -> None:
        self.save_editor()
        self.loaded_row = row
        self.action_table.setRowCount(0)
        if not (0 <= row < len(self.profile.skills)):
            return
        skill = self.profile.skills[row]
        self.name_edit.setText(skill.name)
        self.trigger_edit.setText(skill.trigger_key)
        index = self.trigger_mode.findData(skill.trigger_mode)
        self.trigger_mode.setCurrentIndex(max(index, 0))
        self.switch_wait.setValue(skill.switch_wait_seconds)
        for action in skill.independent_actions:
            self.add_action_row("独立循环", action.name, action.value, action.interval_seconds, "")
        for action in skill.sequence_actions:
            self.add_action_row("顺序动作", action.name, "序列", action.interval_seconds, str(len(action.steps)))

    def add_action_row(self, category: str, name: str, content: str, interval: float, steps: str) -> None:
        row = self.action_table.rowCount()
        self.action_table.insertRow(row)
        for col, value in enumerate([category, name, content, f"{interval:g}", steps]):
            self.action_table.setItem(row, col, QTableWidgetItem(value))

    def add_skill(self) -> None:
        self.save_editor()
        self.profile.skills.append(SkillDefinition())
        self._load_skill_list()
        self.skill_list.setCurrentRow(len(self.profile.skills) - 1)

    def remove_skill(self) -> None:
        row = self.skill_list.currentRow()
        if row < 0:
            return
        self.engine.stop_current()
        self.profile.skills.pop(row)
        self._load_skill_list()

    def add_independent(self) -> None:
        skill = self.current_skill()
        if skill is None:
            return
        dialog = IndependentActionDialog(self)
        if dialog.exec() == QDialog.Accepted:
            skill.independent_actions.append(dialog.result())
            self.load_selected_skill(self.skill_list.currentRow())

    def add_sequence(self) -> None:
        skill = self.current_skill()
        if skill is None:
            return
        dialog = SequenceDialog(self)
        if dialog.exec() == QDialog.Accepted:
            result = dialog.result()
            if not result.steps:
                QMessageBox.warning(self, "无法添加", "顺序动作组至少需要一个步骤")
                return
            skill.sequence_actions.append(result)
            self.load_selected_skill(self.skill_list.currentRow())

    def edit_action(self, row: int, _column: int) -> None:
        skill = self.current_skill()
        if skill is None:
            return
        independent_count = len(skill.independent_actions)
        if row < independent_count:
            dialog = IndependentActionDialog(self, skill.independent_actions[row])
            if dialog.exec() == QDialog.Accepted:
                skill.independent_actions[row] = dialog.result()
        else:
            index = row - independent_count
            dialog = SequenceDialog(self, skill.sequence_actions[index])
            if dialog.exec() == QDialog.Accepted:
                result = dialog.result()
                if not result.steps:
                    QMessageBox.warning(self, "无法保存", "顺序动作组至少需要一个步骤")
                    return
                skill.sequence_actions[index] = result
        self.load_selected_skill(self.skill_list.currentRow())

    def remove_action(self) -> None:
        skill = self.current_skill()
        row = self.action_table.currentRow()
        if skill is None or row < 0:
            return
        independent_count = len(skill.independent_actions)
        if row < independent_count:
            skill.independent_actions.pop(row)
        else:
            skill.sequence_actions.pop(row - independent_count)
        self.load_selected_skill(self.skill_list.currentRow())

    def toggle_master(self, checked: bool) -> None:
        self.engine.set_master_enabled(checked)
        self.profile.master_enabled_by_default = checked
        self.update_master_style()

    def update_master_style(self) -> None:
        if self.master_button.isChecked():
            self.master_button.setText("总开关：已开启")
            self.master_button.setStyleSheet(
                "QPushButton#masterButton { background:#16a34a; border-color:#16a34a; color:white; }"
                "QPushButton#masterButton:hover { background:#15803d; }"
            )
        else:
            self.master_button.setText("总开关：已关闭")
            self.master_button.setStyleSheet(
                "QPushButton#masterButton { background:#dc2626; border-color:#dc2626; color:white; }"
                "QPushButton#masterButton:hover { background:#b91c1c; }"
            )

    def save_current_profile(self) -> None:
        self.save_editor()
        self.update_master_hotkey()
        self.profile.master_enabled_by_default = self.master_button.isChecked()
        path = save_profile(self.profile)
        self.show_status(f"配置已保存：{path}")

    def show_status(self, message: str) -> None:
        self.status_label.setText(message)
        self.update_master_style()

    def closeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self.save_current_profile()
        self.engine.close()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    setTheme(Theme.LIGHT)
    setThemeColor("#2563EB")
    app.setStyleSheet(APP_STYLE)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
