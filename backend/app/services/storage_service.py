import hashlib
import json
import os
import shutil
from pathlib import Path

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
        if value and value.strip():
            return value.strip()
    return None


def bucket_name() -> str | None:
    return _env(
        "AWS_S3_BUCKET_NAME",  # Railway CLI / credentials output
        "AWS_BUCKET_NAME",
        "S3_BUCKET_NAME",
        "BUCKET_NAME",
        "RAILWAY_BUCKET_NAME",
        "BUCKET",             # Railway reference variables
    )


def access_key_id() -> str | None:
    return _env(
        "AWS_ACCESS_KEY_ID",
        "S3_ACCESS_KEY_ID",
        "BUCKET_ACCESS_KEY_ID",
        "BUCKET_ACCESS_KEY",
        "ACCESS_KEY_ID",       # Railway reference variables
    )


def secret_access_key() -> str | None:
    return _env(
        "AWS_SECRET_ACCESS_KEY",
        "S3_SECRET_ACCESS_KEY",
        "BUCKET_SECRET_ACCESS_KEY",
        "BUCKET_SECRET_KEY",
        "SECRET_ACCESS_KEY",   # Railway reference variables
    )


def endpoint_url() -> str | None:
    return _env(
        "AWS_ENDPOINT_URL",
        "S3_ENDPOINT",
        "S3_ENDPOINT_URL",
        "BUCKET_ENDPOINT",
        "ENDPOINT",            # Railway reference variables
    )


def region_name() -> str:
    return _env(
        "AWS_DEFAULT_REGION",
        "AWS_REGION",
        "S3_REGION",
        "BUCKET_REGION",
        "REGION",              # Railway reference variables
    ) or "auto"


def url_style() -> str:
    style = (_env("AWS_S3_URL_STYLE", "S3_URL_STYLE", "BUCKET_URL_STYLE") or "virtual").lower()
    return style if style in {"virtual", "path", "auto"} else "virtual"


def storage_enabled() -> bool:
    return bool(bucket_name() and access_key_id() and secret_access_key() and endpoint_url())


def storage_config_status() -> dict:
    missing = []
    if not bucket_name():
        missing.append("BUCKET/AWS_S3_BUCKET_NAME")
    if not access_key_id():
        missing.append("ACCESS_KEY_ID/AWS_ACCESS_KEY_ID")
    if not secret_access_key():
        missing.append("SECRET_ACCESS_KEY/AWS_SECRET_ACCESS_KEY")
    if not endpoint_url():
        missing.append("ENDPOINT/AWS_ENDPOINT_URL")
    return {
        "enabled": not missing,
        "bucket_name": bucket_name(),
        "endpoint_configured": bool(endpoint_url()),
        "region": region_name(),
        "url_style": url_style(),
        "missing_variables": missing,
    }


def get_s3_client():
    if not storage_enabled():
        missing = ", ".join(storage_config_status()["missing_variables"])
        raise RuntimeError(f"Faltan variables del Bucket de Railway: {missing}")

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url(),
        aws_access_key_id=access_key_id(),
        aws_secret_access_key=secret_access_key(),
        region_name=region_name(),
        config=Config(
            signature_version="s3v4",
            s3={"addressing_style": url_style()},
            retries={"max_attempts": 4, "mode": "standard"},
        ),
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


def upload_file(local_path: str | Path, object_key: str, content_type: str = "application/pdf") -> str:
    local_path = Path(local_path)
    if not local_path.exists() or local_path.stat().st_size <= 0:
        raise RuntimeError("El archivo temporal no existe o está vacío")

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
        ExtraArgs={"ContentType": content_type or "application/octet-stream"},
    )

    # Verifica que Railway haya recibido realmente el objeto antes de guardar en DB.
    metadata = client.head_object(Bucket=bucket, Key=object_key)
    remote_size = int(metadata.get("ContentLength", 0))
    if remote_size != local_path.stat().st_size:
        raise RuntimeError(
            f"La verificación del Bucket falló: local={local_path.stat().st_size} bytes, remoto={remote_size} bytes"
        )

    storage_path = f"s3://{bucket}/{object_key}"
    shutil.copy2(local_path, _cache_path(storage_path))
    return storage_path


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


def list_objects(prefix: str = "") -> list[dict]:
    """Lista todos los objetos del Bucket bajo un prefijo, con paginación."""
    if not storage_enabled():
        return []
    client = get_s3_client()
    bucket = bucket_name()
    paginator = client.get_paginator("list_objects_v2")
    objects: list[dict] = []
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []) or []:
            key = str(item.get("Key") or "")
            if not key or key.endswith("/"):
                continue
            objects.append({
                "key": key,
                "size": int(item.get("Size") or 0),
                "last_modified": item.get("LastModified"),
                "etag": str(item.get("ETag") or "").strip('\"'),
            })
    return objects


def put_json(object_key: str, payload: dict) -> str | None:
    """Guarda metadatos JSON al lado del PDF para poder reconstruir la BD."""
    if not storage_enabled():
        return None
    client = get_s3_client()
    bucket = bucket_name()
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    client.put_object(
        Bucket=bucket,
        Key=object_key,
        Body=body,
        ContentType="application/json; charset=utf-8",
    )
    return f"s3://{bucket}/{object_key}"


def get_json(object_key: str) -> dict | None:
    """Lee un JSON del Bucket; devuelve None si no existe o es inválido."""
    if not storage_enabled():
        return None
    try:
        response = get_s3_client().get_object(Bucket=bucket_name(), Key=object_key)
        raw = response["Body"].read()
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except Exception:
        return None
