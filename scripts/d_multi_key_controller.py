"""D 键多按键循环控制器。

快捷键：
    D    开始/停止全部按键循环
    F2   总开关
    F4   切换 Q 循环
    空格 按住时暂停全部自动按键

循环内容：
    W    每 0.3 秒点按一次
    2    每 2 秒点按一次
    Q    每 0.5 秒点按一次
    1    每 5 秒点按一次

依赖：
    python3 -m pip install pynput
"""

from __future__ import annotations

import threading
import sys
import time

from pynput import keyboard

try:
    import winsound
except ImportError:
    winsound = None


class DMultiKeyController:
    # 可直接修改下面四个变量，单位为秒。
    W_INTERVAL_SECONDS = 0.3
    TWO_INTERVAL_SECONDS = 2.0
    Q_INTERVAL_SECONDS = 0.5
    ONE_INTERVAL_SECONDS = 5.0
    Q_ENABLED_BY_DEFAULT = True
    ENABLE_BEEP = True
    Q_ENABLED_BEEP = (880, 120)
    Q_DISABLED_BEEP = (440, 180)
    MASTER_ENABLED_BEEP = (1046, 120)
    MASTER_DISABLED_BEEP = (330, 180)

    INTERVALS = {
        "w": W_INTERVAL_SECONDS,
        "2": TWO_INTERVAL_SECONDS,
        "q": Q_INTERVAL_SECONDS,
        "1": ONE_INTERVAL_SECONDS,
    }

    def __init__(self) -> None:
        self.keyboard_controller = keyboard.Controller()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.master_enabled = True
        self.running = False
        self.q_enabled = self.Q_ENABLED_BY_DEFAULT
        self.d_down = False
        self.f2_down = False
        self.f4_down = False
        self.space_down = False

    @staticmethod
    def is_function_key(key: keyboard.Key | keyboard.KeyCode, name: str) -> bool:
        named_key = getattr(keyboard.Key, name)
        virtual_key_codes = {"f2": 113, "f4": 115}
        virtual_key = getattr(key, "vk", None)
        if sys.platform.startswith("win"):
            return key == named_key or virtual_key == virtual_key_codes[name]
        return key == named_key

    def beep(self, frequency: int, duration_ms: int) -> None:
        if self.ENABLE_BEEP and winsound is not None:
            winsound.Beep(frequency, duration_ms)

    def toggle_cycle(self) -> None:
        with self.lock:
            if not self.master_enabled:
                print("总开关已关闭，D 键暂不执行")
                return
            self.running = not self.running
            state = "开始" if self.running else "停止"
            print(f"按键循环已{state}")

    def toggle_master(self) -> None:
        with self.lock:
            self.master_enabled = not self.master_enabled
            if not self.master_enabled:
                self.running = False
            state = "开启" if self.master_enabled else "关闭"
            print(f"总开关已{state}")
        self.beep(*(self.MASTER_ENABLED_BEEP if self.master_enabled else self.MASTER_DISABLED_BEEP))

    def toggle_q(self) -> None:
        with self.lock:
            if not self.master_enabled:
                print("总开关已关闭，F4 暂不切换 Q")
                return
            self.q_enabled = not self.q_enabled
            state = "开启" if self.q_enabled else "关闭"
            print(f"Q 循环已{state}")
        self.beep(*(self.Q_ENABLED_BEEP if self.q_enabled else self.Q_DISABLED_BEEP))

    def press_key(self, key: str) -> None:
        self.keyboard_controller.press(key)
        self.keyboard_controller.release(key)

    def cycle_loop(self) -> None:
        next_press = {key: time.monotonic() for key in self.INTERVALS}

        while not self.stop_event.is_set():
            with self.lock:
                active = self.master_enabled and self.running and not self.space_down
                q_active = active and self.q_enabled

            now = time.monotonic()
            if active:
                for key, interval in self.INTERVALS.items():
                    if key == "q" and not q_active:
                        next_press[key] = now
                        continue
                    if now >= next_press[key]:
                        self.press_key(key)
                        next_press[key] = now + interval
            else:
                # 再次按 D 启动时，四个按键都会立即执行一次。
                next_press = {key: now for key in self.INTERVALS}

            self.stop_event.wait(0.005)

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if key == keyboard.Key.space:
            self.space_down = True
        elif self.is_function_key(key, "f2"):
            if not self.f2_down:
                self.f2_down = True
                self.toggle_master()
        elif self.is_function_key(key, "f4"):
            if not self.f4_down:
                self.f4_down = True
                self.toggle_q()
        elif key == keyboard.KeyCode.from_char("d"):
            if not self.d_down:
                self.d_down = True
                self.toggle_cycle()
        return None

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == keyboard.Key.space:
            self.space_down = False
        elif self.is_function_key(key, "f2"):
            self.f2_down = False
        elif self.is_function_key(key, "f4"):
            self.f4_down = False
        elif key == keyboard.KeyCode.from_char("d"):
            self.d_down = False

    def run(self) -> None:
        print("脚本已启动：D=开始/停止，F2=总开关，F4=Q开关，空格=暂停，W=0.3秒，2=2秒，Q=0.5秒，1=5秒")
        worker = threading.Thread(target=self.cycle_loop, daemon=True)
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
            worker.join(timeout=1.0)


if __name__ == "__main__":
    DMultiKeyController().run()
