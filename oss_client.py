"""
轻量版天翼云对象存储客户端封装

说明：
- 使用 boto3 的 S3 兼容接口，设置 path-style 访问和合适的超时/重试参数
- 提供简单上传、批量上传目录、生成限时签名 URL、构造外网 URL
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import boto3
from botocore.config import Config as BotoConfig
from botocore.exceptions import BotoCoreError, ClientError


@dataclass
class OSSConfig:
    access_key: str
    secret_key: str
    endpoint: str
    bucket: str
    region: str = "cn"
    default_prefix: str = "tasks"
    external_host: Optional[str] = None
    timeout: int = 300
    max_retries: int = 3
    presign_expire: int = 24 * 3600  # 24h


class CTYunOSSClient:
    """天翼云 OSS 客户端（S3 兼容）"""

    def __init__(self, cfg: OSSConfig):
        self.cfg = cfg
        # 减少 boto3 在元数据服务上的探测开销
        os.environ.setdefault("AWS_METADATA_SERVICE_TIMEOUT", "5")
        os.environ.setdefault("AWS_METADATA_SERVICE_NUM_ATTEMPTS", "2")

        self._client = boto3.client(
            "s3",
            aws_access_key_id=cfg.access_key,
            aws_secret_access_key=cfg.secret_key,
            endpoint_url=cfg.endpoint,
            config=BotoConfig(
                region_name=cfg.region,
                connect_timeout=cfg.timeout,
                read_timeout=cfg.timeout,
                retries={"max_attempts": cfg.max_retries},
                signature_version="s3",
                s3={"addressing_style": "path"},
            ),
            verify=True,
        )

    def _object_key(self, key: str) -> str:
        key = key.lstrip("/")
        return key

    def upload_file(self, local_path: Path, object_key: str) -> str:
        """上传单个文件，返回对象键，默认设为公共读"""
        try:
            self._client.upload_file(
                Filename=str(local_path),
                Bucket=self.cfg.bucket,
                Key=self._object_key(object_key),
                ExtraArgs={"ACL": "public-read"},
            )
            return object_key
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"上传失败: {local_path} -> {object_key}, {exc}") from exc

    def upload_files(
        self, base_dir: Path, file_list: Iterable[Path], prefix: str
    ) -> List[Dict[str, str]]:
        """
        批量上传文件，返回字典列表 [{local_path, object_key}]
        """
        results: List[Dict[str, str]] = []
        for path in file_list:
            rel = path.relative_to(base_dir)
            object_key = f"{prefix.rstrip('/')}/{rel.as_posix()}"
            self.upload_file(path, object_key)
            results.append({"local_path": str(path), "object_key": object_key})
        return results

    def presign_url(self, object_key: str, expires_in: Optional[int] = None) -> str:
        """生成限时签名 URL"""
        expire = expires_in or self.cfg.presign_expire
        try:
            return self._client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": self.cfg.bucket, "Key": self._object_key(object_key)},
                ExpiresIn=expire,
            )
        except (ClientError, BotoCoreError) as exc:
            raise RuntimeError(f"生成签名URL失败: {object_key}, {exc}") from exc

    def public_url(self, object_key: str) -> Optional[str]:
        """构造外网访问 URL（若配置了 external_host 则返回）"""
        if not self.cfg.external_host:
            return None
        host = self.cfg.external_host.rstrip("/")
        return f"{host}/{self._object_key(object_key)}"


