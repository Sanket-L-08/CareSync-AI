"""Private encrypted object storage. Files are AES-256-GCM encrypted by the app before upload,
and S3 server-side encryption (KMS when configured) is also requested. Buckets must block public access."""
import uuid
from pathlib import Path
from .config import get_settings
from .crypto import encrypt_bytes, decrypt_bytes


class Storage:
    def put(self, key: str, data: bytes) -> None: ...
    def get(self, key: str) -> bytes: ...
    def delete(self, key: str) -> None: ...


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root not in p.parents:
            raise ValueError("Invalid object key")
        return p

    def put(self, key, data):
        p = self._path(key); p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)

    def get(self, key):
        return self._path(key).read_bytes()

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)


class S3Storage(Storage):
    def __init__(self):
        import boto3
        s = get_settings()
        self.bucket, self.kms = s.s3_bucket, s.s3_kms_key_id
        self.client = boto3.client("s3", endpoint_url=s.s3_endpoint, region_name=s.s3_region)

    def put(self, key, data):
        extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": self.kms} if self.kms else {"ServerSideEncryption": "AES256"}
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType="application/octet-stream", **extra)

    def get(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key):
        self.client.delete_object(Bucket=self.bucket, Key=key)


_storage: Storage | None = None


def storage() -> Storage:
    global _storage
    if _storage is None:
        s = get_settings()
        _storage = S3Storage() if s.storage_backend == "s3" else LocalStorage(s.local_storage_dir)
    return _storage


def new_key(patient_id: int) -> str:
    return f"patients/{patient_id}/{uuid.uuid4().hex}.bin"


def put_encrypted(key: str, data: bytes) -> None:
    storage().put(key, encrypt_bytes(data, aad=key.encode()))


def get_decrypted(key: str) -> bytes:
    return decrypt_bytes(storage().get(key), aad=key.encode())
