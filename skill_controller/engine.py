from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pynput import keyboard, mouse

from .models import IndependentAction, SequenceAction, SequenceStep, SkillDefinition


class InputSender:
    """统一串行发送键鼠，避免多个循环同时注入事件。"""

    def __init__(self) -> None:
        self.keyboard = keyboard.Controller()
        self.mouse = mouse.Controller()
        self.lock = threading.Lock()

    @staticmethod
    def normalize_key(value: str) -> keyboard.Key | str:
        aliases: dict[str, keyboard.Key | str] = {
            "space": keyboard.Key.space,
            "空格": keyboard.Key.space,
            "ctrl_l": keyboard.Key.ctrl_l,
            "左ctrl": keyboard.Key.ctrl_l,
            "ctrl_r": keyboard.Key.ctrl_r,
            "右ctrl": keyboard.Key.ctrl_r,
            "alt_l": keyboard.Key.alt_l,
            "左alt": keyboard.Key.alt_l,
            "alt_r": keyboard.Key.alt_r,
            "右alt": keyboard.Key.alt_r,
            "shift_l": keyboard.Key.shift_l,
            "左shift": keyboard.Key.shift_l,
            "shift_r": keyboard.Key.shift_r,
            "右shift": keyboard.Key.shift_r,
            "cmd_l": keyboard.Key.cmd_l,
            "左win": keyboard.Key.cmd_l,
            "cmd_r": keyboard.Key.cmd_r,
            "右win": keyboard.Key.cmd_r,
        }
        return aliases.get(value.strip().lower(), value.lower())

    def tap_key(self, value: str, duration_seconds: float = 0.05) -> None:
        key = self.normalize_key(value)
        with self.lock:
            self.keyboard.press(key)
        if duration_seconds > 0:
            time.sleep(duration_seconds)
        with self.lock:
            self.keyboard.release(key)

    def hold_key(self, value: str) -> None:
        key = self.normalize_key(value)
        with self.lock:
            self.keyboard.press(key)

    def release_key(self, value: str) -> None:
        key = self.normalize_key(value)
        with self.lock:
            self.keyboard.release(key)

    def click_mouse(self, value: str) -> None:
        button = {
            "left": mouse.Button.left,
            "right": mouse.Button.right,
            "middle": mouse.Button.middle,
        }.get(value.lower())
        if button is None:
            raise ValueError(f"不支持的鼠标按钮：{value}")
        with self.lock:
            self.mouse.click(button)


class SkillEngine:
    def __init__(self, status_callback: Callable[[str], None] | None = None) -> None:
        self.sender = InputSender()
        self.status_callback = status_callback or (lambda _message: None)
        self.state_lock = threading.Lock()
        self.master_enabled = True
        self.current_skill: SkillDefinition | None = None
        self.current_stop: threading.Event | None = None
        self.listener: keyboard.Listener | None = None
        self.held_keys: set[str] = set()
        self.trigger_down: set[str] = set()
        self.manual_space_held = False
        self.skills: list[SkillDefinition] = []
        self.hold_skill: SkillDefinition | None = None
        self.master_toggle_key = "f2"

    def set_skills(self, skills: list[SkillDefinition]) -> None:
        self.skills = skills

    def set_master_toggle_key(self, key: str) -> None:
        normalized = key.strip().lower()
        if not normalized:
            raise ValueError("总开关热键不能为空")
        self.master_toggle_key = normalized

    def status(self, message: str) -> None:
        self.status_callback(message)

    def start_listener(self) -> None:
        if self.listener is not None:
            return
        self.listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release,
        )
        self.listener.start()

    def stop_listener(self) -> None:
        if self.listener is not None:
            self.listener.stop()
            self.listener = None

    def set_master_enabled(self, enabled: bool) -> None:
        with self.state_lock:
            self.master_enabled = enabled
        if not enabled:
            self.stop_current()
            self.release_all(keep_manual_space=False)
            self.manual_space_held = False
            self.status("总开关已关闭")
        else:
            self.status("总开关已开启")

    def toggle_master(self) -> None:
        with self.state_lock:
            enabled = not self.master_enabled
        self.set_master_enabled(enabled)

    def stop_current(self) -> None:
        with self.state_lock:
            event = self.current_stop
            self.current_skill = None
            self.current_stop = None
        if event is not None:
            event.set()
        self.release_all(keep_manual_space=self.manual_space_held)

    def start_skill(self, skill: SkillDefinition) -> None:
        with self.state_lock:
            if not self.master_enabled:
                self.status("总开关已关闭，未启动技能")
                return
            had_previous_skill = self.current_skill is not None
        self.stop_current()
        event = threading.Event()
        with self.state_lock:
            self.current_skill = skill
            self.current_stop = event
        threading.Thread(
            target=self._run_skill,
            args=(skill, event, had_previous_skill),
            daemon=True,
        ).start()
        self.status(f"已启动技能：{skill.name}")

    def toggle_skill(self, skill: SkillDefinition) -> None:
        with self.state_lock:
            current = self.current_skill
        if current is not None and current.name == skill.name:
            self.stop_current()
            self.status(f"已停止技能：{skill.name}")
        else:
            self.start_skill(skill)

    def _is_current(self, skill: SkillDefinition, event: threading.Event) -> bool:
        with self.state_lock:
            return (
                self.master_enabled
                and self.current_skill is skill
                and self.current_stop is event
                and not event.is_set()
            )

    @staticmethod
    def _wait(event: threading.Event, seconds: float) -> bool:
        if seconds <= 0:
            return not event.is_set()
        return not event.wait(seconds)

    def _run_skill(
        self,
        skill: SkillDefinition,
        event: threading.Event,
        wait_before_start: bool,
    ) -> None:
        if wait_before_start and not self._wait(event, skill.switch_wait_seconds):
            return
        workers: list[threading.Thread] = []
        repeat = skill.trigger_mode != "once"
        for action in skill.independent_actions:
            worker = threading.Thread(
                target=self._run_independent,
                args=(skill, event, action, repeat),
                daemon=True,
            )
            workers.append(worker)
            worker.start()
        for action in skill.sequence_actions:
            worker = threading.Thread(
                target=self._run_sequence,
                args=(skill, event, action, repeat),
                daemon=True,
            )
            workers.append(worker)
            worker.start()

        if not workers:
            self.status(f"技能没有动作：{skill.name}")
        elif not repeat:
            for worker in workers:
                worker.join()
            with self.state_lock:
                still_current = self.current_skill is skill and self.current_stop is event
            if still_current:
                self.stop_current()
                self.status(f"一次性技能已完成：{skill.name}")

    def _run_independent(
        self,
        skill: SkillDefinition,
        event: threading.Event,
        action: IndependentAction,
        repeat: bool,
    ) -> None:
        if not self._wait(event, action.initial_delay_seconds):
            return
        while self._is_current(skill, event):
            self._execute_independent(event, action)
            if not repeat or not self._wait(event, action.interval_seconds):
                return

    def _execute_independent(self, event: threading.Event, action: IndependentAction) -> None:
        if action.kind == "mouse":
            self.sender.click_mouse(action.value)
            return
        key = self.sender.normalize_key(action.value)
        if action.press_mode == "hold":
            self.sender.hold_key(key)
            self._remember_held(key)
            if self._wait(event, action.hold_seconds):
                self.sender.release_key(key)
                self._forget_held(key)
            else:
                self.sender.release_key(key)
                self._forget_held(key)
            return
        self.sender.tap_key(key, action.tap_seconds)

    def _run_sequence(
        self,
        skill: SkillDefinition,
        event: threading.Event,
        action: SequenceAction,
        repeat: bool,
    ) -> None:
        if not self._wait(event, action.initial_delay_seconds):
            return
        while self._is_current(skill, event):
            for step in action.steps:
                if not self._is_current(skill, event):
                    return
                self._execute_step(event, step)
                if not self._wait(event, step.wait_after_seconds):
                    return
            if not repeat or not self._wait(event, action.interval_seconds):
                return

    def _execute_step(self, event: threading.Event, step: SequenceStep) -> None:
        if step.kind == "wait":
            return
        if step.kind == "mouse":
            self.sender.click_mouse(step.value)
            return
        key = self.sender.normalize_key(step.value)
        if step.press_mode == "hold":
            self.sender.hold_key(key)
            self._remember_held(key)
            if self._wait(event, step.hold_seconds):
                self.sender.release_key(key)
            else:
                self.sender.release_key(key)
            self._forget_held(key)
            return
        self.sender.tap_key(key, step.tap_seconds)

    def _remember_held(self, key: str) -> None:
        with self.state_lock:
            self.held_keys.add(key)

    def _forget_held(self, key: str) -> None:
        with self.state_lock:
            self.held_keys.discard(key)

    def release_all(self, keep_manual_space: bool) -> None:
        with self.state_lock:
            keys = tuple(
                key
                for key in self.held_keys
                if not (keep_manual_space and key == " ")
            )
            self.held_keys.difference_update(keys)
        for key in keys:
            self.sender.release_key(key)

    def toggle_manual_space(self) -> None:
        with self.state_lock:
            if not self.master_enabled:
                self.status("总开关已关闭，左 Ctrl 不执行空格操作")
                return
            enabled = not self.manual_space_held
            self.manual_space_held = enabled
        if enabled:
            self.sender.hold_key(" ")
            self._remember_held(" ")
            self.status("已按住空格")
        else:
            self.sender.release_key(" ")
            self._forget_held(" ")
            self.status("已松开空格")

    @staticmethod
    def _key_name(key: keyboard.Key | keyboard.KeyCode) -> str | None:
        if isinstance(key, keyboard.KeyCode):
            return key.char.lower() if key.char else None
        names = {
            keyboard.Key.ctrl_l: "ctrl_l",
            keyboard.Key.ctrl_r: "ctrl_r",
            keyboard.Key.alt_l: "alt_l",
            keyboard.Key.alt_r: "alt_r",
            keyboard.Key.shift_l: "shift_l",
            keyboard.Key.shift_r: "shift_r",
            keyboard.Key.space: "space",
        }
        for key_name in ("cmd_l", "cmd_r"):
            key_value = getattr(keyboard.Key, key_name, None)
            if key_value is not None:
                names[key_value] = key_name
        for number in range(1, 13):
            function_key = getattr(keyboard.Key, f"f{number}", None)
            if function_key is not None:
                names[function_key] = f"f{number}"
        return names.get(key)

    def on_key_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        name = self._key_name(key)
        if name is None or name in self.trigger_down:
            return
        self.trigger_down.add(name)
        if name == self.master_toggle_key:
            self.toggle_master()
            return
        if name == "ctrl_l":
            self.toggle_manual_space()
            return
        with self.state_lock:
            enabled = self.master_enabled
        if not enabled:
            self.status(f"总开关已关闭，未执行触发键：{name}")
            return
        for skill in self.skills:
            trigger = skill.trigger_key.strip().lower()
            if trigger != name:
                continue
            if skill.trigger_mode == "hold":
                self.hold_skill = skill
                self.start_skill(skill)
            elif skill.trigger_mode == "once":
                self.start_skill(skill)
            else:
                self.toggle_skill(skill)
            break

    def on_key_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        name = self._key_name(key)
        if name is None:
            return
        self.trigger_down.discard(name)
        if self.hold_skill is not None:
            if self.hold_skill.trigger_key.strip().lower() == name:
                with self.state_lock:
                    is_current = self.current_skill is self.hold_skill
                if is_current:
                    self.stop_current()
                    self.status(f"已停止技能：{self.hold_skill.name}")
                self.hold_skill = None

    def close(self) -> None:
        self.stop_listener()
        self.stop_current()
        self.release_all(keep_manual_space=False)
