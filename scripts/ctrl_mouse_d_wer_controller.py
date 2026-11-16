#!/usr/bin/env python3
"""左 Ctrl 鼠标点击 + D 键 W/E/R 循环控制器。

快捷键：
    左 Ctrl   开始/暂停鼠标左键点击
    D         开始/暂停 W、E、R 循环
    Ctrl+C    退出脚本

启动 D 循环时，会先按一次 W、E、R；相邻按键之间间隔 0.1 秒。
完成首次按键后，再按各自的周期执行：W 每 8 秒，E/R 每 5 秒。
"""

from __future__ import annotations

import threading
import time

from pynput import keyboard, mouse


class CtrlMouseDWerController:
    # 可直接修改下面的变量，单位为秒。
    MOUSE_CLICK_INTERVAL_SECONDS = 0.2
    W_INTERVAL_SECONDS = 8.0
    E_INTERVAL_SECONDS = 5.0
    R_INTERVAL_SECONDS = 5.0
    START_KEY_INTERVAL_SECONDS = 0.1
    POLL_INTERVAL_SECONDS = 0.005

    def __init__(self) -> None:
        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()
        self.state_lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.stop_event = threading.Event()

        self.mouse_clicking = False
        self.wer_running = False
        self.ctrl_down = False
        self.d_down = False

    def toggle_mouse_clicking(self) -> None:
        with self.state_lock:
            self.mouse_clicking = not self.mouse_clicking
            state = "开始" if self.mouse_clicking else "暂停"
        print(f"鼠标左键点击已{state}")

    def press_key(self, key: str) -> None:
        with self.send_lock:
            self.keyboard_controller.press(key)
            self.keyboard_controller.release(key)

    def click_left(self) -> None:
        with self.send_lock:
            self.mouse_controller.click(mouse.Button.left)

    def is_mouse_clicking(self) -> bool:
        with self.state_lock:
            return self.mouse_clicking

    def is_wer_running(self) -> bool:
        with self.state_lock:
            return self.wer_running

    def toggle_wer(self) -> None:
        with self.state_lock:
            self.wer_running = not self.wer_running
            running = self.wer_running

        if running:
            print("D 循环已开始：先按 W、E、R，再按周期循环")
            self.press_key("w")
            if self.stop_event.wait(self.START_KEY_INTERVAL_SECONDS):
                return
            self.press_key("e")
            if self.stop_event.wait(self.START_KEY_INTERVAL_SECONDS):
                return
            self.press_key("r")
        else:
            print("D 循环已暂停")

    def mouse_loop(self) -> None:
        next_click = time.monotonic()
        while not self.stop_event.is_set():
            if self.is_mouse_clicking():
                now = time.monotonic()
                if now >= next_click:
                    self.click_left()
                    next_click = now + self.MOUSE_CLICK_INTERVAL_SECONDS
            else:
                next_click = time.monotonic()

            self.stop_event.wait(self.POLL_INTERVAL_SECONDS)

    def key_loop(self, key: str, interval: float) -> None:
        next_press = time.monotonic() + interval
        was_running = False

        while not self.stop_event.is_set():
            running = self.is_wer_running()
            now = time.monotonic()

            if running:
                if not was_running:
                    # 启动时的 W/E/R 已经在 toggle_wer 中完成，周期从这里开始计时。
                    next_press = now + interval
                    was_running = True
                elif now >= next_press:
                    self.press_key(key)
                    next_press = now + interval
            else:
                was_running = False

            self.stop_event.wait(self.POLL_INTERVAL_SECONDS)

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == keyboard.Key.ctrl_l:
            if not self.ctrl_down:
                self.ctrl_down = True
                self.toggle_mouse_clicking()
        elif key == keyboard.KeyCode.from_char("d"):
            if not self.d_down:
                self.d_down = True
                self.toggle_wer()

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == keyboard.Key.ctrl_l:
            self.ctrl_down = False
        elif key == keyboard.KeyCode.from_char("d"):
            self.d_down = False

    def run(self) -> None:
        print(
            "脚本已启动：左 Ctrl=鼠标左键每0.2秒点击，"
            "D=W每8秒/E每5秒/R每5秒，Ctrl+C=退出"
        )

        workers: list[threading.Thread] = [
            threading.Thread(target=self.mouse_loop, daemon=True),
            threading.Thread(
                target=self.key_loop,
                args=("w", self.W_INTERVAL_SECONDS),
                daemon=True,
            ),
            threading.Thread(
                target=self.key_loop,
                args=("e", self.E_INTERVAL_SECONDS),
                daemon=True,
            ),
            threading.Thread(
                target=self.key_loop,
                args=("r", self.R_INTERVAL_SECONDS),
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
            for worker in workers:
                worker.join(timeout=1.0)


if __name__ == "__main__":
    CtrlMouseDWerController().run()
