# 聚光平台 MinerU

企业级多GPU文档解析服务，支持PDF、图片、Office文档等多种格式的智能解析。

## 核心功能

### 文档解析
- **PDF和图片解析** (.pdf, .png, .jpg, .jpeg, .bmp, .tiff, .webp) - 使用 MinerU GPU加速解析
- **Office文档解析** (.docx, .doc, .xlsx, .xls, .pptx, .ppt) - 使用 MarkItDown 快速解析
- **网页和文本解析** (.html, .htm, .txt, .md, .csv, .json, .xml等) - 使用 MarkItDown 解析

### 系统特性
- ✅ **异步处理** - 客户端立即响应，任务后台处理
- ✅ **任务持久化** - SQLite存储，服务重启任务不丢失
- ✅ **优先级队列** - 支持任务优先级设置
- ✅ **GPU负载均衡** - LitServe自动调度，多GPU并发处理
- ✅ **自动清理** - 定期清理旧结果文件，保留数据库记录

## 快速开始

### 安装依赖

```bash
pip install -r requirements.txt
```

### 启动服务

```bash
# 一键启动所有服务
python start_all.py

# 自定义配置
python start_all.py --workers-per-device 2 --devices 0,1
```

### 访问API文档

- **Swagger UI**: `http://localhost:39020/docs` (交互式API文档)
- **详细文档**: 查看 [API.md](./API.md) 获取完整的接口文档和使用示例

## API 接口文档

> 📖 **完整文档**: 详细的API接口文档请查看 [API.md](./API.md)

### 接口概览

| 分类 | 方法 | 路径 | 说明 |
|------|------|------|------|
| 基础 | GET | `/` | 服务信息 |
| 任务 | POST | `/api/v1/tasks/submit` | 提交任务 |
| 任务 | GET | `/api/v1/tasks/{task_id}` | 查询任务状态（支持灵活获取数据） |
| 任务 | DELETE | `/api/v1/tasks/{task_id}` | 取消任务 |
| 队列 | GET | `/api/v1/queue/stats` | 队列统计 |
| 队列 | GET | `/api/v1/queue/tasks` | 任务列表 |
| 管理 | POST | `/api/v1/admin/cleanup` | 清理旧任务 |
| 管理 | POST | `/api/v1/admin/reset-stale` | 重置超时任务 |
| 监控 | GET | `/api/v1/health` | 健康检查 |

---

### 0. 服务信息

**接口地址：** `GET /`

**说明：** 获取服务基本信息

**响应示例：**

```json
{
  "service": "聚光 MinerU",
  "version": "1.0.0",
  "description": "聚光 MinerU - 企业级多GPU文档解析服务",
  "docs": "/docs"
}
```

**cURL示例：**

```bash
curl http://localhost:39020/
```

---

### 1. 提交任务

**接口地址：** `POST /api/v1/tasks/submit`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 文档文件 |
| backend | String | 否 | 处理后端：`pipeline`(默认) / `vlm-transformers` / `vlm-vllm-engine` |
| lang | String | 否 | 语言：`ch`(默认) / `en` / `korean` / `japan` 等 |
| method | String | 否 | 解析方法：`auto`(默认) / `txt` / `ocr` |
| formula_enable | Boolean | 否 | 是否启用公式识别，默认：`true` |
| table_enable | Boolean | 否 | 是否启用表格识别，默认：`true` |
| priority | Integer | 否 | 优先级，数字越大越优先，默认：`0` |

**响应示例：**

```json
{
  "success": true,
  "task_id": "xxx-xxx-xxx",
  "status": "pending",
  "message": "Task submitted successfully",
  "file_name": "document.pdf",
  "created_at": "2024-01-01T00:00:00"
}
```

**cURL示例：**

```bash
curl -X POST http://localhost:39020/api/v1/tasks/submit \
  -F "file=@document.pdf" \
  -F "lang=ch" \
  -F "priority=0"
```

---

### 2. 查询任务状态

**接口地址：** `GET /api/v1/tasks/{task_id}`

**功能说明：**
- 默认只返回任务状态和资源链接（assets字段），响应体小，适合轮询
- 通过 `include_fields` 参数可以灵活选择需要返回的数据字段
- `include_data` 参数为向后兼容，等同于 `include_fields=md`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | String | 是 | 任务ID（路径参数） |
| include_data | Boolean | 否 | 是否返回解析后的 markdown 内容（向后兼容参数，等同于 include_fields=md），默认：`false` |
| include_fields | String | 否 | 需要返回的字段，逗号分隔：`md,content_list,middle_json,model_output,images,layout_pdf,span_pdf,origin_pdf`。不传则只返回任务状态和资源链接 |
| include_metadata | Boolean | 否 | 是否包含文件元数据（仅当 include_fields 指定时有效），默认：`true` |

**支持的字段：**
- `md` - Markdown 内容
- `content_list` - 结构化内容列表 JSON
- `middle_json` - 中间处理结果 JSON
- `model_output` - 模型原始输出 JSON
- `images` - 图片列表
- `layout_pdf` - 布局 PDF 文件
- `span_pdf` - Span PDF 文件
- `origin_pdf` - 原始 PDF 文件

**响应示例（仅查询状态）：**

```json
{
  "success": true,
  "task_id": "xxx-xxx-xxx",
  "status": "completed",
  "file_name": "document.pdf",
  "backend": "pipeline",
  "priority": 0,
  "error_message": null,
  "created_at": "2024-01-01T00:00:00",
  "started_at": "2024-01-01T00:00:01",
  "completed_at": "2024-01-01T00:00:30",
  "worker_id": "worker-1",
  "retry_count": 0,
  "assets": {
    "pdf_url": "https://...",
    "content_list_url": "https://...",
    "full_md_link": "https://...",
    "full_zip_url": "https://..."
  }
}
```

**响应示例（包含数据字段）：**

```json
{
  "success": true,
  "task_id": "xxx-xxx-xxx",
  "status": "completed",
  "file_name": "document.pdf",
  "backend": "pipeline",
  "priority": 0,
  "error_message": null,
  "created_at": "2024-01-01T00:00:00",
  "started_at": "2024-01-01T00:00:01",
  "completed_at": "2024-01-01T00:00:30",
  "worker_id": "worker-1",
  "retry_count": 0,
  "assets": {
    "pdf_url": "https://...",
    "content_list_url": "https://...",
    "full_md_link": "https://...",
    "full_zip_url": "https://..."
  },
  "data": {
    "markdown": {
      "content": "# 文档内容...",
      "file_name": "document.md"
    },
    "content_list": [...],
    "images": {
      "count": 5,
      "list": [...]
    }
  }
}
```

**状态说明：**
- `pending` - 等待处理
- `processing` - 处理中
- `completed` - 已完成
- `failed` - 处理失败
- `cancelled` - 已取消

**响应字段说明：**
- `assets` - 任务完成后的资源链接（优先返回OSS链接，无OSS时返回本地路径）
  - `pdf_url` - 原始PDF文件链接
  - `content_list_url` - 结构化内容列表JSON链接
  - `full_md_link` - Markdown文件链接
  - `full_zip_url` - 完整结果压缩包链接（如果存在）
- `data` - 仅在指定 `include_fields` 或 `include_data=true` 时返回，包含解析后的数据内容

**cURL示例：**

```bash
# 仅查询状态（不返回内容，响应体小）
curl http://localhost:39020/api/v1/tasks/{task_id}

# 返回Markdown内容（向后兼容方式）
curl http://localhost:39020/api/v1/tasks/{task_id}?include_data=true

# 灵活选择返回的字段
curl http://localhost:39020/api/v1/tasks/{task_id}?include_fields=md,images

# 获取所有字段
curl http://localhost:39020/api/v1/tasks/{task_id}?include_fields=md,content_list,middle_json,model_output,images,layout_pdf,span_pdf,origin_pdf
```

---

### 3. 取消任务

**接口地址：** `DELETE /api/v1/tasks/{task_id}`

**说明：** 只能取消 `pending` 状态的任务

**响应示例：**

```json
{
  "success": true,
  "message": "Task cancelled successfully"
}
```

**cURL示例：**

```bash
curl -X DELETE http://localhost:39020/api/v1/tasks/{task_id}
```

---

### 4. 队列统计

**接口地址：** `GET /api/v1/queue/stats`

**响应示例：**

```json
{
  "success": true,
  "stats": {
    "pending": 5,
    "processing": 2,
    "completed": 100,
    "failed": 3,
    "cancelled": 1
  },
  "total": 111,
  "timestamp": "2024-01-01T00:00:00"
}
```

**cURL示例：**

```bash
curl http://localhost:39020/api/v1/queue/stats
```

---

### 5. 任务列表

**接口地址：** `GET /api/v1/queue/tasks`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | String | 否 | 筛选状态：`pending` / `processing` / `completed` / `failed` |
| limit | Integer | 否 | 返回数量限制，最大1000，默认：`100` |

**响应示例：**

```json
{
  "success": true,
  "count": 10,
  "tasks": [...]
}
```

**cURL示例：**

```bash
# 获取所有任务
curl http://localhost:39020/api/v1/queue/tasks?limit=50

# 获取待处理任务
curl http://localhost:39020/api/v1/queue/tasks?status=pending&limit=20
```

---

### 6. 健康检查

**接口地址：** `GET /api/v1/health`

**说明：** 检查服务健康状态和数据库连接

**响应示例：**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00",
  "database": "connected",
  "queue_stats": {
    "pending": 5,
    "processing": 2,
    "completed": 100,
    "failed": 3,
    "cancelled": 1
  }
}
```

**cURL示例：**

```bash
curl http://localhost:39020/api/v1/health
```

---

### 7. 管理接口

#### 7.1 清理旧任务

**接口地址：** `POST /api/v1/admin/cleanup`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| days | Integer | 否 | 清理N天前的任务；不传则清理全部任务（含pending/processing） |

**响应示例：**

```json
{
  "success": true,
  "deleted_count": 50,
  "message": "Cleaned up tasks older than 7 days"
}
```

**cURL示例：**

```bash
# 清理7天前的任务
curl -X POST http://localhost:39020/api/v1/admin/cleanup?days=7

# 清理全部任务
curl -X POST http://localhost:39020/api/v1/admin/cleanup
```

#### 7.2 重置超时任务

**接口地址：** `POST /api/v1/admin/reset-stale`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| timeout_minutes | Integer | 否 | 超时时间（分钟），默认：`60` |

**说明：** 将超时的 `processing` 任务重置为 `pending` 状态

**响应示例：**

```json
{
  "success": true,
  "reset_count": 2,
  "message": "Reset tasks processing for more than 60 minutes"
}
```

**cURL示例：**

```bash
curl -X POST http://localhost:39020/api/v1/admin/reset-stale?timeout_minutes=60
```

---

## 配置说明

### 启动参数

```bash
python start_all.py [选项]

选项:
  --output-dir PATH                 输出目录 (默认: /tmp/mineru_spotlight_output)
  --api-port PORT                   API端口 (默认: 39020)
  --worker-port PORT                Worker端口 (默认: 39021)
  --accelerator TYPE                加速器类型: auto/cuda/cpu/mps (默认: auto)
  --workers-per-device N            每个GPU的worker数 (默认: 1)
  --devices DEVICES                 使用的GPU设备，逗号分隔 (默认: auto，使用所有GPU)
```

### 对象存储配置（可选）

#### 天翼云OSS配置

系统支持将任务结果自动上传到天翼云OSS，设置以下环境变量：

```bash
export CTYUN_ACCESS_KEY="your-access-key"
export CTYUN_SECRET_KEY="your-secret-key"
export CTYUN_ENDPOINT="https://shanghai-9.zos.ctyun.cn"
export CTYUN_BUCKET="your-bucket"
export CTYUN_REGION="cn"
export CTYUN_PREFIX="tasks"
export CTYUN_EXTERNAL_HOST="https://your-domain.com"  # 可选，用于生成公网访问链接
export CTYUN_PRESIGN_EXPIRE=86400  # 预签名URL过期时间（秒），默认24小时
```

**说明：**
- 任务完成后，Worker会自动将结果文件上传到OSS
- API查询接口会优先返回OSS链接，无OSS配置时返回本地路径
- OSS manifest文件保存在结果目录的 `oss_manifest.json` 中

---

## 使用示例

### Python示例

```python
import requests
import time

# 提交任务
with open('document.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:39020/api/v1/tasks/submit',
        files={'file': f},
        data={'lang': 'ch', 'priority': 0}
    )
    task_id = response.json()['task_id']
    print(f"任务已提交: {task_id}")

# 轮询等待完成
while True:
    response = requests.get(
        f'http://localhost:39020/api/v1/tasks/{task_id}',
        params={'include_data': False}  # 轮询时不返回内容，响应体小
    )
    result = response.json()
    
    if result['status'] == 'completed':
        # 获取完整数据
        data_response = requests.get(
            f'http://localhost:39020/api/v1/tasks/{task_id}',
            params={'include_fields': 'md,images'}  # 灵活选择需要的字段
        )
        data = data_response.json()
        
        # 保存Markdown
        if 'markdown' in data.get('data', {}):
            content = data['data']['markdown']['content']
            with open('output.md', 'w', encoding='utf-8') as f:
                f.write(content)
            print("解析完成，结果已保存")
        break
    elif result['status'] == 'failed':
        print(f"失败: {result['error_message']}")
        break
    
    print(f"处理中... 状态: {result['status']}")
    time.sleep(2)
```

---

## 技术栈

- **Web框架**: FastAPI + Uvicorn
- **解析器**: MinerU (PDF/图片) + MarkItDown (Office/文本/HTML等)
- **GPU调度**: LitServe (自动负载均衡)
- **存储**: SQLite (并发安全) + 天翼云OSS (可选)
- **日志**: Loguru

---

## 许可证

遵循 MinerU 主项目许可证
