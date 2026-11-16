#!/usr/bin/env python3
"""F2 总开关 + D/F/S 三种技能模式控制器。

快捷键可在配置区修改。默认快捷键：
    F2  总开关
    左 Ctrl  切换按住/松开空格
    D   当前是 D/S 循环时停止全部循环；空闲时启动 D（T/W/1/2 循环）
    F   鼠标左键每 0.2 秒点击一次，并执行 T -> 等待 -> 按住 Q 2.5 秒 -> R
    S   空格 -> 等待 -> T，循环
    S 循环期间，数字 1 每 2 秒一次，数字 2 每 3 秒一次
    D 循环期间，T 每 3 秒一次，W/1/2 每 5 秒一次
    Ctrl+C 退出

依赖：
    python3 -m pip install pynput
"""

from __future__ import annotations

import threading
import time
from enum import Enum, auto

from pynput import keyboard, mouse


class SkillMode(Enum):
    NONE = auto()
    D = auto()
    F = auto()
    S = auto()


class F2SkillSwitchController:
    # ==================== 可修改配置 ====================
    TOTAL_SWITCH_KEY = keyboard.Key.f2
    LEFT_CTRL_KEY = keyboard.Key.ctrl_l
    D_KEY = "d"
    F_KEY = "f"
    S_KEY = "s"

    MOUSE_CLICK_INTERVAL_SECONDS = 0.2  # 鼠标左键点击间隔：0.2 秒
    MODE_SWITCH_WAIT_SECONDS = 0.15  # 任意技能切换时，停止旧技能后等待：0.15 秒
    F_T_TO_Q_WAIT_SECONDS = 0.2  # F 中按 T 后，按 Q 前等待：0.2 秒
    F_Q_HOLD_SECONDS = 2.5  # F 中 Q 的按住时长：2.5 秒
    ONE_INTERVAL_SECONDS = 2.0  # S 模式中按数字 1 的间隔：2 秒
    TWO_INTERVAL_SECONDS = 3.0  # S 模式中按数字 2 的间隔：3 秒
    D_T_INTERVAL_SECONDS = 2.0  # D 模式中 T 首次立即按，之后每隔 2 秒按一次
    D_W_INTERVAL_SECONDS = 5.0  # D 模式中按 W 的间隔：5 秒
    D_ONE_INTERVAL_SECONDS = 5.0  # D 模式中按数字 1 的间隔：5 秒
    D_TWO_INTERVAL_SECONDS = 5.0  # D 模式中按数字 2 的间隔：5 秒
    S_SPACE_TO_T_WAIT_SECONDS = 0.3  # S 中按空格后，按 T 前等待：0.3 秒
    S_AFTER_T_WAIT_SECONDS = 0.1  # S 中按 T 后，下一轮开始前等待：0.1 秒
    POLL_INTERVAL_SECONDS = 0.005  # 状态检测间隔：0.005 秒

    # ==================== 状态与输入 ====================
    def __init__(self) -> None:
        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()
        self.state_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.change_event = threading.Event()
        self.stop_event = threading.Event()

        self.enabled = True
        self.mode = SkillMode.NONE
        self.pressed_keys: set[str] = set()
        self.key_down_state: dict[str, bool] = {}
        self.mode_switch_wait_required = False
        self.manual_space_held = False

    def is_enabled(self) -> bool:
        with self.state_lock:
            return self.enabled

    def get_mode(self) -> SkillMode:
        with self.state_lock:
            return self.mode

    def is_mode_active(self, mode: SkillMode) -> bool:
        with self.state_lock:
            return self.enabled and self.mode is mode

    def tap_key(self, key: str) -> None:
        with self.send_lock:
            self.keyboard_controller.press(key)
            self.keyboard_controller.release(key)

    def press_and_hold(self, key: str) -> None:
        with self.send_lock:
            self.keyboard_controller.press(key)
        with self.state_lock:
            self.pressed_keys.add(key)

    def release_key(self, key: str) -> None:
        with self.send_lock:
            self.keyboard_controller.release(key)
        with self.state_lock:
            self.pressed_keys.discard(key)

    def release_all_held_keys(self, keep_manual_space: bool = False) -> None:
        with self.state_lock:
            keys = tuple(
                key
                for key in self.pressed_keys
                if not (keep_manual_space and key == " ")
            )
            self.pressed_keys.difference_update(keys)
        if keys:
            with self.send_lock:
                for key in keys:
                    self.keyboard_controller.release(key)

    def wait_for_current_mode(self, seconds: float, mode: SkillMode) -> bool:
        """等待期间如果模式切换、总开关关闭或脚本退出，则立即返回 False。"""
        deadline = time.monotonic() + seconds
        while not self.stop_event.is_set():
            if not self.is_mode_active(mode):
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            self.change_event.wait(min(remaining, self.POLL_INTERVAL_SECONDS))
            self.change_event.clear()
        return False

    def set_mode(self, new_mode: SkillMode) -> None:
        with self.state_lock:
            if not self.enabled:
                return
            old_mode = self.mode
            self.mode = new_mode
            self.mode_switch_wait_required = (
                old_mode is not SkillMode.NONE
                and new_mode is not SkillMode.NONE
                and old_mode is not new_mode
            )
        self.release_all_held_keys(keep_manual_space=self.manual_space_held)
        self.change_event.set()

        if old_mode is new_mode:
            print(f"技能模式已重新启动：{new_mode.name}")
        else:
            print(f"技能模式：{old_mode.name} -> {new_mode.name}")

    def toggle_total_switch(self) -> None:
        with self.state_lock:
            self.enabled = not self.enabled
            enabled = self.enabled
            if not enabled:
                self.mode = SkillMode.NONE
                self.manual_space_held = False
        if not enabled:
            self.release_all_held_keys()
            self.change_event.set()
            print("总开关已关闭，所有技能已停止")
        else:
            print("总开关已开启，请按 D/F/S 选择技能")

    def toggle_skill(self, mode: SkillMode) -> None:
        if not self.is_enabled():
            print("总开关未开启，当前按键不执行；请先按 F2")
            return
        if self.get_mode() is mode:
            self.set_mode(SkillMode.NONE)
        else:
            self.set_mode(mode)

    def handle_d_key(self) -> None:
        """D 作为 D/S 循环的统一停止键；空闲时才启动 D。"""
        if not self.is_enabled():
            print("\a总开关已关闭，D 不启动技能；D 仍可正常输入", end="", flush=True)
            return

        current_mode = self.get_mode()
        if current_mode in {SkillMode.D, SkillMode.S}:
            self.set_mode(SkillMode.NONE)
            print("D/S 技能循环已停止")
        elif current_mode is SkillMode.NONE:
            self.set_mode(SkillMode.D)
        else:
            # F 是一次性动作，不由 D 打断；等待 F 自己完成。
            print("F 技能动作正在执行，D 不打断 F")

    def toggle_manual_space(self) -> None:
        if not self.is_enabled():
            print("\a总开关已关闭，左 Ctrl 不执行空格操作", end="", flush=True)
            return
        if self.manual_space_held:
            self.release_key(" ")
            self.manual_space_held = False
            print("左 Ctrl：已松开空格")
        else:
            self.press_and_hold(" ")
            self.manual_space_held = True
            print("左 Ctrl：已按住空格")

    def consume_mode_switch_wait(self) -> bool:
        with self.state_lock:
            wait_required = self.mode_switch_wait_required
            self.mode_switch_wait_required = False
        if not wait_required:
            return True
        return self.wait_for_current_mode(
            self.MODE_SWITCH_WAIT_SECONDS,
            self.get_mode(),
        )

    def mouse_loop(self) -> None:
        next_click = time.monotonic()
        while not self.stop_event.is_set():
            mode = self.get_mode()
            should_click = self.is_enabled() and mode is SkillMode.F
            if should_click:
                now = time.monotonic()
                if now >= next_click:
                    with self.send_lock:
                        self.mouse_controller.click(mouse.Button.left)
                    next_click = now + self.MOUSE_CLICK_INTERVAL_SECONDS
            else:
                next_click = time.monotonic()
            self.stop_event.wait(self.POLL_INTERVAL_SECONDS)

    def mode_key_loop(
        self,
        key: str,
        interval: float,
        modes: set[SkillMode],
        start_immediately: bool = False,
    ) -> None:
        """仅在指定模式期间按键，离开后重新计时。"""
        next_press = time.monotonic() + interval
        was_mode_active = False
        while not self.stop_event.is_set():
            with self.state_lock:
                active = self.enabled and self.mode in modes
            now = time.monotonic()
            if active:
                if not was_mode_active:
                    if start_immediately:
                        self.tap_key(key)
                        next_press = now + interval
                    else:
                        next_press = now + interval
                    was_mode_active = True
                elif now >= next_press:
                    self.tap_key(key)
                    next_press = now + interval
            else:
                was_mode_active = False
            self.stop_event.wait(self.POLL_INTERVAL_SECONDS)

    def run_d_mode(self) -> None:
        if not self.is_mode_active(SkillMode.D):
            return
        while self.is_mode_active(SkillMode.D) and not self.stop_event.is_set():
            self.change_event.wait(self.POLL_INTERVAL_SECONDS)
            self.change_event.clear()

    def run_f_mode(self) -> None:
        mode = SkillMode.F
        if not self.is_mode_active(mode):
            return
        self.tap_key("t")
        if not self.wait_for_current_mode(self.F_T_TO_Q_WAIT_SECONDS, mode):
            return
        self.press_and_hold("q")
        if not self.wait_for_current_mode(self.F_Q_HOLD_SECONDS, mode):
            self.release_key("q")
            return
        self.release_key("q")
        if not self.is_mode_active(mode):
            return
        self.tap_key("r")
        # F 是一次性动作，完成后回到无技能状态。
        with self.state_lock:
            if self.enabled and self.mode is mode:
                self.mode = SkillMode.NONE
        self.change_event.set()
        print("F 技能动作完成")

    def run_s_mode(self) -> None:
        mode = SkillMode.S
        while self.is_mode_active(mode) and not self.stop_event.is_set():
            self.tap_key(" ")
            if not self.wait_for_current_mode(self.S_SPACE_TO_T_WAIT_SECONDS, mode):
                return
            self.tap_key("t")
            if not self.wait_for_current_mode(self.S_AFTER_T_WAIT_SECONDS, mode):
                return

    def skill_loop(self) -> None:
        handled_mode = SkillMode.NONE
        while not self.stop_event.is_set():
            mode = self.get_mode()
            if mode is not handled_mode:
                handled_mode = mode
                if mode is not SkillMode.NONE and not self.consume_mode_switch_wait():
                    handled_mode = SkillMode.NONE
                elif mode is SkillMode.D:
                    self.run_d_mode()
                elif mode is SkillMode.F:
                    self.run_f_mode()
                elif mode is SkillMode.S:
                    self.run_s_mode()
                handled_mode = SkillMode.NONE
            self.change_event.wait(self.POLL_INTERVAL_SECONDS)
            self.change_event.clear()

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == self.TOTAL_SWITCH_KEY:
            if not self.key_down_state.get("f2", False):
                self.key_down_state["f2"] = True
                self.toggle_total_switch()
            return

        if key == self.LEFT_CTRL_KEY:
            if not self.key_down_state.get("left_ctrl", False):
                self.key_down_state["left_ctrl"] = True
                self.toggle_manual_space()
            return

        if key == keyboard.KeyCode.from_char(self.D_KEY):
            if not self.key_down_state.get("d", False):
                self.key_down_state["d"] = True
                self.handle_d_key()
            return
        if key == keyboard.KeyCode.from_char(self.F_KEY):
            action = SkillMode.F
        elif key == keyboard.KeyCode.from_char(self.S_KEY):
            action = SkillMode.S
        else:
            return

        state_key = action.name.lower()
        if not self.key_down_state.get(state_key, False):
            self.key_down_state[state_key] = True
            self.toggle_skill(action)

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == self.TOTAL_SWITCH_KEY:
            self.key_down_state["f2"] = False
            return
        if key == self.LEFT_CTRL_KEY:
            self.key_down_state["left_ctrl"] = False
            return
        for mode in (SkillMode.D, SkillMode.F, SkillMode.S):
            if key == keyboard.KeyCode.from_char(mode.name.lower()):
                self.key_down_state[mode.name.lower()] = False
                return

    def run(self) -> None:
        print(
            "脚本已启动：F2=总开关（默认开启），"
            "D=启动D/停止D（T/W/1/2），F=鼠标+T/Q/R一次性动作，"
            "S=空格/T，左Ctrl=按住/松开空格，Ctrl+C=退出"
        )
        workers = [
            threading.Thread(target=self.mouse_loop, daemon=True),
            threading.Thread(target=self.skill_loop, daemon=True),
            threading.Thread(
                target=self.mode_key_loop,
                args=("t", self.D_T_INTERVAL_SECONDS, {SkillMode.D}, True),
                daemon=True,
            ),
            threading.Thread(
                target=self.mode_key_loop,
                args=("w", self.D_W_INTERVAL_SECONDS, {SkillMode.D}),
                daemon=True,
            ),
            threading.Thread(
                target=self.mode_key_loop,
                args=("1", self.D_ONE_INTERVAL_SECONDS, {SkillMode.D}),
                daemon=True,
            ),
            threading.Thread(
                target=self.mode_key_loop,
                args=("2", self.D_TWO_INTERVAL_SECONDS, {SkillMode.D}),
                daemon=True,
            ),
            threading.Thread(
                target=self.mode_key_loop,
                args=("1", self.ONE_INTERVAL_SECONDS, {SkillMode.S}),
                daemon=True,
            ),
            threading.Thread(
                target=self.mode_key_loop,
                args=("2", self.TWO_INTERVAL_SECONDS, {SkillMode.S}),
                daemon=True,
            ),
        ]
        for worker in workers:
            worker.start()

        listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
        )
        listener.start()
        try:
            listener.join()
        except KeyboardInterrupt:
            print("正在退出")
        finally:
            self.stop_event.set()
            self.release_all_held_keys()
            self.change_event.set()
            for worker in workers:
                worker.join(timeout=1.0)


if __name__ == "__main__":
    F2SkillSwitchController().run()
