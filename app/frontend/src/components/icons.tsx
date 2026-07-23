/**
 * The named icon exports, kept as thin wrappers over <Icon id>. Every glyph now lives once in the
 * registry (lib/iconRegistry.ts) and is drawn by <Icon> (components/Icon.tsx), so each of these is
 * inspectable + editable in dev mode while every existing call site keeps working unchanged: same
 * export names, same `{ className }` signature, pixel-identical output. Prefer <Icon id="..."> in
 * new code; these wrappers exist so the current consumers need no edit.
 */
import { Icon } from "./Icon";

export function SearchIcon({ className }: { className?: string }) {
  return <Icon id="action.search" className={className} />;
}

export function WarnIcon({ className }: { className?: string }) {
  return <Icon id="status.warn" className={className} />;
}

export function InfoIcon({ className }: { className?: string }) {
  return <Icon id="status.info" className={className} />;
}

export function UploadIcon({ className }: { className?: string }) {
  return <Icon id="action.upload" className={className} />;
}

export function CloseIcon({ className }: { className?: string }) {
  return <Icon id="action.close" className={className} />;
}

export function BackIcon({ className }: { className?: string }) {
  return <Icon id="nav.back" className={className} />;
}

export function ExternalIcon({ className }: { className?: string }) {
  return <Icon id="action.external" className={className} />;
}

// Line art for the Symbol, Footprint and 3D Model file cards. Now registry glyphs; the wrappers
// gain a `{ className }` prop for uniformity, but existing prop-less call sites are unaffected.
export function SymbolArt({ className }: { className?: string }) {
  return <Icon id="art.symbol" className={className} />;
}

export function FootprintArt({ className }: { className?: string }) {
  return <Icon id="art.footprint" className={className} />;
}

export function CubeArt({ className }: { className?: string }) {
  return <Icon id="art.model" className={className} />;
}

// -- Action + navigation icon set. Registry ids under action.* / nav.*; primary line icons that
// carry `.ico` so dev mode's --icon-stroke retunes the whole set at once.

export function LibraryIcon({ className }: { className?: string }) {
  return <Icon id="nav.library" className={className} />;
}

export function AddPartIcon({ className }: { className?: string }) {
  return <Icon id="action.add" className={className} />;
}

export function DuplicateIcon({ className }: { className?: string }) {
  return <Icon id="action.duplicate" className={className} />;
}

export function ProjectsIcon({ className }: { className?: string }) {
  return <Icon id="nav.projects.alt" className={className} />;
}

export function DoctorIcon({ className }: { className?: string }) {
  return <Icon id="action.doctor" className={className} />;
}

export function SettingsIcon({ className }: { className?: string }) {
  return <Icon id="action.settings" className={className} />;
}

export function DownloadIcon({ className }: { className?: string }) {
  return <Icon id="action.download" className={className} />;
}

export function BuildIcon({ className }: { className?: string }) {
  return <Icon id="action.build" className={className} />;
}

export function RefreshIcon({ className }: { className?: string }) {
  return <Icon id="action.refresh" className={className} />;
}

export function EditIcon({ className }: { className?: string }) {
  return <Icon id="action.edit" className={className} />;
}

export function TrashIcon({ className }: { className?: string }) {
  return <Icon id="action.trash" className={className} />;
}

export function EnrichIcon({ className }: { className?: string }) {
  return <Icon id="action.enrich" className={className} />;
}

export function GitIcon({ className }: { className?: string }) {
  return <Icon id="action.git" className={className} />;
}

export function BoardIcon({ className }: { className?: string }) {
  return <Icon id="nav.board" className={className} />;
}
