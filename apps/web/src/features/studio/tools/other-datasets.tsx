"use client";

import { createContext, useContext } from "react";

/** A dataset a tool can read besides the one being edited, with its columns. */
export type OtherDataset = { id: string; name: string; columns: string[] };

const OtherDatasetsContext = createContext<OtherDataset[]>([]);

/**
 * The project's other datasets, for tools that read one (a lookup, an as-of
 * join). Given once by the Studio rather than threaded through the palette,
 * the step list and the inspector, which all show the same tool form.
 */
export function OtherDatasetsProvider({
  datasets,
  children,
}: {
  datasets: OtherDataset[];
  children: React.ReactNode;
}) {
  return (
    <OtherDatasetsContext.Provider value={datasets}>
      {children}
    </OtherDatasetsContext.Provider>
  );
}

export function useOtherDatasets(): OtherDataset[] {
  return useContext(OtherDatasetsContext);
}

/** A dataset record's column names, from its stored schema. */
export function datasetColumns(
  schema: Record<string, unknown> | null | undefined,
): string[] {
  const columns = schema?.columns;
  if (!Array.isArray(columns)) return [];
  return columns
    .map((column) =>
      column && typeof column === "object" && "name" in column
        ? String(column.name)
        : "",
    )
    .filter(Boolean);
}
