"use client";
export default function ErrorPage({
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <section className="panel">
      <div className="panel-body" role="alert">
        <h1>Unable to display this page</h1>
        <p>Please try again. If the problem continues, reload the page.</p>
        <button className="button secondary" onClick={reset}>
          Try again
        </button>
      </div>
    </section>
  );
}
