/**
 * The voice guide's word rules (A0, S6), shared by the language lint over
 * the app's strings and the help pages' test, so the product and its help
 * use the same words.
 */

/** Retired words (A0, S2) and engine words a business user would have to look up. */
export const RETIRED: [RegExp, string][] = [
  [/\bpipelines?\b/i, "recipe"],
  [/\bwatermarks?\b/i, "loaded up to"],
  [/\bupserts?\b/i, "update matching rows"],
  [/\btenants?\b/i, "organisation"],
  [/\bmateriali[sz]\w*/i, "save, make"],
  [/\bartifacts?\b/i, "file, dataset"],
  [/\bsnapshots?\b/i, "version"],
  [/\bpersisted\b/i, "saved, recorded"],
  [/\bextraction\b/i, "import"],
  [/\bingestion\b/i, "import, upload"],
  [/\bdrift\b/i, "schema change"],
  [/\bDAG\b/, "workflow"],
  [/\bcron\b/i, "schedule, timetable"],
  [/\bleases?\b/i, "(say what it means)"],
  [/\bpayload\b/i, "(say what it is)"],
  [/\bsemantic (layer|version)\b/i, "metric, version"],
  [/\bHyper extract\b/i, "Tableau file"],
  [/\bdatasource\b/i, "data source"],
  [/\bpublish\w*/i, "deliver, send"],
  [/\bUUID\b/, "(name the thing)"],
  [/\bendpoint\b/i, "web address"],
];

/** US spellings the product writes the UK way ("organisation", "colour", "licence"). */
export const US_SPELLING =
  /\b\w*(organiz|customiz|normaliz|prioritiz|summariz|analyz|initializ|authoriz|recogniz|visualiz|standardiz|optimiz|materializ|minimiz|maximiz)\w*|\b(color|behavior|favorite|license|center)\b|\bcatalog\b|\bCenter\b/;
