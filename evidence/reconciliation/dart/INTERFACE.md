# DART Collection Adapter Interface (Developer B)

- **Module:** `proofops.adapters.dart`
- **Status:** Implementation verified against Developer B requirements with 46 passing unit/defense tests, ruff clean, and mypy clean
- **Date:** 2026-09-21

---

## 1. Overview

`proofops.adapters.dart` provides bounded, content-addressed, secure collection of corporate disclosures from the official OpenDART API and corporate integrated reports.

Key design principles:
1. **Zero Live Credential Leaks:** API keys (`crtfc_key`) are stripped/redacted from all logs, URLs, repr strings, and exception messages.
2. **Injectable Transport:** Pure standard library HTTP transport with dependency injection for deterministic offline unit and integration testing without network calls.
3. **Exact Wire Provenance:** `DartResponse` preserves exact unaltered response bytes (`raw_bytes`) as received over the wire. No re-serialization is needed or performed when writing to content-addressed storage.
4. **Strict Pinned Receipt & Field Validation:** `get_financial_statements` accepts an optional `expected_rcept_no` and strictly validates that every returned row contains required fields (`corp_code`, `bsns_year`, `reprt_code`, `rcept_no`) matching requested parameters and pinned receipt. Per official OpenDART specification (DS003/2019020), `fs_div` is a request-binding parameter and not required in response rows; if echoed, it must match.
5. **Lossless Financial Normalization:** Normalizes currency amounts to Decimal strings without floating-point precision loss. Float inputs are rejected explicitly to defend against IEEE-754 precision corruption.
6. **Immutable Content-Addressed Storage:** `ArtifactStore` saves raw bytes indexed by SHA256 (`<root>/<sha256[:2]>/<sha256>`).
7. **Defensive Processing:** Zip-slip, zip-bomb (max files, max size, decompression ratio), and XML entity expansion (XXE/billion laughs) defenses.
8. **Collection Manifest Compliance:** Produces companion manifests conforming strictly to `collection_manifest.schema.json` (version `collection-1`).

---

## 2. Public API Signatures

### 2.1 `DartResponse`
```python
from collections.abc import Mapping
from typing import Any, Iterator


class DartResponse(Mapping[str, Any]):
  """Immutable representation of an OpenDART response preserving wire bytes and parsed data."""

  @property
  def status_code(self) -> int:
    ...

  @property
  def headers(self) -> dict[str, str]:
    ...

  @property
  def raw_bytes(self) -> bytes:
    """Exact raw response bytes as received over the wire."""
    ...

  @property
  def data(self) -> dict[str, Any]:
    ...

  @property
  def endpoint(self) -> str:
    ...

  @property
  def rcept_no(self) -> str | None:
    ...

  def __getitem__(self, key: str) -> Any:
    ...

  def __iter__(self) -> Iterator[str]:
    ...

  def __len__(self) -> int:
    ...

  def get(self, key: str, default: Any = None) -> Any:
    ...
```

### 2.2 `DartClient`
```python
from typing import Any, Protocol


class Transport(Protocol):

  def __call__(
      self,
      url: str,
      headers: dict[str, str] | None = None,
      timeout: float = 10.0,
  ) -> tuple[int, dict[str, str], bytes]:
    """Execute HTTP GET request and return (status_code, headers, body_bytes)."""
    ...


class DartClient:

  def __init__(
      self,
      api_key: str = "",
      *,
      transport: Transport | None = None,
      base_url: str = "https://opendart.fss.or.kr",
      timeout: float = 10.0,
      max_retries: int = 3,
      retry_backoff: float = 0.5,
  ) -> None:
    """Initialize DART API client.

    If api_key is omitted or empty, environment variable DART_API_KEY is read.
    """
    ...

  def list_filings(
      self,
      corp_code: str,
      bgn_de: str,
      end_de: str,
      *,
      pblntf_ty: str | None = None,
      pblntf_detail_ty: str | None = None,
      last_reprt_at: str = "Y",
      page_no: int = 1,
      page_count: int = 100,
  ) -> DartResponse:
    """Search disclosure filings (/api/list.json).

    Returns DartResponse mapping with 'status', 'message', 'list', etc.
    """
    ...

  def get_financial_statements(
      self,
      corp_code: str,
      bsns_year: int | str,
      reprt_code: str = "11011",
      fs_div: str = "CFS",
      *,
      expected_rcept_no: str | None = None,
  ) -> DartResponse:
    """Retrieve full single company financial statements (/api/fnlttSinglAcntAll.json).

    reprt_code: 11011 (사업보고서), 11012 (반기), 11013 (1분기), 11014 (3분기).
    fs_div: CFS (연결재무제표), OFS (재무제표/개별).

    If expected_rcept_no is provided, strictly validates that every returned
    row matches expected_rcept_no, corp_code, bsns_year, and reprt_code
    (and matches fs_div if echoed in the row).
    """
    ...

  def download_xbrl(self, rcept_no: str, reprt_code: str = "11011") -> bytes:
    """Download XBRL financial statement zip package (/api/fnlttXbrl.xml).

    Returns raw zip bytes. Raises DartError if DART returns error XML.
    """
    ...

  def download_document(self, rcept_no: str) -> bytes:
    """Download disclosure document original zip package (/api/document.xml).

    Returns raw zip bytes. Raises DartError if DART returns error XML.
    """
    ...
```

### 2.3 `ArtifactStore`
```python
from pathlib import Path


class ArtifactStore:

  def __init__(self, root: str | Path) -> None:
    """Initialize content-addressed immutable artifact store."""
    ...

  def store(self, content: bytes, *, ext: str = "") -> str:
    """Save content bytes atomically under its SHA256 hex digest.

    Returns 64-character lowercase sha256 hex digest.
    """
    ...

  def get(self, sha256: str, *, ext: str = "") -> bytes:
    """Retrieve raw bytes for sha256.

    Raises FileNotFoundError if absent, ValueError if hash mismatch.
    """
    ...

  def has(self, sha256: str, *, ext: str = "") -> bool:
    """Check whether artifact exists in store."""
    ...

  def path_for(self, sha256: str, *, ext: str = "") -> Path:
    """Get expected filesystem path for sha256."""
    ...

  def extract_zip_safe(
      self,
      zip_bytes: bytes,
      target_dir: str | Path,
      *,
      max_files: int = 1000,
      max_total_size: int = 50 * 1024 * 1024,
      max_single_size: int = 20 * 1024 * 1024,
  ) -> list[Path]:
    """Extract zip bytes safely with traversal, symlink, and zip-bomb protections.

    Returns list of extracted relative paths.
    """
    ...
```

### 2.4 `Collection Manifest Builder`
```python
def create_artifact_entry(
    source_id: str,
    document_version_id: str,
    corp_code: str,
    fy: int,
    *,
    artifact_sha256: str | None = None,
    rcept_no: str | None = None,
    consolidation: str = "consolidated",  # 'consolidated' | 'separate' | 'unknown'
    source_system: str = "DART",  # 'DART' | 'integrated_report'
    locator: str | None = None,
    status: str = "retrieved",  # 'retrieved' | 'not_available' | 'failed'
    error_code: str | None = None,
    fetched_at: str | None = None,  # UTC ISO-8601 string, auto-generated if None
) -> dict[str, Any]:
  """Create a single artifact entry adhering strictly to collection_manifest.schema.json."""
  ...


def build_collection_manifest(
    manifest_id: str,
    package_id: str,
    artifacts: list[dict[str, Any]],
    *,
    synthetic: bool = False,
    fetched_at: str | None = None,
) -> dict[str, Any]:
  """Construct a top-level collection manifest conforming to collection_manifest.schema.json."""
  ...
```

### 2.5 `Normalization`
```python
def normalize_financial_amount(
    raw_value: str | int | None,
    *,
    currency: str = "KRW",
    unit_raw: str = "",
) -> dict[str, Any]:
  """Normalize financial currency amount to Decimal string without float precision loss.

  Rejects float inputs with ValueError to prevent silent IEEE-754 precision corruption.

  Returns: {
      'raw': str,
      'normalized': str | None,  # e.g. '10000000000'
      'unit': str,
      'currency': str,
      'kind': 'currency_amount'
  }
  """
  ...


def normalize_entity_set(entities: list[str]) -> dict[str, Any]:
  """Normalize entity names/IDs into deterministic sorted JSON string.

  Returns: {
      'raw': str,
      'normalized': str,  # e.g. '[\"A\",\"B\"]'
      'kind': 'entity_set',
      'unit': 'entity'
  }
  """
  ...


def normalize_period(
    period_start: str,
    period_end: str,
) -> dict[str, Any]:
  """Normalize date range to YYYY-MM-DD/YYYY-MM-DD.

  Returns: {
      'raw': str,
      'normalized': str,  # e.g. '2024-01-01/2024-12-31'
      'kind': 'period'
  }
  """
  ...
```

---

## 3. Verified Example Usage

```python
from pathlib import Path
from proofops.adapters.dart import (
    ArtifactStore,
    DartClient,
    build_collection_manifest,
    create_artifact_entry,
    normalize_financial_amount,
)

# 1. Initialize store and client (mock transport for testing)
store = ArtifactStore(Path("data/artifacts"))
client = DartClient(api_key="mock_key", transport=my_mock_transport)

# 2. Query statements with pinned receipt validation
response = client.get_financial_statements(
    corp_code="00126380",  # 삼성전자
    bsns_year=2024,
    reprt_code="11011",
    fs_div="CFS",
    expected_rcept_no="20250314000123",
)

# 3. Store raw wire bytes content-addressed (exact provenance preserved, zero reserialization)
sha256 = store.store(response.raw_bytes, ext=".json")

# 4. Create collection manifest entry
entry = create_artifact_entry(
    source_id="dart-fs-2024",
    document_version_id="fs-v1",
    corp_code="00126380",
    fy=2024,
    rcept_no=response.rcept_no,
    artifact_sha256=sha256,
    consolidation="consolidated",
    source_system="DART",
    locator="fnlttSinglAcntAll/CFS",
    status="retrieved",
)

manifest = build_collection_manifest(
    manifest_id="manifest-samsung-2024",
    package_id="pkg-samsung-2024",
    artifacts=[entry],
    synthetic=False,
)
```
