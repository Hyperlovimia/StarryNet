export function formatDateTime(value: number | null): string {
  if (!value) {
    return "Not available";
  }
  return new Date(value * 1000).toLocaleString();
}

export function formatRelativeDuration(start: number | null, end: number | null): string {
  if (!start) {
    return "Not started";
  }
  const endMs = end ? end * 1000 : Date.now();
  const durationMs = Math.max(0, endMs - start * 1000);
  const seconds = Math.floor(durationMs / 1000);
  const minutes = Math.floor(seconds / 60);
  if (minutes > 0) {
    return `${minutes}m ${seconds % 60}s`;
  }
  return `${seconds}s`;
}

export function formatCoordinates(points: number[][]): string {
  if (!points.length) {
    return "None";
  }
  return points.map(([lat, lon]) => `${lat.toFixed(3)}, ${lon.toFixed(3)}`).join(" | ");
}
