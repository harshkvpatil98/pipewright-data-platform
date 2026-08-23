import { cx } from "./internal/cx";

type SkeletonProps = {
  className?: string;
};

export function Skeleton({ className }: SkeletonProps) {
  return <div className={cx("animate-pulse rounded-2xl bg-surface-2", className)} />;
}
