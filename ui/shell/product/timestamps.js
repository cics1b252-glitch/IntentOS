export function normalizeTimestamp(value, fallback = 'now') {
  let date = null;
  if (value instanceof Date && Number.isFinite(value.getTime())) date = value;
  else if (typeof value === 'number' && Number.isFinite(value)) {
    date = new Date(Math.abs(value) < 100_000_000_000 ? value * 1000 : value);
  } else if (typeof value === 'string' && value.trim()) {
    const raw = value.trim();
    const numeric = Number(raw);
    date = Number.isFinite(numeric)
      ? new Date(Math.abs(numeric) < 100_000_000_000 ? numeric * 1000 : numeric)
      : new Date(raw);
  }
  if (date && Number.isFinite(date.getTime())) return date.toISOString();
  return fallback === 'now' ? new Date().toISOString() : null;
}

export function formatTimestamp(value, fallback = 'Data não informada') {
  const normalized = normalizeTimestamp(value, 'missing');
  if (!normalized) return fallback;
  const date = new Date(normalized);
  if (Date.now() - date.getTime() < 60_000 && date.getTime() <= Date.now() + 5_000) return 'Agora';
  return date.toLocaleString('pt-BR');
}
