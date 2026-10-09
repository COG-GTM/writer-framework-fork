import { describe, expect, it } from "vitest";
import { getMaxEncodedFilesSize } from "./useFilesEncoder";

describe(getMaxEncodedFilesSize.name, () => {
	const fallback = 200 * 1024 * 1024;

	it("should use the fallback when the server limit is unknown", () => {
		expect(getMaxEncodedFilesSize(null, fallback)).toBe(fallback);
		expect(getMaxEncodedFilesSize(undefined, fallback)).toBe(fallback);
	});

	it("should account for base64 overhead and the message envelope", () => {
		const limit = 5 * 1024 * 1024;
		const max = getMaxEncodedFilesSize(limit, fallback);

		expect(max).toBe(Math.floor(((limit - 64 * 1024) * 3) / 4));
		expect(Math.ceil(max / 3) * 4).toBeLessThan(limit);
	});

	it("should never exceed the fallback", () => {
		expect(getMaxEncodedFilesSize(1024 * 1024 * 1024, fallback)).toBe(
			fallback,
		);
	});

	it("should not return a negative size", () => {
		expect(getMaxEncodedFilesSize(10, fallback)).toBe(0);
	});
});
