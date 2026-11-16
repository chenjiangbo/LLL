"""D 键技能循环控制器。

快捷键：
    D       开始/停止鼠标和 Q 循环
    Ctrl/F  按住时每 0.3 秒点按一次 E
    F2      总开关；关闭时停止所有自动操作
    F3      退出程序

技能循环：
    鼠标左键：每 0.3 秒点击一次
    Q 键：每 2 秒点按一次

依赖：
    python3 -m pip install pynput
"""

from __future__ import annotations

import threading
import time
import sys

from pynput import keyboard, mouse


class DCycleController:
    # Windows 下功能键回调偶尔会是 KeyCode，需要用 Windows VK 码识别：
    # F2=0x71 (113)，F3=0x72 (114)。同时保留 pynput 的 Key.f2/Key.f3。
    FUNCTION_KEY_VK = {"f2": 113, "f3": 114}
    MOUSE_INTERVAL_SECONDS = 0.3
    E_INTERVAL_SECONDS = 0.3
    Q_INTERVAL_SECONDS = 2.0

    def __init__(self) -> None:
        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.master_enabled = True
        self.cycle_running = False
        self.d_down = False
        self.f2_down = False
        self.e_trigger_keys: set[str] = set()

    @classmethod
    def is_function_key(cls, key: keyboard.Key | keyboard.KeyCode, name: str) -> bool:
        named_key = getattr(keyboard.Key, name)
        virtual_key = getattr(key, "vk", None)
        if sys.platform.startswith("win"):
            return key == named_key or virtual_key == cls.FUNCTION_KEY_VK[name]
        return key == named_key

    @staticmethod
    def e_trigger_token(key: keyboard.Key | keyboard.KeyCode) -> str | None:
        if key in (keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
            return "ctrl"
        if getattr(key, "char", "").lower() == "f":
            return "f"
        return None

    def toggle_master(self) -> None:
        with self.lock:
            self.master_enabled = not self.master_enabled
            if not self.master_enabled:
                self.cycle_running = False
                self.e_trigger_keys.clear()
            state = "开启" if self.master_enabled else "关闭"
            print(f"总开关已{state}")

    def toggle_cycle(self) -> None:
        with self.lock:
            if not self.master_enabled:
                print("总开关已关闭，D 键暂不执行")
                return
            self.cycle_running = not self.cycle_running
            state = "开始" if self.cycle_running else "停止"
            print(f"技能循环已{state}")

    def cycle_loop(self) -> None:
        now = time.monotonic()
        next_mouse_click = now
        next_e_press = now
        next_q_press = now

        while not self.stop_event.is_set():
            with self.lock:
                active = self.master_enabled and self.cycle_running
                e_active = self.master_enabled and bool(self.e_trigger_keys)

            now = time.monotonic()
            if active:
                if now >= next_mouse_click:
                    self.mouse_controller.click(mouse.Button.left)
                    next_mouse_click = now + self.MOUSE_INTERVAL_SECONDS

                if now >= next_q_press:
                    self.keyboard_controller.press("q")
                    self.keyboard_controller.release("q")
                    next_q_press = now + self.Q_INTERVAL_SECONDS
            else:
                # 下次启动时立即执行一次鼠标和 Q。
                next_mouse_click = now
                next_q_press = now

            if e_active:
                if now >= next_e_press:
                    self.keyboard_controller.press("e")
                    self.keyboard_controller.release("e")
                    next_e_press = now + self.E_INTERVAL_SECONDS
            else:
                # 按住 Ctrl/F 后立即开始 E 循环。
                next_e_press = now

            self.stop_event.wait(0.005)

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if self.is_function_key(key, "f3"):
            self.stop_event.set()
            print("正在退出")
            return False

        if self.is_function_key(key, "f2"):
            if not self.f2_down:
                self.f2_down = True
                self.toggle_master()
        elif key == keyboard.KeyCode.from_char("d"):
            if not self.d_down:
                self.d_down = True
                self.toggle_cycle()
        else:
            token = self.e_trigger_token(key)
            if token is not None:
                with self.lock:
                    if self.master_enabled:
                        self.e_trigger_keys.add(token)

        return None

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if self.is_function_key(key, "f2"):
            self.f2_down = False
        elif key == keyboard.KeyCode.from_char("d"):
            self.d_down = False
        else:
            token = self.e_trigger_token(key)
            if token is not None:
                with self.lock:
                    self.e_trigger_keys.discard(token)

    def run(self) -> None:
        print("脚本已启动：D=鼠标/Q循环，按住Ctrl或F=按E，F2=总开关，F3=退出")
        worker = threading.Thread(target=self.cycle_loop, daemon=True)
        worker.start()
        listener = keyboard.Listener(
            on_press=self.on_press,
            on_release=self.on_release,
        )
        listener.start()
        try:
            listener.join()
        finally:
            self.stop_event.set()
            worker.join(timeout=1.0)


if __name__ == "__main__":
    DCycleController().run()
