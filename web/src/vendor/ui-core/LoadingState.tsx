export interface LoadingStateProps {
  rows?: number
}

export function LoadingState({ rows = 4 }: LoadingStateProps) {
  return (
    <div className="animate-page-enter space-y-4 p-6">
      <div className="h-5 w-1/3 animate-pulse rounded-xl bg-background-secondary" />
      <div className="h-3.5 w-1/2 animate-pulse rounded-lg bg-background-secondary/70" />

      <div className="mt-6 space-y-3">
        {Array.from({ length: rows }).map((_, index) => (
          <div
            key={index}
            className="h-10 animate-pulse rounded-2xl bg-background-secondary/50"
            style={{ animationDelay: `${index * 100}ms`, width: `${95 - index * 5}%` }}
          />
        ))}
      </div>
    </div>
  )
}
