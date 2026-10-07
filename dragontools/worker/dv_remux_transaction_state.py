"""Run-local install/rollback ownership for a direct Dolby Vision remux."""
from __future__ import annotations

from dataclasses import dataclass, field

from ..core.sidecar_transaction import SidecarCommitTransaction


@dataclass
class DVRemuxTransactionState:
    input_path: str
    output_path: str | None = None
    staging_output_path: str | None = None
    complete: bool = False
    video_committed: bool = False
    preserved_output: bool = False
    output_verified: bool = False
    staged_sidecars: list[str] = field(default_factory=list)
    sidecar_transaction: SidecarCommitTransaction | None = None

    @property
    def needs_cleanup(self) -> bool:
        return not (self.video_committed or self.preserved_output)
