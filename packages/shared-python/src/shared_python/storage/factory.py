from shared_python.storage.local import LocalStorageBackend


# The factory stays config-driven so S3/Azure implementations can slot in later without changing callers.
def build_storage_backend(settings):
    if settings.storage_backend == "local":
        backend = LocalStorageBackend(settings.upload_root_path)
    else:
        raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
    key = getattr(settings, "storage_encryption_key", None)
    if key:
        from shared_python.storage.encrypted import EncryptedStorageBackend, load_key

        return EncryptedStorageBackend(backend, load_key(key))
    return backend
