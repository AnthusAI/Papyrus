export type SignupEntryRecord = {
  id: string;
  form: string;
  value: string;
  submittedAt: string;
};

export const SIGNUP_CSV_HEADER = ["form", "value", "submittedAt"] as const;
const FORMULA_STARTS = new Set(["=", "+", "-", "@", "\t", "\r"]);

/** A spreadsheet runs a cell that starts with one of these as a formula; a leading quote makes it text. */
export function neutralizeFormula(cell: string): string {
  return cell !== "" && FORMULA_STARTS.has(cell[0]) ? `'${cell}` : cell;
}

export function csvCell(cell: string): string {
  const safe = neutralizeFormula(cell);
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}

export function signupEntriesToCsv(entries: SignupEntryRecord[]): string {
  const rows = entries.map((entry) => SIGNUP_CSV_HEADER.map((column) => csvCell(String(entry[column] ?? ""))).join(","));
  return `${[SIGNUP_CSV_HEADER.join(","), ...rows].join("\r\n")}\r\n`;
}
