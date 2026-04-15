import { cx } from "./internal/cx";

type SkeletonProps = {
  className?: string;
};

export function Skeleton({ className }: SkeletonProps) {
  return <div className={cx("animate-pulse rounded-2xl bg-white/[0.06]", className)} />;
}
