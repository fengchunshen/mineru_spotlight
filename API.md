# 聚光 MinerU API 接口文档

## 目录

- [接口概览](#接口概览)
- [基础接口](#基础接口)
- [任务管理接口](#任务管理接口)
- [队列管理接口](#队列管理接口)
- [管理接口](#管理接口)
- [监控接口](#监控接口)

---

## 接口概览

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

**Base URL:** `http://localhost:39020` (默认端口)

**API文档:** `http://localhost:39020/docs` (Swagger UI)

---

## 基础接口

### GET / - 服务信息

获取服务基本信息。

**请求示例：**

```bash
curl http://localhost:39020/
```

**响应示例：**

```json
{
  "service": "聚光 MinerU",
  "version": "1.0.0",
  "description": "聚光 MinerU - 企业级多GPU文档解析服务",
  "docs": "/docs"
}
```

---

## 任务管理接口

### POST /api/v1/tasks/submit - 提交任务

提交文档解析任务，立即返回 task_id，任务在后台异步处理。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| file | File | 是 | 文档文件（支持PDF、图片、Office、HTML、文本等） |
| backend | String | 否 | 处理后端：`pipeline`(默认) / `vlm-transformers` / `vlm-vllm-engine` |
| lang | String | 否 | 语言：`ch`(默认) / `en` / `korean` / `japan` 等 |
| method | String | 否 | 解析方法：`auto`(默认) / `txt` / `ocr` |
| formula_enable | Boolean | 否 | 是否启用公式识别，默认：`true` |
| table_enable | Boolean | 否 | 是否启用表格识别，默认：`true` |
| priority | Integer | 否 | 优先级，数字越大越优先，默认：`0` |

**请求示例：**

```bash
curl -X POST http://localhost:39020/api/v1/tasks/submit \
  -F "file=@document.pdf" \
  -F "backend=pipeline" \
  -F "lang=ch" \
  -F "method=auto" \
  -F "formula_enable=true" \
  -F "table_enable=true" \
  -F "priority=0"
```

**响应示例：**

```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "pending",
  "message": "Task submitted successfully",
  "file_name": "document.pdf",
  "created_at": "2024-01-01T00:00:00"
}
```

---

### GET /api/v1/tasks/{task_id} - 查询任务状态

查询任务状态和详情。支持灵活选择需要返回的数据字段。

**功能说明：**
- 默认只返回任务状态和资源链接（assets字段），响应体小，适合轮询
- 通过 `include_fields` 参数可以灵活选择需要返回的数据字段
- `include_data` 参数为向后兼容，等同于 `include_fields=md`

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | String | 任务ID |

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
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

**请求示例：**

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

**响应示例（仅查询状态）：**

```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
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
    "pdf_url": "https://oss.example.com/tasks/{task_id}/document_origin.pdf",
    "content_list_url": "https://oss.example.com/tasks/{task_id}/document_content_list.json",
    "full_md_link": "https://oss.example.com/tasks/{task_id}/document.md",
    "full_zip_url": "https://oss.example.com/tasks/{task_id}/document.zip"
  }
}
```

**响应示例（包含数据字段）：**

```json
{
  "success": true,
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
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
    "pdf_url": "https://oss.example.com/tasks/{task_id}/document_origin.pdf",
    "content_list_url": "https://oss.example.com/tasks/{task_id}/document_content_list.json",
    "full_md_link": "https://oss.example.com/tasks/{task_id}/document.md",
    "full_zip_url": "https://oss.example.com/tasks/{task_id}/document.zip"
  },
  "data": {
    "markdown": {
      "content": "# 文档内容...",
      "file_name": "document.md",
      "metadata": {
        "size": 1024,
        "created_at": "2024-01-01T00:00:30",
        "modified_at": "2024-01-01T00:00:30"
      }
    },
    "content_list": {
      "content": [...],
      "file_name": "document_content_list.json"
    },
    "images": {
      "count": 5,
      "list": [
        {
          "name": "image_001.png",
          "size": 102400,
          "path": "images/image_001.png"
        }
      ]
    }
  }
}
```

**响应字段说明：**

- `status` - 任务状态：
  - `pending` - 等待处理
  - `processing` - 处理中
  - `completed` - 已完成
  - `failed` - 处理失败
  - `cancelled` - 已取消
- `assets` - 任务完成后的资源链接（优先返回OSS链接，无OSS时返回本地路径）：
  - `pdf_url` - 原始PDF文件链接
  - `content_list_url` - 结构化内容列表JSON链接
  - `full_md_link` - Markdown文件链接
  - `full_zip_url` - 完整结果压缩包链接（如果存在）
- `data` - 仅在指定 `include_fields` 或 `include_data=true` 时返回，包含解析后的数据内容

---

### DELETE /api/v1/tasks/{task_id} - 取消任务

取消任务（仅限 `pending` 状态的任务）。

**路径参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| task_id | String | 任务ID |

**请求示例：**

```bash
curl -X DELETE http://localhost:39020/api/v1/tasks/{task_id}
```

**响应示例：**

```json
{
  "success": true,
  "message": "Task cancelled successfully"
}
```

**错误响应：**

```json
{
  "detail": "Cannot cancel task in processing status"
}
```

---

## 队列管理接口

### GET /api/v1/queue/stats - 队列统计

获取队列统计信息，包括各状态任务的数量。

**请求示例：**

```bash
curl http://localhost:39020/api/v1/queue/stats
```

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

---

### GET /api/v1/queue/tasks - 任务列表

获取任务列表，支持按状态筛选。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| status | String | 否 | 筛选状态：`pending` / `processing` / `completed` / `failed` |
| limit | Integer | 否 | 返回数量限制，最大1000，默认：`100` |

**请求示例：**

```bash
# 获取所有任务（最多100条）
curl http://localhost:39020/api/v1/queue/tasks

# 获取待处理任务（最多20条）
curl http://localhost:39020/api/v1/queue/tasks?status=pending&limit=20

# 获取已完成任务（最多50条）
curl http://localhost:39020/api/v1/queue/tasks?status=completed&limit=50
```

**响应示例：**

```json
{
  "success": true,
  "count": 10,
  "tasks": [
    {
      "task_id": "550e8400-e29b-41d4-a716-446655440000",
      "file_name": "document.pdf",
      "status": "completed",
      "backend": "pipeline",
      "priority": 0,
      "created_at": "2024-01-01T00:00:00",
      "completed_at": "2024-01-01T00:00:30"
    }
  ]
}
```

---

## 管理接口

### POST /api/v1/admin/cleanup - 清理旧任务

清理旧任务记录（管理接口）。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| days | Integer | 否 | 清理N天前的任务；不传则清理全部任务（含pending/processing） |

**请求示例：**

```bash
# 清理7天前的任务
curl -X POST http://localhost:39020/api/v1/admin/cleanup?days=7

# 清理全部任务
curl -X POST http://localhost:39020/api/v1/admin/cleanup
```

**响应示例：**

```json
{
  "success": true,
  "deleted_count": 50,
  "message": "Cleaned up tasks older than 7 days"
}
```

---

### POST /api/v1/admin/reset-stale - 重置超时任务

重置超时的 `processing` 任务为 `pending` 状态（管理接口）。

**查询参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| timeout_minutes | Integer | 否 | 超时时间（分钟），默认：`60` |

**请求示例：**

```bash
curl -X POST http://localhost:39020/api/v1/admin/reset-stale?timeout_minutes=60
```

**响应示例：**

```json
{
  "success": true,
  "reset_count": 2,
  "message": "Reset tasks processing for more than 60 minutes"
}
```

---

## 监控接口

### GET /api/v1/health - 健康检查

检查服务健康状态和数据库连接。

**请求示例：**

```bash
curl http://localhost:39020/api/v1/health
```

**响应示例（健康）：**

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

**响应示例（不健康）：**

```json
{
  "status": "unhealthy",
  "error": "Database connection failed"
}
```

---

## 错误码说明

| HTTP状态码 | 说明 |
|-----------|------|
| 200 | 请求成功 |
| 400 | 请求参数错误 |
| 404 | 资源不存在（如任务不存在） |
| 500 | 服务器内部错误 |
| 503 | 服务不可用（健康检查失败） |

---

## 使用示例

### Python示例

```python
import requests
import time

# 1. 提交任务
with open('document.pdf', 'rb') as f:
    response = requests.post(
        'http://localhost:39020/api/v1/tasks/submit',
        files={'file': f},
        data={
            'lang': 'ch',
            'priority': 0,
            'formula_enable': True,
            'table_enable': True
        }
    )
    result = response.json()
    task_id = result['task_id']
    print(f"任务已提交: {task_id}")

# 2. 轮询等待完成
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

### JavaScript示例

```javascript
// 提交任务
const formData = new FormData();
formData.append('file', fileInput.files[0]);
formData.append('lang', 'ch');
formData.append('priority', '0');

const submitResponse = await fetch('http://localhost:39020/api/v1/tasks/submit', {
  method: 'POST',
  body: formData
});

const { task_id } = await submitResponse.json();

// 轮询查询状态
const pollStatus = async () => {
  const response = await fetch(
    `http://localhost:39020/api/v1/tasks/${task_id}?include_data=true`
  );
  const result = await response.json();
  
  if (result.status === 'completed') {
    // 如果使用 include_data=true，数据在 result.data.markdown.content
    if (result.data && result.data.markdown) {
      console.log('任务完成:', result.data.markdown.content);
    }
    return result;
  } else if (result.status === 'failed') {
    console.error('任务失败:', result.error_message);
    return null;
  }
  
  // 继续轮询
  setTimeout(pollStatus, 2000);
};

pollStatus();
```

---

## 注意事项

1. **任务状态**：任务提交后立即返回 `task_id`，状态为 `pending`，需要轮询查询状态
2. **数据返回**：`GET /api/v1/tasks/{task_id}` 默认只返回任务状态和资源链接（响应体小，适合轮询）。需要数据内容时，使用 `include_data=true` 或 `include_fields` 参数灵活选择字段
3. **OSS支持**：如果配置了天翼云OSS，任务完成后会自动上传结果文件，API优先返回OSS链接，无OSS时返回本地路径
4. **文件清理**：系统会自动清理旧的结果文件，但保留数据库记录
5. **优先级**：数字越大优先级越高，可用于紧急任务处理
6. **并发限制**：系统会根据GPU数量和worker配置自动调度任务

