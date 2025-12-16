"""
MinerU Tianshu - Unified Startup Script
天枢统一启动脚本

一键启动所有服务：API Server + LitServe Workers + Task Scheduler
"""
import subprocess
import signal
import sys
import time
import os
from loguru import logger
from pathlib import Path
import argparse


class TianshuLauncher:
    """天枢服务启动器"""
    
    def __init__(
        self,
        output_dir='/tmp/mineru_tianshu_output',
        api_port=39020,
        worker_port=39021,
        workers_per_device=1,
        devices='auto',
        accelerator='auto'
    ):
        self.output_dir = output_dir
        self.api_port = api_port
        self.worker_port = worker_port
        self.workers_per_device = workers_per_device
        self.devices = devices
        self.accelerator = accelerator
        self.processes = []
        # 本地离线模型配置
        self.model_cache_root = r'C:\Users\fengh\.cache\modelscope'
        self.model_config_path = Path(__file__).parent / 'mineru.local.json'

    def _build_env(self):
        env = os.environ.copy()
        env.update({
            'MINERU_MODEL_SOURCE': 'local',  # 强制本地模式，不触发下载
            'MINERU_TOOLS_CONFIG_JSON': str(self.model_config_path),
            'MINERU_MODEL_CACHE_DIR': self.model_cache_root,
            'MODELSCOPE_CACHE': self.model_cache_root,
            'HUGGINGFACE_HUB_CACHE': self.model_cache_root,
            'HF_HOME': self.model_cache_root,
            'TRANSFORMERS_CACHE': self.model_cache_root,
            'HF_HUB_OFFLINE': '1',
            'TRANSFORMERS_OFFLINE': '1',
        })
        return env
    
    def start_services(self):
        """启动所有服务"""
        logger.info("=" * 70)
        logger.info("🚀 MinerU Tianshu - 启动所有服务")
        logger.info("=" * 70)
        logger.info("天枢 - 企业级多GPU文档解析服务")
        logger.info("")
        
        try:
            # 1. 启动 API Server
            logger.info("📡 [1/3] 正在启动 API Server...")
            env = self._build_env()
            env['API_PORT'] = str(self.api_port)
            api_proc = subprocess.Popen(
                [sys.executable, 'api_server.py'],
                cwd=Path(__file__).parent,
                env=env
            )
            self.processes.append(('API Server', api_proc))
            time.sleep(3)
            
            if api_proc.poll() is not None:
                logger.error("❌ API Server 启动失败！")
                return False
            
            logger.info(f"   ✅ API Server 启动成功 (PID: {api_proc.pid})")
            logger.info(f"   📖 API 文档: http://localhost:{self.api_port}/docs")
            logger.info("")
            
            # 2. 启动 LitServe Worker Pool
            logger.info("⚙️  [2/3] 正在启动 LitServe Worker 池...")
            worker_cmd = [
                sys.executable, 'litserve_worker.py',
                '--output-dir', self.output_dir,
                '--accelerator', self.accelerator,
                '--workers-per-device', str(self.workers_per_device),
                '--port', str(self.worker_port),
                '--devices', str(self.devices) if isinstance(self.devices, str) else ','.join(map(str, self.devices))
            ]
            
            worker_proc = subprocess.Popen(
                worker_cmd,
                cwd=Path(__file__).parent,
                env=self._build_env()
            )
            self.processes.append(('LitServe Workers', worker_proc))
            time.sleep(5)
            
            if worker_proc.poll() is not None:
                logger.error("❌ LitServe Workers 启动失败！")
                return False
            
            logger.info(f"   ✅ LitServe Workers 启动成功 (PID: {worker_proc.pid})")
            logger.info(f"   🔌 Worker 端口: {self.worker_port}")
            logger.info(f"   👷 每卡 Worker 数: {self.workers_per_device}")
            logger.info("")
            
            # 3. 启动 Task Scheduler
            logger.info("🔄 [3/3] 正在启动任务调度器...")
            scheduler_cmd = [
                sys.executable, 'task_scheduler.py',
                '--litserve-url', f'http://localhost:{self.worker_port}/predict',
                '--wait-for-workers'
            ]
            
            scheduler_proc = subprocess.Popen(
                scheduler_cmd,
                cwd=Path(__file__).parent,
                env=self._build_env()
            )
            self.processes.append(('Task Scheduler', scheduler_proc))
            time.sleep(3)
            
            if scheduler_proc.poll() is not None:
                logger.error("❌ 任务调度器启动失败！")
                return False
            
            logger.info(f"   ✅ 任务调度器启动成功 (PID: {scheduler_proc.pid})")
            logger.info("")
            
            # 启动成功
            logger.info("=" * 70)
            logger.info("✅ 所有服务启动完成！")
            logger.info("=" * 70)
            logger.info("")
            logger.info("📚 快速开始:")
            logger.info(f"   • API 文档: http://localhost:{self.api_port}/docs")
            logger.info(f"   • 提交任务: POST http://localhost:{self.api_port}/api/v1/tasks/submit")
            logger.info(f"   • 查询状态: GET  http://localhost:{self.api_port}/api/v1/tasks/{{task_id}}")
            logger.info(f"   • 队列统计: GET  http://localhost:{self.api_port}/api/v1/queue/stats")
            logger.info("")
            logger.info("🔧 服务详情:")
            for name, proc in self.processes:
                logger.info(f"   • {name:20s} 进程 PID: {proc.pid}")
            logger.info("")
            logger.info("⚠️  按 Ctrl+C 停止所有服务")
            logger.info("=" * 70)
            
            return True
            
        except Exception as e:
            logger.error(f"❌ 启动服务失败: {e}")
            self.stop_services()
            return False
    
    def stop_services(self, signum=None, frame=None):
        """停止所有服务"""
        logger.info("")
        logger.info("=" * 70)
        logger.info("⏹️  正在停止所有服务...")
        logger.info("=" * 70)
        
        for name, proc in self.processes:
            if proc.poll() is None:  # 进程仍在运行
                logger.info(f"   正在停止 {name} (PID: {proc.pid})...")
                proc.terminate()
        
        # 等待所有进程结束
        for name, proc in self.processes:
            try:
                proc.wait(timeout=10)
                logger.info(f"   ✅ {name} 已停止")
            except subprocess.TimeoutExpired:
                logger.warning(f"   ⚠️  {name} 未正常停止，正在强制结束...")
                proc.kill()
                proc.wait()
        
        logger.info("=" * 70)
        logger.info("✅ 所有服务已停止")
        logger.info("=" * 70)
        sys.exit(0)
    
    def wait(self):
        """等待所有服务"""
        try:
            while True:
                time.sleep(1)
                
                # 检查进程状态
                for name, proc in self.processes:
                    if proc.poll() is not None:
                        logger.error(f"❌ {name} 异常退出！")
                        self.stop_services()
                        return
                        
        except KeyboardInterrupt:
            self.stop_services()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='MinerU Tianshu - 统一启动脚本',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用默认配置启动（自动检测GPU）
  python start_all.py
  
  # 使用CPU模式
  python start_all.py --accelerator cpu
  
  # 指定输出目录和端口
  python start_all.py --output-dir /data/output --api-port 8080
  
  # 每个GPU启动2个worker
  python start_all.py --accelerator cuda --workers-per-device 2
  
  # 只使用指定的GPU
  python start_all.py --accelerator cuda --devices 0,1
        """
    )
    
    parser.add_argument('--output-dir', type=str, default='/tmp/mineru_tianshu_output',
                       help='输出目录 (默认: /tmp/mineru_tianshu_output)')
    parser.add_argument('--api-port', type=int, default=39020,
                       help='API服务器端口 (默认: 39020)')
    parser.add_argument('--worker-port', type=int, default=39021,
                       help='Worker服务器端口 (默认: 39021)')
    parser.add_argument('--accelerator', type=str, default='auto',
                       choices=['auto', 'cuda', 'cpu', 'mps'],
                       help='加速器类型 (默认: auto，自动检测)')
    parser.add_argument('--workers-per-device', type=int, default=1,
                       help='每个GPU的worker数量 (默认: 1)')
    parser.add_argument('--devices', type=str, default='auto',
                       help='使用的GPU设备，逗号分隔 (默认: auto，使用所有GPU)')
    
    args = parser.parse_args()
    
    # 处理 devices 参数
    devices = args.devices
    if devices != 'auto':
        try:
            devices = [int(d) for d in devices.split(',')]
        except:
            logger.warning(f"设备格式无效: {devices}，将改用 'auto'")
            devices = 'auto'
    
    # 创建启动器
    launcher = TianshuLauncher(
        output_dir=args.output_dir,
        api_port=args.api_port,
        worker_port=args.worker_port,
        workers_per_device=args.workers_per_device,
        devices=devices,
        accelerator=args.accelerator
    )
    
    # 设置信号处理
    signal.signal(signal.SIGINT, launcher.stop_services)
    signal.signal(signal.SIGTERM, launcher.stop_services)
    
    # 启动服务
    if launcher.start_services():
        launcher.wait()
    else:
        sys.exit(1)


if __name__ == '__main__':
    main()

