from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, date, time as dtime
from pathlib import Path

from backend.screening.storage import PostgresScreeningStore
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.tushare_source import TushareScreeningSource
from backend.screening.config import TushareConfig

logger = logging.getLogger("auto_scheduler")

class AutoDataScheduler:
    """自动数据调度服务：
    1. 盘中自动轮询 30m K线数据 (工作日 9:30-15:30 每 30 分钟)
    2. 盘后自动同步官方标准日线数据 (工作日 15:30 & 18:00)
    3. 启动自检与离线自动补齐 (Auto-recovery)
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AutoDataSchedulerThread")
        self._thread.start()
        logger.info("[AutoDataScheduler] 自动化数据同步调度线程已成功启动。")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def _run_loop(self):
        # 启动时首先执行一次静默自检
        try:
            self._run_startup_check()
        except Exception as e:
            logger.error(f"[AutoDataScheduler] 启动自检异常: {e}")

        last_30m_check_min = -1
        last_daily_sync_date = ""

        while not self._stop_event.is_set():
            try:
                now = datetime.now()
                # 仅在工作日执行 (0=Monday, 4=Friday)
                if now.weekday() < 5:
                    current_time = now.time()
                    today_str = now.strftime("%Y%m%d")

                    # 1. 盘中 30m 自动更新 (9:30 ~ 15:30，每 30 分钟触发一次)
                    if dtime(9, 30) <= current_time <= dtime(15, 35):
                        if now.minute in (0, 30) and now.minute != last_30m_check_min:
                            last_30m_check_min = now.minute
                            logger.info(f"[AutoDataScheduler] 触发盘中 30m K 线自动同步 ({now.strftime('%H:%M')})...")
                            self._sync_30m_bars()

                    # 2. 盘后权威日线自动同步 (15:35 及 18:00 各执行一次)
                    if (dtime(15, 35) <= current_time <= dtime(15, 45) or dtime(18, 0) <= current_time <= dtime(18, 10)) and last_daily_sync_date != today_str:
                        logger.info(f"[AutoDataScheduler] 触发盘后官方权威日线自动同步 ({now.strftime('%Y-%m-%d %H:%M')})...")
                        if self._sync_daily_bars(today_str):
                            last_daily_sync_date = today_str

            except Exception as exc:
                logger.error(f"[AutoDataScheduler] 调度循环异常: {exc}")

            # 30 秒轮询一次时间标度
            self._stop_event.wait(30)

    def _get_store_and_sync(self) -> tuple[PostgresScreeningStore, ScreeningDataSync]:
        store = PostgresScreeningStore(self.db_url)
        project_root = Path(__file__).resolve().parents[2]
        config = TushareConfig.from_project_env(project_root)
        source = TushareScreeningSource(config.token)
        sync = ScreeningDataSync(source, store)
        return store, sync

    def _run_startup_check(self):
        store, sync = self._get_store_and_sync()
        freshness = store.get_data_freshness_info()
        latest_db_date = freshness.get("daily_market_date")
        
        today_str = date.today().strftime("%Y%m%d")
        logger.info(f"[AutoDataScheduler] 自检数据库行情日期: {latest_db_date}, 系统今日: {today_str}")

        if latest_db_date and latest_db_date < today_str:
            now_time = datetime.now().time()
            if now_time >= dtime(15, 30):
                self._sync_daily_bars(today_str)

    def _sync_30m_bars(self):
        try:
            store, sync = self._get_store_and_sync()
            today_str = date.today().strftime("%Y%m%d")
            sync.sync_30m_bars_all(start_date=today_str, end_date=today_str)
            logger.info("[AutoDataScheduler] 盘中 30m K 线自动同步完成。")
        except Exception as e:
            logger.warning(f"[AutoDataScheduler] 30m K 线增量同步提示: {e}")

    def _sync_daily_bars(self, target_date: str) -> bool:
        try:
            store, sync = self._get_store_and_sync()
            if store.has_daily_data(target_date):
                return True
            sync.sync_trade_date(target_date)
            logger.info(f"[AutoDataScheduler] 盘后权威日线 {target_date} 成功同步。")
            return True
        except Exception as e:
            logger.warning(f"[AutoDataScheduler] 盘后日线同步提示: {e}")
            return False
