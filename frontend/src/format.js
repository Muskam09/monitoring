// Small formatting helpers reused across the dashboard.

/** 1234.5 → "1.2 kB/s", 1_500_000 → "1.5 MB/s" */
export function formatBytesPerSec(n) {
  if (n == null || isNaN(n)) return '—';
  const abs = Math.abs(n);
  if (abs < 1024) return `${n.toFixed(0)} B/s`;
  if (abs < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB/s`;
  if (abs < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB/s`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB/s`;
}

/** 93120 (seconds) → "1d 1h 52m" */
export function formatUptime(sec) {
  if (sec == null || isNaN(sec)) return '—';
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const parts = [];
  if (d) parts.push(`${d}d`);
  if (h) parts.push(`${h}h`);
  parts.push(`${m}m`);
  return parts.join(' ');
}

/** 73.4 → "73%" + Tailwind class based on usage band */
export function usageColor(pct) {
  if (pct == null) return 'text-gray-400';
  if (pct >= 90) return 'text-red-600';
  if (pct >= 75) return 'text-orange-500';
  if (pct >= 50) return 'text-yellow-600';
  return 'text-green-600';
}

export function usageBarColor(pct) {
  if (pct == null) return 'bg-gray-300';
  if (pct >= 90) return 'bg-red-500';
  if (pct >= 75) return 'bg-orange-500';
  if (pct >= 50) return 'bg-yellow-500';
  return 'bg-green-500';
}
