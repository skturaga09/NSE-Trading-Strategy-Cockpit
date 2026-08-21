export function Placeholder({ title }: { title: string }) {
  return (
    <div className="panel grid min-h-[300px] place-items-center rounded-2xl p-10 text-center">
      <div>
        <div className="text-4xl">🚧</div>
        <h2 className="mt-3 text-lg font-bold text-ink">{title}</h2>
        <p className="mt-1 text-sm text-muted">
          Being ported to React. Still fully working in the classic dashboard at{" "}
          <code className="rounded bg-raised px-1.5 py-0.5 text-xs">/</code> on port 8080.
        </p>
      </div>
    </div>
  );
}
