"""
聚光 MinerU - API Server
聚光 MinerU API服务器

提供RESTful API接口用于任务提交、查询和管理
"""
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import tempfile
from pathlib import Path
from loguru import logger
import uvicorn
from datetime import datetime
import os
import json
from typing import Dict, List, Optional

from task_db import TaskDB
from oss_client import CTYunOSSClient, OSSConfig

# 初始化 FastAPI 应用
app = FastAPI(
    title="聚光 MinerU API",
    description="聚光 MinerU - 企业级多GPU文档解析服务",
    version="1.0.0"
)

# 添加 CORS 中间件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化数据库
db = TaskDB()

# 配置输出目录
OUTPUT_DIR = Path('/tmp/mineru_spotlight_output')
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


# 天翼云 OSS 配置（优先环境变量，缺省使用提供的值）
def _get_int_env(name: str, default: int) -> int:
    try:
        val = os.getenv(name)
        return int(val) if val is not None and val != '' else default
    except ValueError:
        return default


CTYUN_CONFIG = {
    'access_key': os.getenv('CTYUN_ACCESS_KEY', '0NAG9S3AFKVCLP6F5CC7'),
    'secret_key': os.getenv('CTYUN_SECRET_KEY', 'B33aA5PjbuEe4TUoVOQaA3xetAkNhNQlUuJHbDR0'),
    'endpoint': os.getenv('CTYUN_ENDPOINT', 'https://shanghai-9.zos.ctyun.cn'),
    'bucket': os.getenv('CTYUN_BUCKET', 'spotlight'),
    'region': os.getenv('CTYUN_REGION', 'cn'),
    'prefix': os.getenv('CTYUN_PREFIX', 'tasks'),
    'external_host': os.getenv('CTYUN_EXTERNAL_HOST', 'https://spotlight.shanghai-9.zos.ctyun.cn'),
    'presign_expire': _get_int_env('CTYUN_PRESIGN_EXPIRE', 24 * 3600)
}




_oss_client: Optional[CTYunOSSClient] = None


def get_oss_client() -> Optional[CTYunOSSClient]:
    """获取天翼云 OSS 客户端，缺少配置则返回 None"""
    global _oss_client
    required = ['access_key', 'secret_key', 'endpoint', 'bucket']
    if not all(CTYUN_CONFIG.get(k) for k in required):
        logger.warning("⚠️ 未配置完整的天翼云 OSS 凭据，跳过上传")
        return None
    if _oss_client is None:
        cfg = OSSConfig(
            access_key=CTYUN_CONFIG['access_key'],
            secret_key=CTYUN_CONFIG['secret_key'],
            endpoint=CTYUN_CONFIG['endpoint'],
            bucket=CTYUN_CONFIG['bucket'],
            region=CTYUN_CONFIG['region'],
            default_prefix=CTYUN_CONFIG['prefix'],
            external_host=CTYUN_CONFIG.get('external_host') or None,
            presign_expire=CTYUN_CONFIG['presign_expire'],
        )
        _oss_client = CTYunOSSClient(cfg)
    return _oss_client


def ensure_oss_manifest(task_id: str, result_dir: Path) -> Optional[Dict]:
    """
    确保任务结果已上传到天翼云 OSS，并返回 manifest

    ⚠️ 注意：
    - 正常情况下，上传动作应由 worker (`litserve_worker.py`) 完成
    - API 查询接口只应该“读取” manifest，而不是每次查询都触发上传
    - 因为历史原因，API 侧保留了一个兜底上传逻辑：当 worker 没有上传，
      且本地没有 `oss_manifest.json` 时，第一次调用会触发一次上传并生成 manifest，
      后续查询只会读取 manifest，不再重复上传

    manifest 结构：
    {
        "prefix": "tasks/<task_id>",
        "files": [
            {"relative_path": "...", "object_key": "...", "url": "...", "public_url": "...", "presign_url": "..."}
        ]
    }
    """
    client = get_oss_client()
    if not client:
        return None

    manifest_path = result_dir / 'oss_manifest.json'
    if manifest_path.exists():
        try:
            with open(manifest_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取 OSS manifest 失败，将重新生成: {e}")

    if not result_dir.exists():
        logger.warning(f"结果目录不存在，无法上传到 OSS: {result_dir}")
        return None

    # 收集所有文件（跳过 manifest 自身）
    files: List[Path] = [p for p in result_dir.rglob('*') if p.is_file() and p.name != 'oss_manifest.json']
    if not files:
        logger.info(f"结果目录为空，跳过上传: {result_dir}")
        return None

    prefix = f"{CTYUN_CONFIG['prefix'].rstrip('/')}/{task_id}"
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
    except Exception as e:
        logger.warning(f"写入 OSS manifest 失败: {e}")

    return manifest


def load_oss_manifest_if_exists(result_dir: Path) -> Optional[Dict]:
    """
    仅读取已存在的 OSS manifest，不做任何上传操作

    - 用于 API 查询接口，避免每次查询都触发上传
    """
    manifest_path = result_dir / 'oss_manifest.json'
    if not manifest_path.exists():
        return None

    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取 OSS manifest 失败: {e}")
        return None




def read_json_file(file_path: Path):
    """
    读取 JSON 文件

    Args:
        file_path: JSON 文件路径

    Returns:
        解析后的 JSON 数据，失败返回 None
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"读取 JSON 文件 {file_path} 失败: {e}")
        return None


def get_file_metadata(file_path: Path):
    """
    获取文件元数据

    Args:
        file_path: 文件路径

    Returns:
        包含文件元数据的字典
    """
    if not file_path.exists():
        return None

    stat = file_path.stat()
    return {
        'size': stat.st_size,
        'created_at': datetime.fromtimestamp(stat.st_ctime).isoformat(),
        'modified_at': datetime.fromtimestamp(stat.st_mtime).isoformat()
    }


def get_images_info(image_dir: Path):
    """
    获取图片目录信息

    Args:
        image_dir: 图片目录路径

    Returns:
        图片信息字典
    """
    if not image_dir.exists() or not image_dir.is_dir():
        return {
            'count': 0,
            'list': []
        }

    # 支持的图片格式
    image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}
    image_files = [f for f in image_dir.iterdir() if f.is_file() and f.suffix.lower() in image_extensions]

    images_list = []

    for img_file in sorted(image_files):
        img_info = {
            'name': img_file.name,
            'size': img_file.stat().st_size,
            'path': str(img_file.relative_to(image_dir.parent))
        }
        images_list.append(img_info)

    return {
        'count': len(images_list),
        'list': images_list
    }


@app.get("/", summary="服务信息", tags=["基础接口"])
async def root():
    """API根路径"""
    return {
        "service": "聚光 MinerU",
        "version": "1.0.0",
        "description": "聚光 MinerU - 企业级多GPU文档解析服务",
        "docs": "/docs"
    }


@app.post("/api/v1/tasks/submit", summary="提交任务", tags=["任务管理"])
async def submit_task(
    file: UploadFile = File(..., description="文档文件: PDF/图片(MinerU解析) 或 Office/HTML/文本等(MarkItDown解析)"),
    backend: str = Form('pipeline', description="处理后端: pipeline/vlm-transformers/vlm-vllm-engine"),
    lang: str = Form('ch', description="语言: ch/en/korean/japan等"),
    method: str = Form('auto', description="解析方法: auto/txt/ocr"),
    formula_enable: bool = Form(True, description="是否启用公式识别"),
    table_enable: bool = Form(True, description="是否启用表格识别"),
    priority: int = Form(0, description="优先级，数字越大越优先"),
):
    """
    提交文档解析任务
    
    立即返回 task_id，任务在后台异步处理
    """
    try:
        # 保存上传的文件到临时目录
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix)
        
        # 流式写入文件到磁盘，避免高内存使用
        while True:
            chunk = await file.read(1 << 23)  # 8MB chunks
            if not chunk:
                break
            temp_file.write(chunk)
        
        temp_file.close()
        
        # 创建任务
        task_id = db.create_task(
            file_name=file.filename,
            file_path=temp_file.name,
            backend=backend,
            options={
                'lang': lang,
                'method': method,
                'formula_enable': formula_enable,
                'table_enable': table_enable,
            },
            priority=priority
        )
        
        logger.info(f"✅ 任务已提交: {task_id} - {file.filename} (优先级: {priority})")
        
        return {
            'success': True,
            'task_id': task_id,
            'status': 'pending',
            'message': 'Task submitted successfully',
            'file_name': file.filename,
            'created_at': datetime.now().isoformat()
        }
    
    except Exception as e:
        logger.error(f"❌ 提交任务失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


def _load_task_data_fields(result_dir: Path, fields: list, include_metadata: bool = True):
    """
    根据字段列表加载任务数据
    
    Args:
        result_dir: 结果目录
        fields: 需要加载的字段列表
        include_metadata: 是否包含文件元数据
        
    Returns:
        包含数据的字典
    """
    data = {}
    
    # 1. 处理 Markdown 文件
    if 'md' in fields:
        md_files = list(result_dir.rglob('*.md'))
        # 排除带特殊后缀的 md 文件
        md_files = [f for f in md_files if not any(f.stem.endswith(suffix) for suffix in ['_layout', '_span', '_origin'])] 
        
        if md_files:
            md_file = md_files[0]
            logger.info(f"📄 读取 markdown 文件: {md_file}")
            
            with open(md_file, 'r', encoding='utf-8') as f:
                md_content = f.read()
            
            data['markdown'] = {
                'content': md_content,
                'file_name': md_file.name
            }
            
            if include_metadata:
                metadata = get_file_metadata(md_file)
                if metadata:
                    data['markdown']['metadata'] = metadata
    
    # 2. 处理 Content List JSON
    if 'content_list' in fields:
        content_list_files = list(result_dir.rglob('*_content_list.json'))
        if content_list_files:
            content_list_file = content_list_files[0]
            logger.info(f"📄 读取 content_list 文件: {content_list_file}")
            
            content_data = read_json_file(content_list_file)
            if content_data is not None:
                data['content_list'] = {
                    'content': content_data,
                    'file_name': content_list_file.name
                }
                
                if include_metadata:
                    metadata = get_file_metadata(content_list_file)
                    if metadata:
                        data['content_list']['metadata'] = metadata
    
    # 3. 处理 Middle JSON
    if 'middle_json' in fields:
        middle_json_files = list(result_dir.rglob('*_middle.json'))
        if middle_json_files:
            middle_json_file = middle_json_files[0]
            logger.info(f"📄 读取 middle json 文件: {middle_json_file}")
            
            middle_data = read_json_file(middle_json_file)
            if middle_data is not None:
                data['middle_json'] = {
                    'content': middle_data,
                    'file_name': middle_json_file.name
                }
                
                if include_metadata:
                    metadata = get_file_metadata(middle_json_file)
                    if metadata:
                        data['middle_json']['metadata'] = metadata
    
    # 4. 处理 Model Output JSON
    if 'model_output' in fields:
        model_output_files = list(result_dir.rglob('*_model.json'))
        if model_output_files:
            model_output_file = model_output_files[0]
            logger.info(f"📄 读取模型输出文件: {model_output_file}")
            
            model_data = read_json_file(model_output_file)
            if model_data is not None:
                data['model_output'] = {
                    'content': model_data,
                    'file_name': model_output_file.name
                }
                
                if include_metadata:
                    metadata = get_file_metadata(model_output_file)
                    if metadata:
                        data['model_output']['metadata'] = metadata
    
    # 5. 处理图片
    if 'images' in fields:
        image_dirs = list(result_dir.rglob('images'))
        if image_dirs:
            image_dir = image_dirs[0]
            logger.info(f"🖼️  获取图片信息目录: {image_dir}")
            
            images_info = get_images_info(image_dir)
            data['images'] = images_info
    
    # 6. 处理 Layout PDF
    if 'layout_pdf' in fields:
        layout_pdf_files = list(result_dir.rglob('*_layout.pdf'))
        if layout_pdf_files:
            layout_pdf_file = layout_pdf_files[0]
            data['layout_pdf'] = {
                'file_name': layout_pdf_file.name,
                'path': str(layout_pdf_file.relative_to(result_dir))
            }
            
            if include_metadata:
                metadata = get_file_metadata(layout_pdf_file)
                if metadata:
                    data['layout_pdf']['metadata'] = metadata
    
    # 7. 处理 Span PDF
    if 'span_pdf' in fields:
        span_pdf_files = list(result_dir.rglob('*_span.pdf'))
        if span_pdf_files:
            span_pdf_file = span_pdf_files[0]
            data['span_pdf'] = {
                'file_name': span_pdf_file.name,
                'path': str(span_pdf_file.relative_to(result_dir))
            }
            
            if include_metadata:
                metadata = get_file_metadata(span_pdf_file)
                if metadata:
                    data['span_pdf']['metadata'] = metadata
    
    # 8. 处理 Origin PDF
    if 'origin_pdf' in fields:
        origin_pdf_files = list(result_dir.rglob('*_origin.pdf'))
        if origin_pdf_files:
            origin_pdf_file = origin_pdf_files[0]
            data['origin_pdf'] = {
                'file_name': origin_pdf_file.name,
                'path': str(origin_pdf_file.relative_to(result_dir))
            }
            
            if include_metadata:
                metadata = get_file_metadata(origin_pdf_file)
                if metadata:
                    data['origin_pdf']['metadata'] = metadata
    
    return data


@app.get("/api/v1/tasks/{task_id}", summary="查询任务状态", tags=["任务管理"])
async def get_task_status(
    task_id: str,
    include_data: bool = Query(False, description="是否返回解析后的 markdown 内容（向后兼容参数，等同于 include_fields=md）"),
    include_fields: Optional[str] = Query(None, description="需要返回的字段，逗号分隔：md,content_list,middle_json,model_output,images,layout_pdf,span_pdf,origin_pdf。不传则只返回任务状态和资源链接"),
    include_metadata: bool = Query(True, description="是否包含文件元数据（仅当 include_fields 指定时有效）")
):
    """
    查询任务状态和详情
    
    功能说明：
    - 默认只返回任务状态和资源链接（assets字段），响应体小
    - 通过 include_fields 参数可以灵活选择需要返回的数据字段
    - include_data 参数为向后兼容，等同于 include_fields=md
    
    支持的字段：
    - md: Markdown 内容
    - content_list: 结构化内容列表 JSON
    - middle_json: 中间处理结果 JSON
    - model_output: 模型原始输出 JSON
    - images: 图片列表
    - layout_pdf, span_pdf, origin_pdf: PDF 文件信息
    """
    task = db.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    response = {
        'success': True,
        'task_id': task_id,
        'status': task['status'],
        'file_name': task['file_name'],
        'backend': task['backend'],
        'priority': task['priority'],
        'error_message': task['error_message'],
        'created_at': task['created_at'],
        'started_at': task['started_at'],
        'completed_at': task['completed_at'],
        'worker_id': task['worker_id'],
        'retry_count': task['retry_count']
    }
    logger.info(f"✅ 任务状态: {task['status']} - (result_path: {task['result_path']})")
    
    # 如果任务已完成，处理上传和（可选的）数据返回
    if task['status'] == 'completed':
        if not task['result_path']:
            response['message'] = 'Task completed but result files have been cleaned up (older than retention period)'
            return response
        
        result_dir = Path(task['result_path'])
        logger.info(f"📂 正在检查结果目录: {result_dir}")
        
        if result_dir.exists():
            logger.info(f"✅ 结果目录存在")
            
            def _pick_local(glob_pattern: str):
                files = list(result_dir.rglob(glob_pattern))
                return files[0] if files else None

            def _url_from_manifest(manifest: dict, suffixes):
                for item in manifest.get('files', []):
                    rel = item.get('relative_path', '')
                    if any(rel.endswith(suf) for suf in suffixes):
                        return item.get('public_url') or item.get('presign_url') or item.get('url')
                return None

            # 优先只“读取” worker 生成的 OSS manifest，避免查询接口触发上传
            manifest = load_oss_manifest_if_exists(result_dir)
            if manifest:
                logger.info(f"✅ 任务 {task_id} 读取到已有 OSS manifest，共 {len(manifest.get('files', []))} 个文件")
            else:
                logger.info(f"ℹ️  任务 {task_id} 没有找到 OSS manifest，将仅返回本地路径资源")

            # 构建前端需要的核心直链（优先用 OSS 链接，退化为本地路径）
            assets = {}

            # origin pdf (只返回原始 PDF，不返回 layout/span 等)
            pdf_url = None
            if manifest:
                # 优先匹配 _origin.pdf
                pdf_url = _url_from_manifest(manifest, ['_origin.pdf'])
                # 如果没有 _origin.pdf，尝试匹配普通 .pdf（排除 layout/span）
                if not pdf_url:
                    for item in manifest.get('files', []):
                        rel = item.get('relative_path', '')
                        if rel.endswith('.pdf') and not any(rel.endswith(suffix) for suffix in ['_layout.pdf', '_span.pdf', '_origin.pdf']):
                            pdf_url = item.get('public_url') or item.get('presign_url') or item.get('url')
                            break
            if not pdf_url:
                # 本地文件查找：优先 _origin.pdf，然后普通 PDF（排除 layout/span）
                local_pdf = _pick_local('*_origin.pdf')
                if not local_pdf:
                    all_pdfs = list(result_dir.rglob('*.pdf'))
                    # 排除 layout、span，保留 origin 和普通 PDF
                    local_pdf = next((f for f in all_pdfs if not any(f.stem.endswith(suffix) for suffix in ['_layout', '_span'])), None)
                if local_pdf:
                    pdf_url = str(local_pdf)
            if pdf_url:
                assets['pdf_url'] = pdf_url

            # content_list
            content_list_url = None
            if manifest:
                content_list_url = _url_from_manifest(manifest, ['_content_list.json'])
            if not content_list_url:
                local_cl = _pick_local('*_content_list.json')
                if local_cl:
                    content_list_url = str(local_cl)
            if content_list_url:
                assets['content_list_url'] = content_list_url

            # full markdown
            full_md_link = None
            if manifest:
                full_md_link = _url_from_manifest(manifest, ['.md'])
            if not full_md_link:
                local_md = _pick_local('*.md')
                if local_md:
                    full_md_link = str(local_md)
            if full_md_link:
                assets['full_md_link'] = full_md_link

            # zip (若存在)
            full_zip_url = None
            if manifest:
                full_zip_url = _url_from_manifest(manifest, ['.zip'])
            if not full_zip_url:
                local_zip = _pick_local('*.zip')
                if local_zip:
                    full_zip_url = str(local_zip)
            if full_zip_url:
                assets['full_zip_url'] = full_zip_url

            if assets:
                response['assets'] = assets

            # 根据参数决定是否加载数据内容
            fields_to_load = []
            
            # 处理向后兼容参数 include_data
            if include_data:
                fields_to_load.append('md')
            
            # 处理 include_fields 参数
            if include_fields:
                fields_to_load.extend([f.strip() for f in include_fields.split(',')])
            
            # 去重
            fields_to_load = list(set(fields_to_load))
            
            # 如果有字段需要加载，则加载数据
            if fields_to_load:
                logger.info(f"📦 正在获取任务 {task_id} 的数据，包含字段: {fields_to_load}")
                try:
                    data = _load_task_data_fields(result_dir, fields_to_load, include_metadata)
                    if data:
                        response['data'] = data
                        logger.info(f"✅ 成功获取任务 {task_id} 的数据")
                    else:
                        logger.warning(f"⚠️  未找到任何数据文件")
                except Exception as e:
                    logger.error(f"❌ 获取任务 {task_id} 的数据失败: {e}")
                    logger.exception(e)
                    response['data'] = None
        else:
            logger.error(f"❌ 结果目录不存在: {result_dir}")
    elif task['status'] == 'completed':
        logger.warning(f"⚠️  任务已完成但 result_path 为空")
    else:
        logger.info(f"ℹ️  任务状态为 {task['status']}，跳过内容加载")
    
    return response


@app.delete("/api/v1/tasks/{task_id}", summary="取消任务", tags=["任务管理"])
async def cancel_task(task_id: str):
    """
    取消任务（仅限 pending 状态）
    """
    task = db.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task['status'] == 'pending':
        db.update_task_status(task_id, 'cancelled')
        
        # 删除临时文件
        file_path = Path(task['file_path'])
        if file_path.exists():
            file_path.unlink()
        
        logger.info(f"⏹️  任务已取消: {task_id}")
        return {
            'success': True,
            'message': 'Task cancelled successfully'
        }
    else:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot cancel task in {task['status']} status"
        )


@app.get("/api/v1/queue/stats", summary="队列统计", tags=["队列管理"])
async def get_queue_stats():
    """
    获取队列统计信息
    """
    stats = db.get_queue_stats()
    
    return {
        'success': True,
        'stats': stats,
        'total': sum(stats.values()),
        'timestamp': datetime.now().isoformat()
    }


@app.get("/api/v1/queue/tasks", summary="任务列表", tags=["队列管理"])
async def list_tasks(
    status: Optional[str] = Query(None, description="筛选状态: pending/processing/completed/failed"),
    limit: int = Query(100, description="返回数量限制", le=1000)
):
    """
    获取任务列表
    """
    if status:
        tasks = db.get_tasks_by_status(status, limit)
    else:
        # 返回所有任务（需要修改 TaskDB 添加这个方法）
        with db.get_cursor() as cursor:
            cursor.execute('''
                SELECT * FROM tasks 
                ORDER BY created_at DESC 
                LIMIT ?
            ''', (limit,))
            tasks = [dict(row) for row in cursor.fetchall()]
    
    return {
        'success': True,
        'count': len(tasks),
        'tasks': tasks
    }


@app.post("/api/v1/admin/cleanup", summary="清理旧任务", tags=["管理接口"])
async def cleanup_old_tasks(days: Optional[int] = Query(
    None,
    description="清理N天前的任务；不传则清理全部任务（含pending/processing）"
)):
    """
    清理旧任务记录（管理接口）
    """
    deleted_count = db.cleanup_old_tasks(days)
    
    logger.info(f"🧹 已清理 {deleted_count} 条旧任务记录")
    
    return {
        'success': True,
        'deleted_count': deleted_count,
        'message': f'Cleaned up tasks older than {days} days'
    }


@app.post("/api/v1/admin/reset-stale", summary="重置超时任务", tags=["管理接口"])
async def reset_stale_tasks(timeout_minutes: int = Query(60, description="超时时间（分钟）")):
    """
    重置超时的 processing 任务（管理接口）
    """
    reset_count = db.reset_stale_tasks(timeout_minutes)
    
    logger.info(f"🔄 已重置 {reset_count} 个超时任务")
    
    return {
        'success': True,
        'reset_count': reset_count,
        'message': f'Reset tasks processing for more than {timeout_minutes} minutes'
    }


@app.get("/api/v1/health", summary="健康检查", tags=["监控接口"])
async def health_check():
    """
    健康检查接口
    """
    try:
        # 检查数据库连接
        stats = db.get_queue_stats()
        
        return {
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'database': 'connected',
            'queue_stats': stats
        }
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        return JSONResponse(
            status_code=503,
            content={
                'status': 'unhealthy',
                'error': str(e)
            }
        )


if __name__ == '__main__':
    # 从环境变量读取端口，默认为39020
    api_port = int(os.getenv('API_PORT', '39020'))
    
    logger.info("🚀 启动聚光 MinerU API Server...")
    logger.info(f"📖 API 文档: http://localhost:{api_port}/docs")
    
    uvicorn.run(
        app, 
        host='0.0.0.0', 
        port=api_port,
        log_level='info'
    )

