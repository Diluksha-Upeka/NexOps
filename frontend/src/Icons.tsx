/**
 * NexOps Icon System
 * ------------------
 * Pure SVG icons — no emojis, no dependencies.
 * Every icon shares the same 24×24 viewBox and currentColor fill for easy theming.
 */
import type { CSSProperties } from 'react';

interface IconProps {
  size?: number;
  className?: string;
  style?: CSSProperties;
  color?: string;
}

const defaults = (p: IconProps, fallbackSize = 20) => ({
  width: p.size ?? fallbackSize,
  height: p.size ?? fallbackSize,
  viewBox: '0 0 24 24',
  fill: 'none',
  xmlns: 'http://www.w3.org/2000/svg',
  className: p.className ?? '',
  style: p.style,
});

/* ── NexOps Brand Mark ──
   A hexagon with a stylised "N" bolt — the single brand symbol.
*/
export function NexOpsLogo({ size = 32, className, style }: IconProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      style={style}
    >
      {/* Hexagon shell */}
      <path
        d="M20 2L36.66 11.5V30.5L20 40L3.34 30.5V11.5L20 2Z"
        fill="url(#nexops-grad)"
        stroke="url(#nexops-grad)"
        strokeWidth="1"
      />
      {/* N letterform */}
      <path
        d="M13 28V12L27 28V12"
        stroke="#fff"
        strokeWidth="2.8"
        strokeLinecap="round"
        strokeLinejoin="round"
        fill="none"
      />
      <defs>
        <linearGradient id="nexops-grad" x1="4" y1="4" x2="38" y2="38" gradientUnits="userSpaceOnUse">
          <stop stopColor="#6366f1" />
          <stop offset="0.5" stopColor="#8b5cf6" />
          <stop offset="1" stopColor="#a855f7" />
        </linearGradient>
      </defs>
    </svg>
  );
}

/* ── Navigation Icons ── */

export function DashboardIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <rect x="3" y="3" width="7" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
      <rect x="14" y="12" width="7" height="9" rx="1.5" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

export function SignalIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M2 20h2v-4h-2v4zm4 0h2v-8h-2v8zm4 0h2v-12h-2v12zm4 0h2v-16h-2v16zm4 0h2v-10h-2v10zm4 0h2v-6h-2v6z" fill="currentColor" />
    </svg>
  );
}

export function BookIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M4 19.5A2.5 2.5 0 016.5 17H20" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M8 7h8M8 11h5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function ChartIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M18 20V10M12 20V4M6 20v-6" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

/* ── Status / Action Icons ── */

export function AlertTriangleIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="9" x2="12" y2="13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <circle cx="12" cy="17" r="0.5" fill="currentColor" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export function AlertCircleIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" />
      <line x1="12" y1="8" x2="12" y2="12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <circle cx="12" cy="16" r="0.5" fill="currentColor" stroke="currentColor" strokeWidth="1" />
    </svg>
  );
}

export function CheckCircleIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="22 4 12 14.01 9 11.01" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function XCircleIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.8" />
      <line x1="15" y1="9" x2="9" y2="15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="9" y1="9" x2="15" y2="15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function PlayIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <polygon points="5,3 19,12 5,21" fill="currentColor" />
    </svg>
  );
}

export function SearchIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <circle cx="11" cy="11" r="8" stroke="currentColor" strokeWidth="1.8" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function ActivityIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ShieldIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ToolIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TargetIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="12" cy="12" r="6" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="12" cy="12" r="2" fill="currentColor" />
    </svg>
  );
}

export function LightbulbIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M9 21h6M12 3a6 6 0 014 10.46V17a1 1 0 01-1 1h-6a1 1 0 01-1-1v-3.54A6 6 0 0112 3z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ClipboardListIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M16 4h2a2 2 0 012 2v14a2 2 0 01-2 2H6a2 2 0 01-2-2V6a2 2 0 012-2h2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <rect x="8" y="2" width="8" height="4" rx="1" stroke="currentColor" strokeWidth="1.8" />
      <line x1="8" y1="10" x2="16" y2="10" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="8" y1="14" x2="14" y2="14" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="8" y1="18" x2="12" y2="18" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function FlameIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M12 2c.5 4-2 6-2 10a4 4 0 008 0c0-4-2-6-2-10a4 4 0 00-4 0z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function HeartPulseIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M20.42 4.58a5.4 5.4 0 00-7.65 0L12 5.34l-.77-.76a5.4 5.4 0 00-7.65 7.65l.77.76L12 20.64l7.65-7.65.77-.76a5.4 5.4 0 000-7.65z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="3 12 7.5 12 9 10 12 16 14 12 17 12 21 12" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function FileTextIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="14 2 14 8 20 8" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="8" y1="13" x2="16" y2="13" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      <line x1="8" y1="17" x2="14" y2="17" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  );
}

export function LinkIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function RocketIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 00-2.91-.09z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 15l-3-3a22 22 0 012-3.95A12.88 12.88 0 0122 2c0 2.72-.78 7.5-6 11.95A22 22 0 0112 15z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M9 12H4s.55-3.03 2-4.5M12 15v5s3.03-.55 4.5-2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function RefreshIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <polyline points="23 4 23 10 17 10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <polyline points="1 20 1 14 7 14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function InboxIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <polyline points="22 12 16 12 14 15 10 15 8 12 2 12" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function ZapIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" fill="currentColor" fillOpacity="0.15" />
    </svg>
  );
}

export function ExternalLinkIcon(p: IconProps) {
  return (
    <svg {...defaults(p, 14)}>
      <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function BrainIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <path d="M12 2a5 5 0 015 5c0 .87-.23 1.68-.63 2.38A5 5 0 0119 14a5 5 0 01-3 4.58V22h-4v-3.42A5 5 0 019 14a5 5 0 012.63-4.62A5 5 0 0112 2z" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M12 2v20" stroke="currentColor" strokeWidth="1" strokeLinecap="round" strokeDasharray="2 3" opacity="0.5" />
    </svg>
  );
}

export function TerminalIcon(p: IconProps) {
  return (
    <svg {...defaults(p)}>
      <polyline points="4 17 10 11 4 5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
      <line x1="12" y1="19" x2="20" y2="19" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

