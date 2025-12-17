"""
MinerU Tianshu - LitServe Worker
天枢 LitServe Worker

使用 LitServe 实现 GPU 资源的自动负载均衡
Worker 主动循环拉取任务并处理
"""
import os
import json
import sys
import time
import threading
import signal
import atexit
from pathlib import Path
from typing import Optional, Dict, List
import litserve as ls
from loguru import logger

# 添加父目录到路径以导入 MinerU
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from task_db import TaskDB
from oss_client import CTYunOSSClient, OSSConfig
from mineru.cli.common import do_parse, read_fn
from mineru.utils.config_reader import get_device
from mineru.utils.model_utils import get_vram, clean_memory

# 默认模型缓存目录，可通过环境变量 MINERU_MODEL_CACHE_DIR 覆盖
# Windows 本地默认指向 ModelScope 缓存根目录（~/.cache/modelscope）
DEFAULT_MODEL_CACHE_DIR = os.getenv(
    'MINERU_MODEL_CACHE_DIR',
    r'C:\Users\fengh\.cache\modelscope'
)


def setup_model_cache_dir(cache_dir: str = DEFAULT_MODEL_CACHE_DIR):
    """
    设置模型下载/缓存目录，覆盖 huggingface 和 modelscope 的默认缓存。
    """
    if not cache_dir:
        return
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault('HUGGINGFACE_HUB_CACHE', str(cache_path))
    os.environ.setdefault('HF_HOME', str(cache_path))
    os.environ.setdefault('TRANSFORMERS_CACHE', str(cache_path))
    os.environ.setdefault('MODELSCOPE_CACHE', str(cache_path))
    logger.info(f"📦 模型缓存目录设置为 {cache_path}")


# 确保在导入和 Worker 启动前设置缓存目录
setup_model_cache_dir()


def patch_hf_snapshot_with_modelscope(cache_dir: str = DEFAULT_MODEL_CACHE_DIR):
    """
    将 huggingface_hub.snapshot_download 打补丁为优先 HF，失败 fallback ModelScope。
    """
    try:
        import huggingface_hub
        from huggingface_hub import snapshot_download as hf_snapshot_download
        from modelscope.hub.snapshot_download import snapshot_download as ms_snapshot_download
    except ImportError:
        logger.warning("⚠️  huggingface_hub 或 modelscope 未安装，跳过下载补丁")
        return

    def _patched_snapshot_download(*args, **kwargs):
        repo_id = kwargs.get('repo_id') or (args[0] if args else None)
        revision = kwargs.get('revision')
        cache_dir_arg = kwargs.get('cache_dir') or cache_dir
        logger.info(f"📦 准备下载模型: repo_id={repo_id}, revision={revision}, cache_dir={cache_dir_arg}")
        try:
            return hf_snapshot_download(*args, **kwargs)
        except Exception as hf_err:
            logger.warning(f"⚠️  HF 下载失败，尝试改用 ModelScope：{hf_err}")
            ms_kwargs = {
                'model_id': repo_id,
                'revision': revision,
                'cache_dir': cache_dir_arg,
            }
            try:
                # 只传递 ModelScope 支持的参数
                return ms_snapshot_download(**{k: v for k, v in ms_kwargs.items() if v is not None})
            except Exception as ms_err:
                raise RuntimeError(f"HuggingFace 下载失败且 ModelScope 兜底失败：{ms_err}") from hf_err

    huggingface_hub.snapshot_download = _patched_snapshot_download
    logger.info("🔁 huggingface_hub.snapshot_download 已打补丁，失败时回退到 ModelScope")


# 在导入 MinerU 前打补丁，确保内部使用的 HF 下载也能回退
patch_hf_snapshot_with_modelscope()

# 尝试导入 markitdown
try:
    from markitdown import MarkItDown
    MARKITDOWN_AVAILABLE = True
except ImportError:
    MARKITDOWN_AVAILABLE = False
    logger.warning("⚠️  未安装 markitdown，Office 格式解析将被禁用")


class MinerUWorkerAPI(ls.LitAPI):
    """
    LitServe API Worker
    
    Worker 主动循环拉取任务，利用 LitServe 的自动 GPU 负载均衡
    支持两种解析方式：
    - PDF/图片 -> MinerU 解析（GPU 加速）
    - 其他所有格式 -> MarkItDown 解析（快速处理）
    
    新模式：每个 worker 启动后持续循环拉取任务，处理完一个立即拉取下一个
    """
    
    # 支持的文件格式定义
    # MinerU 专用格式：PDF 和图片
    PDF_IMAGE_FORMATS = {'.pdf', '.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.tif', '.webp'}
    # 其他所有格式都使用 MarkItDown 解析
    
    def __init__(self, output_dir='/tmp/mineru_tianshu_output', worker_id_prefix='tianshu', 
                 poll_interval=0.5, enable_worker_loop=True):
        super().__init__()
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.worker_id_prefix = worker_id_prefix
        self.poll_interval = poll_interval  # Worker 拉取任务的间隔（秒）
        self.enable_worker_loop = enable_worker_loop  # 是否启用 worker 循环拉取
        self.db = TaskDB()
        self.worker_id = None
        self.markitdown = None
        self.running = False  # Worker 运行状态
        self.worker_thread = None  # Worker 线程
        self.oss_client: Optional[CTYunOSSClient] = None
        self.oss_config = self._load_oss_config()

    @staticmethod
    def _get_int_env(name: str, default: int) -> int:
        try:
            val = os.getenv(name)
            return int(val) if val is not None and val != '' else default
        except ValueError:
            return default

    def _load_oss_config(self) -> Dict:
        """
        读取天翼云 OSS 配置；缺失必填项时返回空 dict
        """
        cfg = {
            'access_key': os.getenv('CTYUN_ACCESS_KEY', '0NAG9S3AFKVCLP6F5CC7'),
            'secret_key': os.getenv('CTYUN_SECRET_KEY', 'B33aA5PjbuEe4TUoVOQaA3xetAkNhNQlUuJHbDR0'),
            'endpoint': os.getenv('CTYUN_ENDPOINT', 'https://shanghai-9.zos.ctyun.cn'),
            'bucket': os.getenv('CTYUN_BUCKET', 'spotlight'),
            'region': os.getenv('CTYUN_REGION', 'cn'),
            'prefix': os.getenv('CTYUN_PREFIX', 'tasks'),
            'external_host': os.getenv('CTYUN_EXTERNAL_HOST', 'https://spotlight.shanghai-9.zos.ctyun.cn'),
            'presign_expire': self._get_int_env('CTYUN_PRESIGN_EXPIRE', 24 * 3600),
        }
        required = ['access_key', 'secret_key', 'endpoint', 'bucket']
        if not all(cfg.get(k) for k in required):
            logger.warning("⚠️ 未配置完整的天翼云 OSS 凭据，Worker 将跳过上传")
            return {}
        return cfg

    def _get_oss_client(self) -> Optional[CTYunOSSClient]:
        """懒加载 OSS 客户端"""
        if not self.oss_config:
            return None
        if self.oss_client is None:
            cfg = self.oss_config
            self.oss_client = CTYunOSSClient(
                OSSConfig(
                    access_key=cfg['access_key'],
                    secret_key=cfg['secret_key'],
                    endpoint=cfg['endpoint'],
                    bucket=cfg['bucket'],
                    region=cfg['region'],
                    default_prefix=cfg['prefix'],
                    external_host=cfg.get('external_host') or None,
                    presign_expire=cfg['presign_expire'],
                )
            )
        return self.oss_client

    def _upload_result_to_oss(self, task_id: str, result_dir: Path):
        """
        将任务结果目录上传到天翼云 OSS，生成 manifest
        """
        client = self._get_oss_client()
        if not client:
            logger.warning(f"⚠️ 未配置 OSS，跳过上传: task_id={task_id}")
            return

        if not result_dir.exists():
            logger.warning(f"⚠️ 结果目录不存在，无法上传: {result_dir}")
            return

        manifest_path = result_dir / 'oss_manifest.json'
        if manifest_path.exists():
            logger.info(f"ℹ️ 已存在 OSS manifest，跳过重复上传: {manifest_path}")
            return

        files: List[Path] = [p for p in result_dir.rglob('*') if p.is_file() and p.name != 'oss_manifest.json']
        if not files:
            logger.info(f"ℹ️ 结果目录为空，跳过上传: {result_dir}")
            return

        prefix = f"{self.oss_config['prefix'].rstrip('/')}/{task_id}"
        logger.info(f"🆙 正在上传任务 {task_id} 结果到天翼云，文件数: {len(files)}，前缀: {prefix}")
        uploaded = client.upload_files(result_dir, files, prefix)

        manifest = {"prefix": prefix, "files": []}
        for item in uploaded:
            object_key = item['object_key']
            presign_url = client.presign_url(object_key)
            public_url = client.public_url(object_key)
            manifest['files'].append({
                "relative_path": str(Path(item['local_path']).relative_to(result_dir)),
                "object_key": object_key,
                "presign_url": presign_url,
                "public_url": public_url,
                "url": public_url or presign_url,
            })

        try:
            with open(manifest_path, 'w', encoding='utf-8') as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ 任务 {task_id} 已上传 OSS，manifest: {manifest_path}")
        except Exception as e:
            logger.warning(f"写入 OSS manifest 失败: {e}")
    
    def setup(self, device):
        """
        初始化环境（每个 worker 进程调用一次）
        
        关键修复：使用 CUDA_VISIBLE_DEVICES 确保每个进程只使用分配的 GPU
        
        Args:
            device: LitServe 分配的设备 (cuda:0, cuda:1, etc.)
        """
        # 生成唯一的 worker_id
        import socket
        hostname = socket.gethostname()
        pid = os.getpid()
        self.worker_id = f"{self.worker_id_prefix}-{hostname}-{device}-{pid}"
        
        logger.info(f"⚙️  Worker {self.worker_id} 正在使用设备 {device} 进行初始化")
        
        # 关键修复：设置 CUDA_VISIBLE_DEVICES 限制进程只能看到分配的 GPU
        # 这样可以防止一个进程占用多张卡的显存
        if device != 'auto' and device != 'cpu' and ':' in str(device):
            # 从 'cuda:0' 提取设备ID '0'
            device_id = str(device).split(':')[-1]
            os.environ['CUDA_VISIBLE_DEVICES'] = device_id
            # 设置为 cuda:0，因为对进程来说只能看到一张卡（逻辑ID变为0）
            os.environ['MINERU_DEVICE_MODE'] = 'cuda:0'
            device_mode = os.environ['MINERU_DEVICE_MODE']
            logger.info(f"🔒 已设置 CUDA_VISIBLE_DEVICES={device_id} (物理 GPU {device_id} → 逻辑 GPU 0)")
        else:
            # 配置 MinerU 环境
            if os.getenv('MINERU_DEVICE_MODE', None) is None:
                os.environ['MINERU_DEVICE_MODE'] = device if device != 'auto' else get_device()
            device_mode = os.environ['MINERU_DEVICE_MODE']
        
        # 配置显存
        if os.getenv('MINERU_VIRTUAL_VRAM_SIZE', None) is None:
            if device_mode.startswith("cuda") or device_mode.startswith("npu"):
                try:
                    vram = get_vram(device_mode)
                    os.environ['MINERU_VIRTUAL_VRAM_SIZE'] = str(vram)
                except:
                    os.environ['MINERU_VIRTUAL_VRAM_SIZE'] = '8'  # 默认值
            else:
                os.environ['MINERU_VIRTUAL_VRAM_SIZE'] = '1'
        
        # 初始化 MarkItDown（如果可用）
        if MARKITDOWN_AVAILABLE:
            self.markitdown = MarkItDown()
            logger.info(f"✅ MarkItDown 已初始化，可用于 Office 格式解析")
        
        logger.info(f"✅ Worker {self.worker_id} 准备就绪")
        logger.info(f"   设备: {device_mode}")
        logger.info(f"   显存: {os.environ['MINERU_VIRTUAL_VRAM_SIZE']}GB")
        
        # 启动 worker 循环拉取任务（在独立线程中）
        if self.enable_worker_loop:
            self.running = True
            self.worker_thread = threading.Thread(
                target=self._worker_loop, 
                daemon=True,
                name=f"Worker-{self.worker_id}"
            )
            self.worker_thread.start()
            logger.info(f"🔄 Worker 循环已启动 (轮询间隔={self.poll_interval}s)")
    
    def teardown(self):
        """
        优雅关闭 Worker
        
        设置 running 标志为 False，等待 worker 线程完成当前任务后退出。
        这避免了守护线程可能导致的任务处理不完整或数据库操作不一致问题。
        """
        if self.enable_worker_loop and self.worker_thread and self.worker_thread.is_alive():
            logger.info(f"🛑 正在关闭 worker {self.worker_id}...")
            self.running = False
            
            # 等待线程完成当前任务（最多等待 poll_interval * 2 秒）
            timeout = self.poll_interval * 2
            self.worker_thread.join(timeout=timeout)
            
            if self.worker_thread.is_alive():
                logger.warning(f"⚠️  Worker 线程在 {timeout}s 内未停止，准备强制退出")
            else:
                logger.info(f"✅ Worker {self.worker_id} 已优雅退出")
    
    def _worker_loop(self):
        """
        Worker 主循环：持续拉取并处理任务
        
        这个方法在独立线程中运行，让每个 worker 主动拉取任务
        而不是被动等待调度器触发
        """
        logger.info(f"🔁 {self.worker_id} 启动任务轮询循环")
        
        idle_count = 0
        while self.running:
            try:
                # 从数据库获取任务
                task = self.db.get_next_task(self.worker_id)
                
                if task:
                    idle_count = 0  # 重置空闲计数
                    
                    # 处理任务
                    task_id = task['task_id']
                    logger.info(f"🔄 {self.worker_id} 领取任务 {task_id}")
                    
                    try:
                        self._process_task(task)
                    except Exception as e:
                        logger.error(f"❌ {self.worker_id} 处理任务 {task_id} 失败: {e}")
                        success = self.db.update_task_status(
                            task_id, 'failed', 
                            error_message=str(e), 
                            worker_id=self.worker_id
                        )
                        if not success:
                            logger.warning(f"⚠️  任务 {task_id} 在失败更新时被其他进程修改")
                    
                else:
                    # 没有任务时，增加空闲计数
                    idle_count += 1
                    
                    # 只在第一次空闲时记录日志，避免刷屏
                    if idle_count == 1:
                        logger.debug(f"💤 {self.worker_id} 空闲中，等待新任务...")
                    
                    # 空闲时等待一段时间再拉取
                    time.sleep(self.poll_interval)
                    
            except Exception as e:
                logger.error(f"❌ {self.worker_id} 循环发生异常: {e}")
                time.sleep(self.poll_interval)
        
        logger.info(f"⏹️  {self.worker_id} 已停止任务轮询循环")
    
    def _process_task(self, task: dict):
        """
        处理单个任务
        
        Args:
            task: 任务字典
        """
        task_id = task['task_id']
        file_path = task['file_path']
        file_name = task['file_name']
        backend = task['backend']
        options = json.loads(task['options'])
        
        logger.info(f"🔄 正在处理任务 {task_id}: {file_name}")
        
        try:
            # 准备输出目录
            output_path = self.output_dir / task_id
            output_path.mkdir(parents=True, exist_ok=True)
            
            # 判断文件类型并选择解析方式
            file_type = self._get_file_type(file_path)
            
            if file_type == 'pdf_image':
                # 使用 MinerU 解析 PDF 和图片
                self._parse_with_mineru(
                    file_path=Path(file_path),
                    file_name=file_name,
                    task_id=task_id,
                    backend=backend,
                    options=options,
                    output_path=output_path
                )
                parse_method = 'MinerU'
                
            else:  # file_type == 'markitdown'
                # 使用 markitdown 解析所有其他格式
                self._parse_with_markitdown(
                    file_path=Path(file_path),
                    file_name=file_name,
                    output_path=output_path
                )
                parse_method = 'MarkItDown'
            
            # 更新状态为成功
            success = self.db.update_task_status(
                task_id, 'completed', 
                result_path=str(output_path),
                worker_id=self.worker_id
            )
            
            if success:
                logger.info(f"✅ 任务 {task_id} 已由 {self.worker_id} 完成")
                logger.info(f"   解析器: {parse_method}")
                logger.info(f"   输出目录: {output_path}")
                # 成功后尝试上传 OSS（若配置可用）
                try:
                    self._upload_result_to_oss(task_id, output_path)
                except Exception as e:
                    logger.error(f"❌ 上传任务 {task_id} 结果到 OSS 失败: {e}")
            else:
                logger.warning(
                    f"⚠️  任务 {task_id} 被其他进程修改。"
                    f"Worker {self.worker_id} 已完成工作但状态更新被拒绝。"
                )
            
        finally:
            # 清理临时文件
            try:
                if Path(file_path).exists():
                    Path(file_path).unlink()
            except Exception as e:
                logger.warning(f"清理临时文件 {file_path} 失败: {e}")
    
    def decode_request(self, request):
        """
        解码请求
        
        现在主要用于健康检查和手动触发（兼容旧接口）
        """
        return request.get('action', 'poll')
    
    def _get_file_type(self, file_path: str) -> str:
        """
        判断文件类型
        
        Args:
            file_path: 文件路径
            
        Returns:
            'pdf_image': PDF 或图片格式，使用 MinerU 解析
            'markitdown': 其他所有格式，使用 markitdown 解析
        """
        suffix = Path(file_path).suffix.lower()
        
        if suffix in self.PDF_IMAGE_FORMATS:
            return 'pdf_image'
        else:
            # 所有非 PDF/图片格式都使用 markitdown
            return 'markitdown'
    
    def _parse_with_mineru(self, file_path: Path, file_name: str, task_id: str, 
                           backend: str, options: dict, output_path: Path):
        """
        使用 MinerU 解析 PDF 和图片格式
        
        Args:
            file_path: 文件路径
            file_name: 文件名
            task_id: 任务ID
            backend: 后端类型
            options: 解析选项
            output_path: 输出路径
        """
        logger.info(f"📄 使用 MinerU 解析: {file_name}")
        
        try:
            # 读取文件
            pdf_bytes = read_fn(file_path)
            
            # 执行解析（MinerU 的 ModelSingleton 会自动复用模型）
            do_parse(
                output_dir=str(output_path),
                pdf_file_names=[Path(file_name).stem],
                pdf_bytes_list=[pdf_bytes],
                p_lang_list=[options.get('lang', 'ch')],
                backend=backend,
                parse_method=options.get('method', 'auto'),
                formula_enable=options.get('formula_enable', True),
                table_enable=options.get('table_enable', True),
            )
        finally:
            # 使用 MinerU 自带的内存清理函数
            # 这个函数只清理推理产生的中间结果，不会卸载模型
            try:
                clean_memory()
            except Exception as e:
                logger.debug(f"任务 {task_id} 清理显存失败: {e}")
    
    def _parse_with_markitdown(self, file_path: Path, file_name: str, 
                               output_path: Path):
        """
        使用 markitdown 解析文档（支持 Office、HTML、文本等多种格式）
        
        Args:
            file_path: 文件路径
            file_name: 文件名
            output_path: 输出路径
        """
        if not MARKITDOWN_AVAILABLE or self.markitdown is None:
            raise RuntimeError("markitdown is not available. Please install it: pip install markitdown")
        
        logger.info(f"📊 使用 MarkItDown 解析: {file_name}")
        
        # 使用 markitdown 转换文档
        result = self.markitdown.convert(str(file_path))
        
        # 保存为 markdown 文件
        output_file = output_path / f"{Path(file_name).stem}.md"
        output_file.write_text(result.text_content, encoding='utf-8')
        
        logger.info(f"📝 Markdown 已保存到: {output_file}")
    
    def predict(self, action):
        """
        HTTP 接口（主要用于健康检查和监控）
        
        现在任务由 worker 循环自动拉取处理，这个接口主要用于：
        1. 健康检查
        2. 获取 worker 状态
        3. 兼容旧的手动触发模式（当 enable_worker_loop=False 时）
        """
        if action == 'health':
            # 健康检查
            stats = self.db.get_queue_stats()
            return {
                'status': 'healthy',
                'worker_id': self.worker_id,
                'worker_loop_enabled': self.enable_worker_loop,
                'worker_running': self.running,
                'queue_stats': stats
            }
        
        elif action == 'poll':
            if not self.enable_worker_loop:
                # 兼容模式：手动触发任务拉取
                task = self.db.get_next_task(self.worker_id)
                
                if not task:
                    return {
                        'status': 'idle',
                        'message': 'No pending tasks in queue',
                        'worker_id': self.worker_id
                    }
                
                try:
                    self._process_task(task)
                    return {
                        'status': 'completed',
                        'task_id': task['task_id'],
                        'worker_id': self.worker_id
                    }
                except Exception as e:
                    return {
                        'status': 'failed',
                        'task_id': task['task_id'],
                        'error': str(e),
                        'worker_id': self.worker_id
                    }
            else:
                # Worker 循环模式：返回状态信息
                return {
                    'status': 'auto_mode',
                    'message': 'Worker is running in auto-loop mode, tasks are processed automatically',
                    'worker_id': self.worker_id,
                    'worker_running': self.running
                }
        
        else:
            return {
                'status': 'error',
                'message': f'Invalid action: {action}. Use "health" or "poll".',
                'worker_id': self.worker_id
            }
    
    def encode_response(self, response):
        """编码响应"""
        return response


def start_litserve_workers(
    output_dir='/tmp/mineru_tianshu_output',
    accelerator='auto',
    devices='auto',
    workers_per_device=1,
    port=39021,
    poll_interval=0.5,
    enable_worker_loop=True
):
    """
    启动 LitServe Worker Pool
    
    Args:
        output_dir: 输出目录
        accelerator: 加速器类型 (auto/cuda/cpu/mps)
        devices: 使用的设备 (auto/[0,1,2])
        workers_per_device: 每个 GPU 的 worker 数量
        port: 服务端口
        poll_interval: Worker 拉取任务的间隔（秒）
        enable_worker_loop: 是否启用 worker 自动循环拉取任务
    """
    logger.info("=" * 60)
    logger.info("🚀 启动 MinerU Tianshu LitServe Worker 池")
    logger.info("=" * 60)
    logger.info(f"📂 输出目录: {output_dir}")
    logger.info(f"🎮 加速器: {accelerator}")
    logger.info(f"💾 设备: {devices}")
    logger.info(f"👷 每设备 Worker 数: {workers_per_device}")
    logger.info(f"🔌 端口: {port}")
    logger.info(f"🔄 Worker 循环: {'开启' if enable_worker_loop else '关闭'}")
    if enable_worker_loop:
        logger.info(f"⏱️  轮询间隔: {poll_interval}s")
    logger.info("=" * 60)
    
    # 创建 LitServe 服务器
    api = MinerUWorkerAPI(
        output_dir=output_dir,
        poll_interval=poll_interval,
        enable_worker_loop=enable_worker_loop
    )
    server = ls.LitServer(
        api,
        accelerator=accelerator,
        devices=devices,
        workers_per_device=workers_per_device,
        timeout=False,  # 不设置超时
    )
    
    # 注册优雅关闭处理器
    def graceful_shutdown(signum=None, frame=None):
        """处理关闭信号，优雅地停止 worker"""
        logger.info("🛑 收到停止信号，正在优雅关闭 workers...")
        # 注意：LitServe 会为每个设备创建多个 worker 实例
        # 这里的 api 只是模板，实际的 worker 实例由 LitServe 管理
        # teardown 会在每个 worker 进程中被调用
        if hasattr(api, 'teardown'):
            api.teardown()
        sys.exit(0)
    
    # 注册信号处理器（Ctrl+C 等）
    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)
    
    # 注册 atexit 处理器（正常退出时调用）
    atexit.register(lambda: api.teardown() if hasattr(api, 'teardown') else None)
    
    logger.info(f"✅ LitServe Worker 池已初始化")
    logger.info(f"📡 监听地址: http://0.0.0.0:{port}/predict")
    if enable_worker_loop:
        logger.info(f"🔁 Workers 将持续轮询并处理任务")
    else:
        logger.info(f"🔄 Workers 将等待调度器触发")
    logger.info("=" * 60)
    
    # 启动服务器
    server.run(port=port, generate_client_file=False)


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='MinerU Tianshu LitServe Worker Pool')
    parser.add_argument('--output-dir', type=str, default='/tmp/mineru_tianshu_output',
                       help='Output directory for processed files')
    parser.add_argument('--accelerator', type=str, default='auto',
                       choices=['auto', 'cuda', 'cpu', 'mps'],
                       help='Accelerator type')
    parser.add_argument('--devices', type=str, default='auto',
                       help='Devices to use (auto or comma-separated list like 0,1,2)')
    parser.add_argument('--workers-per-device', type=int, default=1,
                       help='Number of workers per device')
    parser.add_argument('--port', type=int, default=39021,
                       help='Server port')
    parser.add_argument('--poll-interval', type=float, default=0.5,
                       help='Worker poll interval in seconds (default: 0.5)')
    parser.add_argument('--disable-worker-loop', action='store_true',
                       help='Disable worker auto-loop mode (use scheduler-driven mode)')
    
    args = parser.parse_args()
    
    # 处理 devices 参数
    devices = args.devices
    if devices != 'auto':
        try:
            devices = [int(d) for d in devices.split(',')]
        except:
            logger.warning(f"设备格式无效: {devices}，将改用 'auto'")
            devices = 'auto'
    
    start_litserve_workers(
        output_dir=args.output_dir,
        accelerator=args.accelerator,
        devices=devices,
        workers_per_device=args.workers_per_device,
        port=args.port,
        poll_interval=args.poll_interval,
        enable_worker_loop=not args.disable_worker_loop
    )


