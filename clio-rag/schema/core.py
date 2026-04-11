"""
Trelagers index-schema för clio-rag (ADD v1.0 §4).

Lager 1: CorePayload     — gemensamma fält för alla content-typer
Lager 2: LocationPayload — lazy loading-adresser (cloud / local)
Lager 3: BookExt         — bokspecifika fält (payload.ext)
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
import uuid


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ContentType(str, Enum):
    BOOK    = "book"
    NCC     = "ncc"
    AUDIO   = "audio"
    IMAGE   = "image"
    VIDEO   = "video"
    EMAIL   = "email"
    FINANCE = "finance"
    ARTIFACT = "artifact"


class Sensitivity(str, Enum):
    PUBLIC       = "public"
    INTERNAL     = "internal"
    CONFIDENTIAL = "confidential"


class StorageTier(str, Enum):
    CLOUD = "cloud"
    LOCAL = "local"
    BOTH  = "both"


class CopyrightStatus(str, Enum):
    PUBLIC_DOMAIN = "public_domain"
    PERSONAL_USE  = "personal_use"
    LICENSED      = "licensed"
    UNKNOWN       = "unknown"


class AccessOrigin(str, Enum):
    SELF_CREATED    = "self_created"
    PURCHASED       = "purchased"
    RENTED          = "rented"
    THIRD_PARTY_RAG = "third_party_rag"
    BORROWED        = "borrowed"
    PUBLIC_DOMAIN   = "public_domain"


# ---------------------------------------------------------------------------
# Lager 1: Core
# ---------------------------------------------------------------------------

@dataclass
class CorePayload:
    title:           str
    summary:         str                        # 200–400 ord — det embeddings byggs på
    content_type:    ContentType = ContentType.BOOK
    language:        str         = "sv"
    tags:            list[str]   = field(default_factory=list)
    quality_score:   float       = 1.0          # 0.0–1.0, OCR/transkriptkvalitet
    sensitivity:     Sensitivity = Sensitivity.INTERNAL
    valid_until:     Optional[str] = None       # None = tidlös, annars ISO 8601
    source_id:       str         = ""           # UUID v5 — binder chunks från samma dokument
    chunk_index:     int         = 0            # 0-baserat
    chunk_total:     int         = 1
    source_hash:     str         = ""           # SHA-256 av chunktexten
    embedding_model: str         = "text-embedding-3-small:1536"
    schema_version:  int         = 1
    indexed_at:      str         = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    id:              str         = field(default_factory=lambda: str(uuid.uuid4()))


# ---------------------------------------------------------------------------
# Lager 2: Location
# ---------------------------------------------------------------------------

@dataclass
class LocationPayload:
    storage_tier:     StorageTier = StorageTier.LOCAL
    cloud_path:       Optional[str] = None
    local_path:       Optional[str] = None      # Absolut sökväg på WD4TB1
    local_available:  bool          = False     # Är WD4TB1 monterad?
    file_size_bytes:  Optional[int] = None
    checksum_sha256:  Optional[str] = None      # SHA-256 av originalfilen


# ---------------------------------------------------------------------------
# Lager 3: BookExt
# ---------------------------------------------------------------------------

@dataclass
class BookExt:
    author:           str
    year:             int
    page_start:       int                        = 0
    page_end:         int                        = 0
    copyright_status: CopyrightStatus           = CopyrightStatus.LICENSED
    access_origin:    AccessOrigin              = AccessOrigin.SELF_CREATED
    shareable:        bool                      = False
    isbn:             Optional[str]             = None
    publisher:        Optional[str]             = None


# ---------------------------------------------------------------------------
# Sammansatt payload — det som lagras i Qdrant
# ---------------------------------------------------------------------------

@dataclass
class FullPayload:
    core:     CorePayload
    location: LocationPayload
    ext:      BookExt

    def to_dict(self) -> dict:
        """Platt dict för Qdrant-payload (inga nästlade objekt)."""
        d: dict = {}

        core_d = asdict(self.core)
        # Enum-värden → strängar
        core_d["content_type"] = self.core.content_type.value
        core_d["sensitivity"]  = self.core.sensitivity.value
        d.update(core_d)

        loc_d = asdict(self.location)
        loc_d["storage_tier"] = self.location.storage_tier.value
        # Prefix location-fält för att undvika kollisioner
        for k, v in loc_d.items():
            d[f"loc_{k}"] = v

        ext_d = asdict(self.ext)
        ext_d["copyright_status"] = self.ext.copyright_status.value
        ext_d["access_origin"]    = self.ext.access_origin.value
        for k, v in ext_d.items():
            d[f"ext_{k}"] = v

        return d

    @classmethod
    def from_dict(cls, d: dict) -> "FullPayload":
        """Återskapa FullPayload från Qdrant-payload-dict."""
        loc_keys = {"storage_tier", "cloud_path", "local_path",
                    "local_available", "file_size_bytes", "checksum_sha256"}
        ext_keys = {"author", "year", "page_start", "page_end",
                    "copyright_status", "access_origin", "shareable", "isbn", "publisher"}

        core_d = {k: v for k, v in d.items()
                  if not k.startswith("loc_") and not k.startswith("ext_")}
        loc_d  = {k[4:]: v for k, v in d.items() if k.startswith("loc_")}
        ext_d  = {k[4:]: v for k, v in d.items() if k.startswith("ext_")}

        core = CorePayload(**{k: v for k, v in core_d.items()
                               if k in CorePayload.__dataclass_fields__})
        loc  = LocationPayload(**{k: v for k, v in loc_d.items()
                                   if k in LocationPayload.__dataclass_fields__})
        ext  = BookExt(**{k: v for k, v in ext_d.items()
                           if k in BookExt.__dataclass_fields__})
        return cls(core=core, location=loc, ext=ext)
