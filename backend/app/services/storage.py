"""Dataset file storage abstraction.

* ``local``    – files under STORAGE_DIR (Docker volume in Compose). Not durable on hosts with
                 ephemeral disks (most free PaaS tiers).
* ``database`` – files in the ``stored_files`` table. Durable on managed Postgres; suitable only for
                 the small files a public demo allows (MAX_UPLOAD_MB).

Stored files are immutable: every version (including remediation outputs) gets a new key, so the
original upload is never overwritten.
"""

from __future__ import annotations

import io
import shutil
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import models as m


class Storage:
    def __init__(self) -> None:
        self._cache: OrderedDict[str, pd.DataFrame] = OrderedDict()
        self._lock = threading.Lock()

    @property
    def backend(self) -> str:
        return get_settings().storage_backend

    def _root(self) -> Path:
        root = Path(get_settings().storage_dir).resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _local_path(self, key: str) -> Path:
        root = self._root()
        p = (root / key).resolve()
        if root not in p.parents:
            raise ValueError("invalid storage key")
        return p

    def put(self, db: Session, workspace_id: int, key: str, src: Path) -> int:
        size = src.stat().st_size
        if self.backend == "database":
            db.merge(m.StoredFile(key=key, workspace_id=workspace_id, content=src.read_bytes(), size_bytes=size))
            db.flush()
        else:
            dst = self._local_path(key)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        return size

    def put_frame(self, db: Session, workspace_id: int, key: str, df: pd.DataFrame) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "data.parquet"
            df.to_parquet(p, index=False)
            return self.put(db, workspace_id, key, p)

    @contextmanager
    def local_copy(self, db: Session, key: str) -> Iterator[Path]:
        if self.backend == "database":
            row = db.get(m.StoredFile, key)
            if row is None:
                raise FileNotFoundError(key)
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / Path(key).name
                p.write_bytes(row.content)
                yield p
        else:
            p = self._local_path(key)
            if not p.exists():
                raise FileNotFoundError(key)
            yield p

    def read_frame(self, db: Session, key: str) -> pd.DataFrame:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key].copy()
        if self.backend == "database":
            row = db.get(m.StoredFile, key)
            if row is None:
                raise FileNotFoundError(key)
            df = pd.read_parquet(io.BytesIO(row.content))
        else:
            df = pd.read_parquet(self._local_path(key))
        with self._lock:
            self._cache[key] = df
            while len(self._cache) > 8:
                self._cache.popitem(last=False)
        return df.copy()

    def delete_workspace(self, db: Session, workspace_id: int) -> None:
        if self.backend == "database":
            db.execute(delete(m.StoredFile).where(m.StoredFile.workspace_id == workspace_id))
        else:
            shutil.rmtree(self._root() / f"ws{workspace_id}", ignore_errors=True)
        with self._lock:
            for k in [k for k in self._cache if k.startswith(f"ws{workspace_id}/")]:
                del self._cache[k]


storage = Storage()
