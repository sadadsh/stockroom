/**
 * Inline SVG icons lifted from the mockup (library-v2.html). Self contained so
 * the bundle needs no icon font or network fetch (WebView2 loads it offline).
 */
import type { ReactNode } from "react";

export function SearchIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
    >
      <circle cx="11" cy="11" r="7" />
      <path d="M21 21l-4.3-4.3" />
    </svg>
  );
}

export function WarnIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path d="M12 3.4l9.3 16.1H2.7z" strokeLinejoin="round" />
      <path d="M12 10v4.2" strokeLinecap="round" />
      <circle cx="12" cy="17.4" r="0.5" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function InfoIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
    >
      <circle cx="12" cy="12" r="9" />
      <path d="M12 11v5" strokeLinecap="round" />
      <circle cx="12" cy="7.8" r="0.6" fill="currentColor" stroke="none" />
    </svg>
  );
}

export function UploadIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.4}
    >
      <path d="M12 15V3m0 0L8 7m4-4l4 4" />
      <path d="M4 17v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" />
    </svg>
  );
}

export function CloseIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
    >
      <path d="M6 6l12 12M18 6L6 18" strokeLinecap="round" />
    </svg>
  );
}

export function BackIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="15"
      height="15"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
    >
      <path d="M15 5l-7 7 7 7" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ExternalIcon({ className }: { className?: string }) {
  return (
    <svg
      className={className}
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
    >
      <path
        d="M14 4h6v6M20 4l-9 9M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

// Simple line art for the Symbol, Footprint and 3D Model file cards (mockup).
export function SymbolArt() {
  return (
    <svg viewBox="0 0 132 94" width="132" height="94">
      <g style={{ stroke: "var(--c-icon-line)" }} strokeWidth="1.5" fill="none">
        <rect x="40" y="20" width="52" height="54" rx="3" />
        <path d="M40 33H24M40 47H24M40 61H24M92 33h16M92 47h16M92 61h16" />
      </g>
      <text
        x="66"
        y="51"
        style={{ fill: "var(--c-icon-faint)" }}
        fontSize="10"
        textAnchor="middle"
        fontFamily="monospace"
      >
        U1
      </text>
    </svg>
  );
}

export function FootprintArt() {
  const pads = [34, 48, 62, 76, 90];
  return (
    <svg viewBox="0 0 132 94" width="132" height="94">
      <g style={{ fill: "var(--c-icon-fill)" }}>
        {pads.map((x) => (
          <rect key={`t${x}`} x={x} y="26" width="9" height="7" rx="1" />
        ))}
        {pads.map((x) => (
          <rect key={`b${x}`} x={x} y="61" width="9" height="7" rx="1" />
        ))}
      </g>
      <rect
        x="38"
        y="37"
        width="60"
        height="20"
        rx="2"
        fill="none"
        style={{ stroke: "var(--c-icon-edge)" }}
        strokeWidth="1.3"
      />
    </svg>
  );
}

export function CubeArt() {
  return (
    <svg
      viewBox="0 0 90 90"
      width="70"
      height="70"
      fill="none"
      style={{ stroke: "var(--c-icon-cube)" }}
      strokeWidth="1.4"
    >
      <path d="M45 12l30 17v32L45 78 15 61V29z" />
      <path d="M45 12v18M45 30l30-17M45 30L15 13" opacity="0.5" />
    </svg>
  );
}

// -- Action + navigation icon set (M-icons pass). All 24x24, stroke=currentColor so they
// inherit text color + retint per theme; default 14px, sized via className. Self-contained.

function Svg({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <svg
      className={className ?? "h-3.5 w-3.5"}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.9}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export function LibraryIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <rect x="3" y="4" width="7" height="16" rx="1" />
      <rect x="14" y="4" width="7" height="16" rx="1" />
      <path d="M6.5 8h0M6.5 12h0M17.5 8h0M17.5 12h0" />
    </Svg>
  );
}

export function AddPartIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M12 5v14M5 12h14" />
    </Svg>
  );
}

export function DuplicateIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <rect x="9" y="9" width="11" height="11" rx="2" />
      <path d="M5 15V5a2 2 0 0 1 2-2h8" />
    </Svg>
  );
}

export function ProjectsIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M12 3l9 5-9 5-9-5 9-5Z" />
      <path d="M3 13l9 5 9-5" />
    </Svg>
  );
}

export function DoctorIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M3 12h4l2 5 4-12 2 7h6" />
    </Svg>
  );
}

export function SettingsIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" />
    </Svg>
  );
}

export function DownloadIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M12 3v12M7 10l5 5 5-5" />
      <path d="M4 20h16" />
    </Svg>
  );
}

export function BuildIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M7 4v16l13-8Z" />
    </Svg>
  );
}

export function RefreshIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M20 11a8 8 0 0 0-14-4.5L3 9M4 13a8 8 0 0 0 14 4.5L21 15" />
      <path d="M3 4v5h5M21 20v-5h-5" />
    </Svg>
  );
}

export function EditIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17v3Z" />
      <path d="M13.5 6.5l3 3" />
    </Svg>
  );
}

export function TrashIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M4 7h16M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
    </Svg>
  );
}

export function EnrichIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <path d="M12 3l1.8 4.7L18.5 9.5 13.8 11.3 12 16l-1.8-4.7L5.5 9.5 10.2 7.7 12 3Z" />
      <path d="M19 15l.7 1.8L21.5 17.5l-1.8.7L19 20l-.7-1.8L16.5 17.5l1.8-.7L19 15Z" />
    </Svg>
  );
}

export function GitIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <circle cx="6" cy="6" r="2.5" />
      <circle cx="6" cy="18" r="2.5" />
      <circle cx="18" cy="8" r="2.5" />
      <path d="M6 8.5v7M18 10.5c0 4-4 3.5-6 5.5" />
    </Svg>
  );
}

export function BoardIcon({ className }: { className?: string }) {
  return (
    <Svg className={className}>
      <rect x="4" y="4" width="16" height="16" rx="2" />
      <circle cx="9" cy="9" r="1.3" />
      <circle cx="15" cy="15" r="1.3" />
      <path d="M9 10.3v3.4M15 10.3v3.4M10.3 9h3.4" />
    </Svg>
  );
}
