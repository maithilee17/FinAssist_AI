"""Private filesystem storage with traversal checks and recoverable deletion."""

import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile


class UploadTooLargeError(ValueError):
    pass


class EmptyUploadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DeleteTicket:
    original: Path
    quarantine: Path | None


class PrivateDocumentStorage:
    def __init__(self, root: Path, max_size_bytes: int, read_chunk_bytes: int) -> None:
        self.root = root.resolve()
        self.max_size_bytes = max_size_bytes
        self.read_chunk_bytes = read_chunk_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self.trash_dir = (self.root / ".trash").resolve()
        self.trash_dir.mkdir(parents=True, exist_ok=True)

    def relative_path(self, user_id: UUID, document_id: UUID) -> str:
        return f"{user_id}/{document_id}.pdf"

    def resolve(self, relative_path: str) -> Path:
        candidate = (self.root / relative_path).resolve()
        if candidate == self.root or self.root not in candidate.parents:
            raise ValueError("Stored document path escapes the private storage root")
        return candidate

    async def save_upload(self, upload: UploadFile, relative_path: str) -> int:
        destination = self.resolve(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        partial = destination.with_suffix(f"{destination.suffix}.{uuid4().hex}.part")
        total = 0
        try:
            with partial.open("xb") as output:
                while chunk := await upload.read(self.read_chunk_bytes):
                    total += len(chunk)
                    if total > self.max_size_bytes:
                        raise UploadTooLargeError(
                            f"PDF exceeds the {self.max_size_bytes // (1024 * 1024)} MB limit"
                        )
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if total == 0:
                raise EmptyUploadError("The uploaded file is empty")
            os.replace(partial, destination)
            return total
        except Exception:
            partial.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

    def remove(self, relative_path: str) -> None:
        self.resolve(relative_path).unlink(missing_ok=True)

    def prepare_delete(self, relative_path: str) -> DeleteTicket:
        original = self.resolve(relative_path)
        if not original.exists():
            return DeleteTicket(original=original, quarantine=None)
        quarantine = (self.trash_dir / f"{uuid4()}.pdf.deleting").resolve()
        if self.root not in quarantine.parents:
            raise ValueError("Quarantine path escapes the private storage root")
        os.replace(original, quarantine)
        return DeleteTicket(original=original, quarantine=quarantine)

    @staticmethod
    def restore_delete(ticket: DeleteTicket) -> None:
        if ticket.quarantine and ticket.quarantine.exists():
            ticket.original.parent.mkdir(parents=True, exist_ok=True)
            os.replace(ticket.quarantine, ticket.original)

    @staticmethod
    def finalize_delete(ticket: DeleteTicket) -> bool:
        if not ticket.quarantine:
            return True
        try:
            ticket.quarantine.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def cleanup_quarantine(self) -> int:
        removed = 0
        for candidate in self.trash_dir.glob("*.deleting"):
            try:
                candidate.unlink()
                removed += 1
            except OSError:
                continue
        return removed
