interface ErrorPanelProps {
  message: string;
}

export function ErrorPanel({ message }: ErrorPanelProps) {
  return (
    <div className="panel error-panel">
      <h3>Request failed</h3>
      <p>{message}</p>
    </div>
  );
}
