from shared_python.storage.local import LocalStorageBackend


# The factory stays config-driven so S3/Azure implementations can slot in later without changing callers.
def build_storage_backend(settings):
    if settings.storage_backend == "local":
        return LocalStorageBackend(settings.upload_root_path)
    raise ValueError(f"Unsupported storage backend: {settings.storage_backend}")
