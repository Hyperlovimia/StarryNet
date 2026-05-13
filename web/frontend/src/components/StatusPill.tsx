interface StatusPillProps {
  status: string;
}

export function StatusPill({ status }: StatusPillProps) {
  const tone = `status-pill status-${status.toLowerCase()}`;
  return <span className={tone}>{status}</span>;
}
