"""
MinerU Tianshu - Task Scheduler (Optional)
天枢任务调度器（可选）

在 Worker 自动循环模式下，调度器主要用于：
1. 监控队列状态（默认5分钟一次）
2. 健康检查（默认15分钟一次）
3. 统计信息收集
4. 故障恢复（重置超时任务）

注意：
- 如果 workers 启用了自动循环模式（默认），则不需要调度器来触发任务处理
- Worker 已经主动工作，调度器只是偶尔检查系统状态
- 较长的间隔可以最小化系统开销，同时保持必要的监控能力
- 5分钟监控、15分钟健康检查对于自动运行的系统来说已经足够及时
"""
import asyncio
import aiohttp
from loguru import logger
from task_db import TaskDB
import signal


class TaskScheduler:
    """
    任务调度器（可选）
    
    职责（在 Worker 自动循环模式下）：
    1. 监控 SQLite 任务队列状态
    2. 健康检查 Workers
    3. 故障恢复（重置超时任务）
    4. 收集和展示统计信息
    
    职责（在传统模式下）：
    1. 触发 Workers 拉取任务
    """
    
    def __init__(
        self, 
        litserve_url='http://localhost:39021/predict', 
        monitor_interval=300,
        health_check_interval=900,
        stale_task_timeout=60,
        cleanup_old_files_days=7,
        cleanup_old_records_days=0,
        worker_auto_mode=True
    ):
        """
        初始化调度器
        
        Args:
            litserve_url: LitServe Worker 的 URL
            monitor_interval: 监控间隔（秒，默认300秒=5分钟）
            health_check_interval: 健康检查间隔（秒，默认900秒=15分钟）
            stale_task_timeout: 超时任务重置时间（分钟）
            cleanup_old_files_days: 清理多少天前的结果文件（0=禁用，默认7天）
            cleanup_old_records_days: 清理多少天前的数据库记录（0=禁用，不推荐删除）
            worker_auto_mode: Worker 是否启用自动循环模式
        """
        self.litserve_url = litserve_url
        self.monitor_interval = monitor_interval
        self.health_check_interval = health_check_interval
        self.stale_task_timeout = stale_task_timeout
        self.cleanup_old_files_days = cleanup_old_files_days
        self.cleanup_old_records_days = cleanup_old_records_days
        self.worker_auto_mode = worker_auto_mode
        self.db = TaskDB()
        self.running = True
    
    async def check_worker_health(self, session: aiohttp.ClientSession):
        """
        检查 worker 健康状态
        """
        try:
            async with session.post(
                self.litserve_url,
                json={'action': 'health'},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return result
                else:
                    logger.error(f"健康检查返回异常状态码: {resp.status}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.warning("健康检查超时")
            return None
        except Exception as e:
            logger.error(f"健康检查出现异常: {e}")
            return None
    
    async def schedule_loop(self):
        """
        主监控循环
        """
        logger.info("🔄 任务调度器已启动")
        logger.info(f"   LitServe 地址: {self.litserve_url}")
        logger.info(f"   Worker 模式: {'自动循环' if self.worker_auto_mode else '调度驱动'}")
        logger.info(f"   监控间隔: {self.monitor_interval}s")
        logger.info(f"   健康检查间隔: {self.health_check_interval}s")
        logger.info(f"   超时任务阈值: {self.stale_task_timeout}m")
        if self.cleanup_old_files_days > 0:
            logger.info(f"   清理旧文件: {self.cleanup_old_files_days} 天")
        else:
            logger.info(f"   清理旧文件: 已禁用")
        if self.cleanup_old_records_days > 0:
            logger.info(f"   清理旧记录: {self.cleanup_old_records_days} 天（不推荐）")
        else:
            logger.info(f"   清理旧记录: 已禁用（永久保留）")
        
        health_check_counter = 0
        stale_task_counter = 0
        cleanup_counter = 0
        
        async with aiohttp.ClientSession() as session:
            while self.running:
                try:
                    # 1. 监控队列状态
                    stats = self.db.get_queue_stats()
                    pending_count = stats.get('pending', 0)
                    processing_count = stats.get('processing', 0)
                    completed_count = stats.get('completed', 0)
                    failed_count = stats.get('failed', 0)
                    
                    if pending_count > 0 or processing_count > 0:
                        logger.info(
                            f"📊 队列: {pending_count} 待处理, {processing_count} 处理中, "
                            f"{completed_count} 已完成, {failed_count} 失败"
                        )
                    
                    # 2. 定期健康检查
                    health_check_counter += 1
                    if health_check_counter * self.monitor_interval >= self.health_check_interval:
                        health_check_counter = 0
                        logger.info("🏥 正在执行健康检查...")
                        health_result = await self.check_worker_health(session)
                        if health_result:
                            logger.info(f"✅ Worker 健康: {health_result}")
                        else:
                            logger.warning("⚠️  Worker 健康检查失败")
                    
                    # 3. 定期重置超时任务
                    stale_task_counter += 1
                    if stale_task_counter * self.monitor_interval >= self.stale_task_timeout * 60:
                        stale_task_counter = 0
                        reset_count = self.db.reset_stale_tasks(self.stale_task_timeout)
                        if reset_count > 0:
                            logger.warning(f"⚠️  已重置 {reset_count} 个超时任务 (阈值: {self.stale_task_timeout} 分钟)")
                    
                    # 4. 定期清理旧任务文件和记录
                    cleanup_counter += 1
                    # 每24小时清理一次（基于当前监控间隔计算）
                    cleanup_interval_cycles = (24 * 3600) / self.monitor_interval
                    if cleanup_counter >= cleanup_interval_cycles:
                        cleanup_counter = 0
                        
                        # 清理旧结果文件（保留数据库记录）
                        if self.cleanup_old_files_days > 0:
                            logger.info(f"🧹 正在清理早于 {self.cleanup_old_files_days} 天的结果文件...")
                            file_count = self.db.cleanup_old_task_files(days=self.cleanup_old_files_days)
                            if file_count > 0:
                                logger.info(f"✅ 已清理 {file_count} 个结果目录（保留数据库记录）")
                        
                        # 清理极旧的数据库记录（可选，默认不启用）
                        if self.cleanup_old_records_days > 0:
                            logger.warning(
                                f"🗑️  正在清理早于 {self.cleanup_old_records_days} 天的数据库记录..."
                            )
                            record_count = self.db.cleanup_old_task_records(days=self.cleanup_old_records_days)
                            if record_count > 0:
                                logger.warning(f"⚠️  已永久删除 {record_count} 条任务记录")
                    
                    # 等待下一次监控
                    await asyncio.sleep(self.monitor_interval)
                    
                except Exception as e:
                    logger.error(f"调度循环异常: {e}")
                    await asyncio.sleep(self.monitor_interval)
        
        logger.info("⏹️  任务调度器已停止")
    
    def start(self):
        """启动调度器"""
        logger.info("🚀 启动 MinerU Tianshu 任务调度器...")
        
        # 设置信号处理
        def signal_handler(sig, frame):
            logger.info("\n🛑 收到停止信号，正在关闭...")
            self.running = False
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # 运行调度循环
        asyncio.run(self.schedule_loop())
    
    def stop(self):
        """停止调度器"""
        self.running = False


async def health_check(litserve_url: str) -> bool:
    """
    健康检查：验证 LitServe Worker 是否可用
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                litserve_url.replace('/predict', '/health'),
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
    except:
        return False


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='MinerU Tianshu Task Scheduler (Optional)')
    parser.add_argument('--litserve-url', type=str, default='http://localhost:39021/predict',
                       help='LitServe worker URL')
    parser.add_argument('--monitor-interval', type=int, default=300,
                       help='Monitor interval in seconds (default: 300s = 5 minutes)')
    parser.add_argument('--health-check-interval', type=int, default=900,
                       help='Health check interval in seconds (default: 900s = 15 minutes)')
    parser.add_argument('--stale-task-timeout', type=int, default=60,
                       help='Timeout for stale tasks in minutes (default: 60)')
    parser.add_argument('--cleanup-old-files-days', type=int, default=7,
                       help='Delete result files older than N days (0=disable, default: 7)')
    parser.add_argument('--cleanup-old-records-days', type=int, default=0,
                       help='Delete DB records older than N days (0=disable, NOT recommended)')
    parser.add_argument('--wait-for-workers', action='store_true',
                       help='Wait for workers to be ready before starting')
    parser.add_argument('--no-worker-auto-mode', action='store_true',
                       help='Disable worker auto-loop mode assumption')
    
    args = parser.parse_args()
    
    # 等待 workers 就绪（可选）
    if args.wait_for_workers:
        logger.info("⏳ 正在等待 LitServe workers 就绪...")
        import time
        max_retries = 30
        for i in range(max_retries):
            if asyncio.run(health_check(args.litserve_url)):
                logger.info("✅ LitServe workers 已就绪！")
                break
            time.sleep(2)
            if i == max_retries - 1:
                logger.error("❌ LitServe workers 未响应，继续启动...")
    
    # 创建并启动调度器
    scheduler = TaskScheduler(
        litserve_url=args.litserve_url,
        monitor_interval=args.monitor_interval,
        health_check_interval=args.health_check_interval,
        stale_task_timeout=args.stale_task_timeout,
        cleanup_old_files_days=args.cleanup_old_files_days,
        cleanup_old_records_days=args.cleanup_old_records_days,
        worker_auto_mode=not args.no_worker_auto_mode
    )
    
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("👋 调度器被用户中断")

