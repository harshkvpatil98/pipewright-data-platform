/**
 * Single source of truth for product naming. Everything user-facing reads from
 * here so the product can be renamed in one place.
 */
export const brand = {
  name: "Pipewright",
  /** Kept short so it sits on one line beside the mark in the sidebar. */
  tagline: "Data, made ready",
  /** Used for page titles and meta description. */
  description:
    "Pipewright brings data in from files, databases and apps, cleans it with recipes, checks it, and delivers it where it is needed, on a schedule or by hand.",
  shortDescription: "Bring data in, clean it, check it and deliver it, with every run recorded.",
} as const;

export const appName = process.env.NEXT_PUBLIC_APP_NAME ?? brand.name;
