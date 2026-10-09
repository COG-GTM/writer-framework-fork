import { type internal } from "arquero";
import { ARQUERO_INTERNAL_ID } from "./constants";

// Leading characters that spreadsheet applications interpret as the start of
// a formula (OWASP CSV injection guidance).
const FORMULA_TRIGGER_PATTERN = /^[=+\-@\t\r]/;
const CSV_QUOTE_PATTERN = /[",\n\r]/;

export function neutralizeCsvFormula<T>(value: T): T | string {
	if (typeof value !== "string") return value;
	return FORMULA_TRIGGER_PATTERN.test(value) ? `'${value}` : value;
}

function quoteCsvField(value: string) {
	return CSV_QUOTE_PATTERN.test(value)
		? `"${value.replace(/"/g, '""')}"`
		: value;
}

export function dataframeToSafeCSV(table: internal.ColumnTable): string {
	const columnNames = table
		.columnNames()
		.filter((name) => name !== ARQUERO_INTERNAL_ID);
	const exported = table.select(columnNames);

	// Escaped headers are written separately rather than renamed in the
	// table, as renaming could make two distinct columns collide
	// (e.g. "=x" and "'=x").
	const rawHeader = exported.slice(0, 0).toCSV();
	const format = Object.fromEntries(
		columnNames.map((name) => [name, neutralizeCsvFormula]),
	);
	const rows = exported.toCSV({ format }).slice(rawHeader.length);
	const header = columnNames
		.map((name) => quoteCsvField(String(neutralizeCsvFormula(name))))
		.join(",");

	return rawHeader.endsWith("\n") ? `${header}\n${rows}` : header + rows;
}
