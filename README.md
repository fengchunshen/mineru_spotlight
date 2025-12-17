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
- ✅ **图片上传** - 支持将解析图片上传到MinIO对象存储

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

浏览器访问：`http://localhost:39020/docs`

## API 接口文档

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

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | String | 是 | 任务ID（路径参数） |
| upload_images | Boolean | 否 | 是否上传图片到MinIO并替换链接，默认：`false` |

**响应示例：**

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
  "data": {
    "markdown_file": "document.md",
    "content": "# 文档内容...",
    "images_uploaded": false,
    "has_images": true
  }
}
```

**状态说明：**
- `pending` - 等待处理
- `processing` - 处理中
- `completed` - 已完成
- `failed` - 处理失败
- `cancelled` - 已取消

**cURL示例：**

```bash
# 查询任务状态
curl http://localhost:39020/api/v1/tasks/{task_id}

# 查询并上传图片到MinIO
curl http://localhost:39020/api/v1/tasks/{task_id}?upload_images=true
```

---

### 3. 获取任务完整数据

**接口地址：** `GET /api/v1/tasks/{task_id}/data`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| task_id | String | 是 | 任务ID（路径参数） |
| include_fields | String | 否 | 需要返回的字段，逗号分隔：`md,content_list,middle_json,model_output,images,layout_pdf,span_pdf,origin_pdf`，默认：`md,content_list,middle_json,model_output,images` |
| upload_images | Boolean | 否 | 是否上传图片到MinIO并返回URL，默认：`false` |
| include_metadata | Boolean | 否 | 是否包含文件元数据，默认：`true` |

**响应示例：**

```json
{
  "success": true,
  "task_id": "xxx-xxx-xxx",
  "status": "completed",
  "file_name": "document.pdf",
  "backend": "pipeline",
  "created_at": "2024-01-01T00:00:00",
  "completed_at": "2024-01-01T00:00:30",
  "data": {
    "markdown": {
      "content": "# 文档内容...",
      "file_name": "document.md"
    },
    "content_list": [...],
    "middle_json": {...},
    "model_output": {...},
    "images": {
      "count": 5,
      "list": [...],
      "uploaded_to_minio": false
    }
  }
}
```

**字段说明：**
- `md` - Markdown内容
- `content_list` - 结构化内容列表JSON
- `middle_json` - 中间处理结果JSON
- `model_output` - 模型原始输出JSON
- `images` - 图片列表
- `layout_pdf` - 布局PDF文件
- `span_pdf` - Span PDF文件
- `origin_pdf` - 原始PDF文件

**cURL示例：**

```bash
curl http://localhost:39020/api/v1/tasks/{task_id}/data?include_fields=md,images&upload_images=true
```

---

### 4. 取消任务

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

### 5. 队列统计

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

### 6. 任务列表

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

### 7. 健康检查

**接口地址：** `GET /api/v1/health`

**响应示例：**

```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T00:00:00"
}
```

**cURL示例：**

```bash
curl http://localhost:39020/api/v1/health
```

---

### 8. 管理接口

#### 8.1 清理旧任务

**接口地址：** `POST /api/v1/admin/cleanup`

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| days | Integer | 否 | 清理N天前的任务，默认：`7` |

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
curl -X POST http://localhost:39020/api/v1/admin/cleanup?days=7
```

#### 8.2 重置超时任务

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
  --output-dir PATH                 输出目录 (默认: /tmp/mineru_tianshu_output)
  --api-port PORT                   API端口 (默认: 39020)
  --worker-port PORT                Worker端口 (默认: 39021)
  --accelerator TYPE                加速器类型: auto/cuda/cpu/mps (默认: auto)
  --workers-per-device N            每个GPU的worker数 (默认: 1)
  --devices DEVICES                 使用的GPU设备 (默认: auto，使用所有GPU)
  --poll-interval SECONDS           Worker拉取任务间隔 (默认: 0.5秒)
  --enable-scheduler                启用可选的任务调度器 (默认: 不启动)
  --monitor-interval SECONDS        调度器监控间隔 (默认: 300秒=5分钟)
  --cleanup-old-files-days N        清理N天前的结果文件 (默认: 7天, 0=禁用)
```

### MinIO配置（可选）

如需使用图片上传到MinIO功能，设置以下环境变量：

```bash
export MINIO_ENDPOINT="your-endpoint.com"
export MINIO_ACCESS_KEY="your-access-key"
export MINIO_SECRET_KEY="your-secret-key"
export MINIO_BUCKET="your-bucket"
```

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
    response = requests.get(f'http://localhost:39020/api/v1/tasks/{task_id}')
    result = response.json()
    
    if result['status'] == 'completed':
        if result.get('data'):
            content = result['data']['content']
            print(f"解析完成，内容长度: {len(content)} 字符")
            # 保存结果
            with open('output.md', 'w', encoding='utf-8') as f:
                f.write(content)
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
- **存储**: SQLite (并发安全) + MinIO (可选)
- **日志**: Loguru

---

## 许可证

遵循 MinerU 主项目许可证
