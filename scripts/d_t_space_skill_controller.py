"""D 键技能循环控制器。

快捷键：
    D       开始/暂停技能循环，再按一次恢复
    空格    按住时暂停所有自动操作，松开后继续

循环内容：
    T、空格  严格按 T → 空格 → T → 空格 交替执行，每步间隔 0.6 秒
    2、1    每 3 秒各点按一次
    R、E    启动后等待 5 秒，之后每 5 秒各点按一次
    鼠标左键 每 0.3 秒点击一次

依赖：
    python3 -m pip install pynput
"""

from __future__ import annotations

import threading
import time

from pynput import keyboard, mouse


class DTSpaceSkillController:
    # 可直接修改下面的变量，单位为秒。
    T_SPACE_INTERVAL_SECONDS = 0.6  # T 和空格两个动作之间的间隔
    TWO_INTERVAL_SECONDS = 3.0
    ONE_INTERVAL_SECONDS = 3.0
    R_INTERVAL_SECONDS = 5.0
    E_INTERVAL_SECONDS = 5.0
    MOUSE_INTERVAL_SECONDS = 0.3

    # 自动点按空格是瞬时完成的；持续超过此时间才认定为手动按住暂停。
    SPACE_PAUSE_HOLD_THRESHOLD_SECONDS = 0.15

    def __init__(self) -> None:
        self.keyboard_controller = keyboard.Controller()
        self.mouse_controller = mouse.Controller()
        self.lock = threading.Lock()
        self.send_lock = threading.Lock()
        self.stop_event = threading.Event()
        self.running = False
        self.d_down = False
        self.space_down_since: float | None = None

    def toggle_cycle(self) -> None:
        with self.lock:
            self.running = not self.running
            state = "开始" if self.running else "暂停"
            print(f"技能循环已{state}")

    def press_key(self, key: str) -> None:
        with self.send_lock:
            self.keyboard_controller.press(key)
            self.keyboard_controller.release(key)

    def click_left(self) -> None:
        with self.send_lock:
            self.mouse_controller.click(mouse.Button.left)

    def is_active(self) -> bool:
        now = time.monotonic()
        with self.lock:
            manually_paused = (
                self.space_down_since is not None
                and now - self.space_down_since
                >= self.SPACE_PAUSE_HOLD_THRESHOLD_SECONDS
            )
            return self.running and not manually_paused

    def t_space_loop(self) -> None:
        next_press = time.monotonic()
        next_key = "t"
        was_active = False

        while not self.stop_event.is_set():
            active = self.is_active()
            now = time.monotonic()
            if active:
                if not was_active:
                    next_press = now
                    next_key = "t"
                    was_active = True
                if now >= next_press:
                    self.press_key(" " if next_key == "space" else "t")
                    next_key = "space" if next_key == "t" else "t"
                    next_press = now + self.T_SPACE_INTERVAL_SECONDS
            else:
                was_active = False

            self.stop_event.wait(0.005)

    def background_loop(self, interval: float, action, initial_delay: float = 0.0) -> None:
        was_active = False
        next_action = time.monotonic()

        while not self.stop_event.is_set():
            active = self.is_active()
            now = time.monotonic()
            if active:
                if not was_active:
                    next_action = now + initial_delay
                    was_active = True
                if now >= next_action:
                    action()
                    next_action = now + interval
            else:
                was_active = False

            self.stop_event.wait(0.005)

    def on_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        if key == keyboard.Key.space:
            with self.lock:
                if self.space_down_since is None:
                    self.space_down_since = time.monotonic()
        elif key == keyboard.KeyCode.from_char("d"):
            if not self.d_down:
                self.d_down = True
                self.toggle_cycle()
        return None

    def on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        if key == keyboard.Key.space:
            with self.lock:
                self.space_down_since = None
        elif key == keyboard.KeyCode.from_char("d"):
            self.d_down = False

    def run(self) -> None:
        print("脚本已启动：D=开始/暂停，按住空格=暂停，T→空格交替=0.6秒，2/1=3秒，R/E=启动后5秒再按且每5秒一次，鼠标左键=0.3秒")
        workers = [
            threading.Thread(target=self.t_space_loop, daemon=True),
            threading.Thread(
                target=self.background_loop,
                args=(self.R_INTERVAL_SECONDS, lambda: self.press_key("r"), self.R_INTERVAL_SECONDS),
                daemon=True,
            ),
            threading.Thread(
                target=self.background_loop,
                args=(self.E_INTERVAL_SECONDS, lambda: self.press_key("e"), self.E_INTERVAL_SECONDS),
                daemon=True,
            ),
            threading.Thread(
                target=self.background_loop,
                args=(self.TWO_INTERVAL_SECONDS, lambda: self.press_key("2")),
                daemon=True,
            ),
            threading.Thread(
                target=self.background_loop,
                args=(self.ONE_INTERVAL_SECONDS, lambda: self.press_key("1")),
                daemon=True,
            ),
            threading.Thread(
                target=self.background_loop,
                args=(self.MOUSE_INTERVAL_SECONDS, self.click_left),
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
    DTSpaceSkillController().run()
