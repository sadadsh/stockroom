/**
 * Inline SVG icons lifted from the mockup (library-v2.html). Self contained so
 * the bundle needs no icon font or network fetch (WebView2 loads it offline).
 */

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
      <g stroke="#8b9099" strokeWidth="1.5" fill="none">
        <rect x="40" y="20" width="52" height="54" rx="3" />
        <path d="M40 33H24M40 47H24M40 61H24M92 33h16M92 47h16M92 61h16" />
      </g>
      <text
        x="66"
        y="51"
        fill="#c7ccd3"
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
      <g fill="#7f858e">
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
        stroke="#4b5057"
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
      stroke="#8a8f97"
      strokeWidth="1.4"
    >
      <path d="M45 12l30 17v32L45 78 15 61V29z" />
      <path d="M45 12v18M45 30l30-17M45 30L15 13" opacity="0.5" />
    </svg>
  );
}
