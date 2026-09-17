import Link from "next/link";
export default function NotFound() {
  return (
    <div className="empty-state">
      <h1>Page not found</h1>
      <p className="muted">This page is not part of your workspace.</p>
      <Link className="button primary" href="/technicians">
        Back to Technicians
      </Link>
    </div>
  );
}
