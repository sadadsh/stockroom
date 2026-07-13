/**
 * Response shapes mirrored from the backend DTOs. These are the presentation
 * contract only; the source of truth stays the PartRecord JSON + derived index
 * (stockroom.api.schemas, stockroom.model.part). Kept in lockstep with those.
 */

// GET /api/library/parts -> { parts: PartSummary[], count }
export interface PartSummary {
  id: string;
  display_name: string;
  category: string;
  mpn: string;
  manufacturer: string;
  is_complete: boolean;
  missing: string[];
}

export interface PartsResponse {
  parts: PartSummary[];
  count: number;
}

// GET /api/library/facets
export interface Facets {
  by_category: Record<string, number>;
  by_manufacturer: Record<string, number>;
  complete: number;
  incomplete: number;
}

// Nested records inside the full part detail (stockroom.model.part).
export interface DatasheetRef {
  file: string;
  source_url: string;
  fetched_at: string;
}

export interface PriceBreak {
  // price_breaks are emitted as raw lists; tolerate either [qty, price] pairs
  // or objects so the panel never crashes on a shape it did not expect.
  [key: string]: unknown;
}

export interface PurchaseRef {
  vendor: string;
  url: string;
  price_breaks: PriceBreak[];
  stock: number | null;
  currency: string;
  fetched_at: string;
}

export interface LibRef {
  lib: string;
  name: string;
}

export interface ModelRef {
  file: string;
}

export interface Provenance {
  source: string;
  source_url: string;
  original_zip_sha256: string;
  ingested_at: string;
}

// GET /api/library/parts/{id} -> full PartRecord.to_dict()
export interface PartDetail {
  id: string;
  display_name: string;
  category: string;
  description: string;
  tags: string[];
  mpn: string;
  manufacturer: string;
  datasheet: DatasheetRef | null;
  purchase: PurchaseRef[];
  symbol: LibRef | null;
  footprint: LibRef | null;
  model: ModelRef | null;
  provenance: Provenance | null;
  hashes: Record<string, string> | null;
  enrichment: Record<string, { source: string; confidence: string }>;
}

export interface ApiErrorBody {
  error?: string;
  detail?: string;
  message?: string;
}

// POST /api/enrich/part -> the canonical enrichment result (stockroom.enrich.schema).
// Each single-valued field carries the source it came from and a confidence, or is
// null when no source could fill it (a scrape miss is null, never an error).
export interface SourcedField {
  value: unknown;
  source: string;
  confidence: string;
}

export interface EnrichPriceBreak {
  qty: number;
  price: number;
  currency: string;
}

export interface EnrichmentResult {
  category: string;
  mpn: SourcedField | null;
  manufacturer: SourcedField | null;
  description: SourcedField | null;
  datasheet_url: SourcedField | null;
  stock: SourcedField | null;
  package: SourcedField | null;
  price_breaks: EnrichPriceBreak[];
  specs: Record<string, SourcedField | null>;
  schema_version: number;
}
