import { describe, expect, it } from "vitest";
import {
	exceedsWebsocketLimit,
	getMaxEncodedFilesSize,
} from "./useFilesEncoder";

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

describe(exceedsWebsocketLimit.name, () => {
	it("should never block when the server limit is unknown", () => {
		expect(exceedsWebsocketLimit({ data: "x".repeat(1000) }, null)).toBe(
			false,
		);
	});

	it("should compare the serialized size plus envelope reserve", () => {
		const limit = 64 * 1024;
		expect(exceedsWebsocketLimit({ data: "x".repeat(1024) }, limit)).toBe(
			false,
		);
		expect(
			exceedsWebsocketLimit({ data: "x".repeat(60 * 1024) }, limit),
		).toBe(true);
	});

	it("should count multi-byte characters in bytes", () => {
		const limit = 32 * 1024;
		const text = "\u00e9".repeat(9 * 1024);
		expect(text.length + 16 * 1024).toBeLessThan(limit);
		expect(exceedsWebsocketLimit({ text }, limit)).toBe(true);
	});
});
