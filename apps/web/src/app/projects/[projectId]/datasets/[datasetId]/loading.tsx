import { Skeleton } from "@platform/shared-ui";

export default function DatasetDetailLoading() {
  return (
    <div className="space-y-6 px-6 py-8">
      <div className="space-y-3">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-10 w-96" />
        <Skeleton className="h-5 w-[36rem]" />
      </div>

      <div className="grid gap-4 md:grid-cols-4">
        {Array.from({ length: 4 }).map((_, index) => (
          <Skeleton key={index} className="h-28 w-full" />
        ))}
      </div>

      <Skeleton className="h-72 w-full" />
      <Skeleton className="h-80 w-full" />
      <Skeleton className="h-96 w-full" />
    </div>
  );
}
