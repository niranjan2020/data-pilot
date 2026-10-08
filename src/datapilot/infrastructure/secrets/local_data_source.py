"""Local encrypted datasource credentials, stored outside the metadata catalog.

The encryption key and ciphertext are both local deployment files; this protects
against accidental metadata exposure, not compromise of the API host.
Use a managed secret vault for hosted production.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from cryptography.fernet import Fernet


class LocalDataSourceSecretStore:
    def __init__(self, directory: str = "/app/data/secrets") -> None:
        self.directory = Path(directory)

    def _key(self) -> bytes:
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = self.directory / "datasource.key"
        if not path.exists():
            try:
                with path.open("xb") as stream:
                    stream.write(Fernet.generate_key())
                os.chmod(path, 0o600)
            except FileExistsError:
                pass
        return path.read_bytes()

    def _path(self, source_id: int) -> Path:
        if source_id < 1:
            raise ValueError("Invalid datasource identifier")
        return self.directory / f"datasource-{source_id}.enc"

    def put(self, source_id: int, password: str) -> None:
        encrypted = Fernet(self._key()).encrypt(json.dumps({"password": password}).encode())
        target = self._path(source_id)
        temporary = target.with_suffix(".tmp")
        with temporary.open("wb") as stream:
            stream.write(encrypted)
        os.chmod(temporary, 0o600)
        temporary.replace(target)

    def resolve_for_runtime(self, source_id: int) -> str | None:
        path = self._path(source_id)
        if not path.exists():
            return None
        return json.loads(Fernet(self._key()).decrypt(path.read_bytes()))["password"]
