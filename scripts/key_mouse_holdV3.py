"""用快捷键控制 Q 键和鼠标左键的点按。

快捷键：
    D    开始/停止 Q 键、鼠标左键和数字 1 的点按
    F    暂停 Q/鼠标点按，依次执行 T、E、W，然后恢复原来的运行状态
    F1   退出程序

依赖：
    python3 -m pip install pynput
"""

from __future__ import annotations

import threading
import time

from pynput import keyboard, mouse


class KeyMouseController:
    Q_INTERVAL_SECONDS = 0.2
    MOUSE_INTERVAL_SECONDS = 0.5
    ONE_INTERVAL_SECONDS = 0.3

    def __init__(self) -> None:
        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()
        self.lock = threading.Lock()
        self.running = False
        self.d_cycle_active = False
        self.stop_event = threading.Event()
        self.d_hotkey_down = False
        self.f_hotkey_down = False

    def toggle_running(self) -> None:
        with self.lock:
            self.d_cycle_active = not self.d_cycle_active
            self.running = self.d_cycle_active
            state = "开始" if self.d_cycle_active else "停止"
            print(f"已{state} Q、鼠标左键和数字 1 的技能循环")

    def press_t_then_e_then_w(self) -> None:
        self.keyboard_controller.press("t")
        self.keyboard_controller.release("t")
        time.sleep(0.1)
        self.keyboard_controller.press("e")
        self.keyboard_controller.release("e")
        time.sleep(0.2)
        self.keyboard_controller.press("w")
        self.keyboard_controller.release("w")
        print("已依次按下 T、E、W")

    def click_loop(self) -> None:
        next_mouse_click = time.monotonic()
        next_q_press = time.monotonic()
        next_one_press = time.monotonic() + self.ONE_INTERVAL_SECONDS

        while not self.stop_event.is_set():
            with self.lock:
                running = self.running
                d_cycle_active = self.d_cycle_active

            now = time.monotonic()
            if running:
                if now >= next_q_press:
                    self.keyboard_controller.press("q")
                    self.keyboard_controller.release("q")
                    next_q_press = now + self.Q_INTERVAL_SECONDS

                if now >= next_mouse_click:
                    self.mouse_controller.click(mouse.Button.left)
                    next_mouse_click = now + self.MOUSE_INTERVAL_SECONDS

            else:
                # 暂停后重新开始时立即进行一次 Q 点按和鼠标点击。
                next_q_press = now
                next_mouse_click = now

            # 数字 1 只由 D 控制；F 暂停 Q/鼠标时不影响数字 1 定时器。
            # Q 和鼠标左键已经先处理，因此数字 1 不会抢占它们的执行时机。
            if d_cycle_active:
                if now >= next_one_press and (
                    not running
                    or (now < next_q_press and now < next_mouse_click)
                ):
                    self.keyboard_controller.press("1")
                    self.keyboard_controller.release("1")
                    next_one_press = now + self.ONE_INTERVAL_SECONDS
            else:
                next_one_press = now + self.ONE_INTERVAL_SECONDS

            self.stop_event.wait(0.005)

    def handle_f(self) -> None:
        with self.lock:
            was_running = self.running
            self.running = False

        print("已暂停，准备按 T、E、W")
        self.press_t_then_e_then_w()
        # 给 W 的游戏内动作留出处理时间，再恢复 Q 和鼠标点击。
        time.sleep(0.3)

        with self.lock:
            self.running = was_running

        if was_running:
            print("已恢复 Q 点按和鼠标左键点击")

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if key == keyboard.Key.f1:
            self.stop_event.set()
            print("正在退出")
            return False

        if key == keyboard.KeyCode.from_char("d"):
            if not self.d_hotkey_down:
                self.d_hotkey_down = True
                self.toggle_running()
        elif key == keyboard.KeyCode.from_char("f"):
            if not self.f_hotkey_down:
                self.f_hotkey_down = True
                self.handle_f()

        return None

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == keyboard.KeyCode.from_char("d"):
            self.d_hotkey_down = False
        elif key == keyboard.KeyCode.from_char("f"):
            self.f_hotkey_down = False

    def run(self) -> None:
        print("脚本已启动：D=开始/停止，F=执行 T、E、W 并恢复，F1=退出")
        worker = threading.Thread(target=self.click_loop, daemon=True)
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
    KeyMouseController().run()
