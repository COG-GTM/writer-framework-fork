import { type internal } from "arquero";
import { ARQUERO_INTERNAL_ID } from "./constants";

// Leading characters that spreadsheet applications interpret as the start of
// a formula (OWASP CSV injection guidance).
const FORMULA_TRIGGER_PATTERN = /^[=+\-@\t\r]/;

export function neutralizeCsvFormula<T>(value: T): T | string {
	if (typeof value !== "string") return value;
	return FORMULA_TRIGGER_PATTERN.test(value) ? `'${value}` : value;
}

export function dataframeToSafeCSV(table: internal.ColumnTable): string {
	const columnNames = table
		.columnNames()
		.filter((name) => name !== ARQUERO_INTERNAL_ID);
	const safeNames = Object.fromEntries(
		columnNames.map((name) => [name, neutralizeCsvFormula(name)]),
	);
	const format = Object.fromEntries(
		Object.values(safeNames).map((name) => [name, neutralizeCsvFormula]),
	);
	return table.select(safeNames).toCSV({ format });
}
