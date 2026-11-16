from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, time as dtime
from pathlib import Path
from zoneinfo import ZoneInfo
import psycopg

from backend.screening.storage import PostgresScreeningStore
from backend.screening.data_sync import ScreeningDataSync
from backend.screening.tushare_source import TushareScreeningSource
from backend.screening.config import TushareConfig

logger = logging.getLogger("auto_scheduler")
DAILY_RELEASE_TIME = dtime(17, 0)

class AutoDataScheduler:
    """自动数据调度服务：
    1. 按配置时间盘后同步官方标准日线及周线数据
    2. 股票当日 30 分钟数据由 K 线接口按需获取
    3. 启动时检查并补齐已发布的日线与周线数据
    """

    def __init__(self, db_url: str):
        self.db_url = db_url
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock_conn: psycopg.Connection | None = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        # uvicorn 被重复启动时，只允许一个进程运行自动同步，避免多个全量任务并发打 Tushare。
        try:
            lock_conn = psycopg.connect(self.db_url, autocommit=True)
            acquired = lock_conn.execute(
                "SELECT pg_try_advisory_lock(hashtext('lll.market_review.auto_scheduler'))"
            ).fetchone()[0]
            if not acquired:
                lock_conn.close()
                logger.warning("[AutoDataScheduler] 检测到已有调度器实例，当前进程不启动自动同步线程。")
                return
            self._lock_conn = lock_conn
        except Exception as exc:
            logger.error(f"[AutoDataScheduler] 获取跨进程调度锁失败，拒绝启动自动同步: {exc}")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="AutoDataSchedulerThread")
        self._thread.start()
        logger.info("[AutoDataScheduler] 自动化数据同步调度线程已成功启动。")

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._lock_conn:
            try:
                self._lock_conn.execute("SELECT pg_advisory_unlock(hashtext('lll.market_review.auto_scheduler'))")
                self._lock_conn.close()
            except Exception:
                pass
            finally:
                self._lock_conn = None

    def _run_loop(self):
        # 启动时首先执行一次静默自检
        try:
            self._run_startup_check()
        except Exception as e:
            logger.error(f"[AutoDataScheduler] 启动自检异常: {e}")

        last_daily_sync_slot = ""

        while not self._stop_event.is_set():
            try:
                store = PostgresScreeningStore(self.db_url)
                config = store.get_data_management_config()["config"]
                now = datetime.now(ZoneInfo(str(config.get("timezone", "Asia/Shanghai"))))
                if not config.get("enabled", True):
                    self._stop_event.wait(30)
                    continue
                # 仅在工作日执行 (0=Monday, 4=Friday)
                if (not config.get("trading_days_only", True)) or now.weekday() < 5:
                    today_str = now.strftime("%Y%m%d")

                    # 盘中分钟线只在打开单只股票 K 线时按需获取，不做全市场扫描。
                    # 盘后日线自动同步，执行时间由数据管理配置决定。
                    # 数据源通常在收盘后约两小时才提供正式日线；过滤配置中的过早时刻。
                    run_times = {
                        str(value)[:5]
                        for value in config.get("daily_run_times", ["18:00"])
                        if str(value)[:5] >= DAILY_RELEASE_TIME.strftime("%H:%M")
                    }
                    daily_slot = f"{today_str}{now.strftime('%H:%M')}"
                    if now.strftime("%H:%M") in run_times and daily_slot != last_daily_sync_slot:
                        last_daily_sync_slot = daily_slot
                        if config.get("daily_enabled", True):
                            logger.info(f"[AutoDataScheduler] 触发盘后官方权威日线自动同步 ({now.strftime('%Y-%m-%d %H:%M')})...")
                            self._sync_daily_bars(today_str)
                        if config.get("weekly_enabled", True):
                            logger.info(f"[AutoDataScheduler] 触发周线行情自动同步 ({today_str})...")
                            self._sync_weekly_bars(today_str)

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
        config = store.get_data_management_config()["config"]
        if not config.get("enabled", True):
            logger.info("[AutoDataScheduler] 自动更新已在数据管理中关闭，跳过启动自检。")
            return
        freshness = store.get_data_freshness_info()
        latest_db_date = freshness.get("daily_market_date")
        
        now = datetime.now(ZoneInfo(str(config.get("timezone", "Asia/Shanghai"))))
        today_str = now.strftime("%Y%m%d")
        logger.info(f"[AutoDataScheduler] 自检数据库行情日期: {latest_db_date}, 系统今日: {today_str}")

        if now.weekday() < 5:
            now_time = now.time()
            if now_time >= DAILY_RELEASE_TIME:
                if config.get("daily_enabled", True) and (latest_db_date and latest_db_date < today_str):
                    self._sync_daily_bars(today_str)
                if config.get("weekly_enabled", True):
                    self._sync_weekly_bars(today_str)

    def _sync_daily_bars(self, target_date: str) -> bool:
        store, sync = self._get_store_and_sync()
        task_id = str(uuid.uuid4())
        store.create_data_task(task_id, "scheduled_daily", target_date)
        store.update_data_task(task_id, status="RUNNING", progress=0, stage_message=f"自动更新 {target_date} 日线数据", started_at=datetime.now(ZoneInfo("Asia/Shanghai")))
        daily_ok = store.has_daily_data(target_date)
        try:
            if not daily_ok:
                sync.sync_trade_date(target_date)
                daily_ok = True
                logger.info(f"[AutoDataScheduler] 盘后权威日线 {target_date} 成功同步。")
        except Exception as e:
            # 当天尚未发布日线时记录待发布，后续调度周期再检查。
            logger.info(f"[AutoDataScheduler] 日线 {target_date} 暂不可用，稍后再检查: {e}")

        store.update_data_task(
            task_id,
            status="SUCCESS" if daily_ok else "PARTIAL",
            progress=100,
            stage_message=f"{target_date} 日线同步完成" if daily_ok else f"{target_date} 日线仍待数据源发布",
            completed_at=datetime.now(ZoneInfo("Asia/Shanghai")),
        )
        return daily_ok

    def _sync_weekly_bars(self, target_date: str) -> bool:
        store, sync = self._get_store_and_sync()
        task_id = str(uuid.uuid4())
        store.create_data_task(task_id, "scheduled_weekly", target_date)
        store.update_data_task(task_id, status="RUNNING", progress=0, stage_message=f"自动更新 {target_date} 周线数据", started_at=datetime.now(ZoneInfo("Asia/Shanghai")))
        try:
            result = sync.sync_stock_weekly_history(target_date, target_date)
            store.update_data_task(task_id, status="SUCCESS", progress=100, stage_message=f"{target_date} 周线同步完成", summary_json=result, completed_at=datetime.now(ZoneInfo("Asia/Shanghai")))
            logger.info(f"[AutoDataScheduler] 周线 {target_date} 同步完成: {result}")
            return True
        except Exception as exc:
            store.update_data_task(task_id, status="FAILED", progress=100, stage_message=f"{target_date} 周线同步失败", error_message=str(exc), completed_at=datetime.now(ZoneInfo("Asia/Shanghai")))
            logger.error(f"[AutoDataScheduler] 周线 {target_date} 同步失败: {exc}")
            return False
