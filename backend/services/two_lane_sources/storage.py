from __future__ import annotations

from services.pdf_scan.storage import PdfScanArtifactStore


class TwoLaneArtifactStore(PdfScanArtifactStore):
    def delete_run_prefix(self, run_id: str) -> int:
        return self.delete_prefix(prefix=self.run_prefix(run_id))
