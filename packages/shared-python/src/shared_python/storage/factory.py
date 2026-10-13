from shared_python.storage.local import LocalStorageBackend


def build_storage_backend(settings):
    """The backend `STORAGE_BACKEND` names, wrapped in encryption when a key is set."""
    if settings.storage_backend == "local":
        backend = LocalStorageBackend(settings.upload_root_path)
    elif settings.storage_backend == "s3":
        from shared_python.storage.s3 import S3StorageBackend

        backend = S3StorageBackend(
            bucket=getattr(settings, "storage_s3_bucket", None) or "",
            prefix=getattr(settings, "storage_s3_prefix", "") or "",
            endpoint_url=getattr(settings, "storage_s3_endpoint_url", None),
            region=getattr(settings, "storage_s3_region", None),
            access_key_id=getattr(settings, "storage_s3_access_key_id", None),
            secret_access_key=getattr(settings, "storage_s3_secret_access_key", None),
        )
    else:
        raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
    key = getattr(settings, "storage_encryption_key", None)
    if key:
        from shared_python.storage.encrypted import EncryptedStorageBackend, load_key

        return EncryptedStorageBackend(backend, load_key(key))
    return backend
