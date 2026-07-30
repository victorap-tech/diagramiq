import hashlib
import os
import shutil
from pathlib import Path
from typing import BinaryIO

import boto3
from botocore.config import Config

BASE_DIR = Path(__file__).resolve().parents[2]
LOCAL_UPLOAD_DIR = BASE_DIR / "uploads" / "documents"
CACHE_DIR = Path(os.getenv("DIAGRAMIQ_CACHE_DIR", "/tmp/diagramiq-cache"))
LOCAL_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _env(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def bucket_name() -> str | None:
    return _env("AWS_BUCKET_NAME", "S3_BUCKET_NAME", "BUCKET_NAME", "RAILWAY_BUCKET_NAME")


def storage_enabled() -> bool:
    return bool(
        bucket_name()
        and _env("AWS_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID")
        and _env("AWS_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY")
        and _env("AWS_ENDPOINT_URL", "S3_ENDPOINT", "S3_ENDPOINT_URL")
    )


def get_s3_client():
    endpoint = _env("AWS_ENDPOINT_URL", "S3_ENDPOINT", "S3_ENDPOINT_URL")
    access_key = _env("AWS_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID")
    secret_key = _env("AWS_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY")
    region = _env("AWS_DEFAULT_REGION", "AWS_REGION", "S3_REGION") or "us-east-1"
    if not (endpoint and access_key and secret_key and bucket_name()):
        raise RuntimeError("Faltan las credenciales del Bucket de Railway")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


def is_s3_path(value: str | Path) -> bool:
    return str(value).startswith("s3://")


def parse_s3_path(value: str | Path) -> tuple[str, str]:
    raw = str(value)
    if not raw.startswith("s3://"):
        raise ValueError("La ruta no pertenece al Bucket")
    remainder = raw[5:]
    bucket, key = remainder.split("/", 1)
    return bucket, key


def upload_file(local_path: str | Path, object_key: str) -> str:
    local_path = Path(local_path)
    if not storage_enabled():
        destination = LOCAL_UPLOAD_DIR / Path(object_key).name
        if local_path.resolve() != destination.resolve():
            shutil.copy2(local_path, destination)
        return str(destination)

    client = get_s3_client()
    bucket = bucket_name()
    client.upload_file(
        str(local_path),
        bucket,
        object_key,
        ExtraArgs={"ContentType": "application/pdf"},
    )
    cache_path = _cache_path(f"s3://{bucket}/{object_key}")
    shutil.copy2(local_path, cache_path)
    return f"s3://{bucket}/{object_key}"


def _cache_path(storage_path: str | Path) -> Path:
    digest = hashlib.sha256(str(storage_path).encode("utf-8")).hexdigest()
    return CACHE_DIR / f"{digest}.pdf"


def resolve_local_file(storage_path: str | Path) -> Path:
    raw = str(storage_path)
    if not is_s3_path(raw):
        path = Path(raw)
        if not path.is_absolute():
            path = BASE_DIR / path
        return path

    cached = _cache_path(raw)
    if cached.exists() and cached.stat().st_size > 0:
        return cached

    bucket, key = parse_s3_path(raw)
    get_s3_client().download_file(bucket, key, str(cached))
    return cached


def get_object_stream(storage_path: str | Path):
    bucket, key = parse_s3_path(storage_path)
    response = get_s3_client().get_object(Bucket=bucket, Key=key)
    return response["Body"], response.get("ContentLength")


def delete_file(storage_path: str | Path) -> None:
    raw = str(storage_path)
    if is_s3_path(raw):
        bucket, key = parse_s3_path(raw)
        get_s3_client().delete_object(Bucket=bucket, Key=key)
        cached = _cache_path(raw)
        if cached.exists():
            cached.unlink()
        return

    path = Path(raw)
    if not path.is_absolute():
        path = BASE_DIR / path
    if path.exists():
        path.unlink()
