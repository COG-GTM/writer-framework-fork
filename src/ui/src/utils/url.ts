/**
 * Convert absoule URL to full URL in case the application is hosted on a subpath.
 *
 * ```js
 * convertAbsolutePathtoFullURL("/assets/image.png", "http://localhost:3000/hello/?foo=bar")
 * // => 'http://localhost:3000/hello/assets/image.png'
 * ```
 */
export function convertAbsolutePathtoFullURL(
	path: string,
	base = window.location.toString(),
) {
	return new URL(`.${path}`, base).toString();
}

export function resolveAssetURL(path: string) {
	if (path.startsWith("/")) return convertAbsolutePathtoFullURL(path);
	return path;
}

export const EMBED_URL_PROTOCOLS = Object.freeze(["http:", "https:", "blob:"]);
export const MEDIA_URL_PROTOCOLS = Object.freeze([
	"http:",
	"https:",
	"blob:",
	"data:",
]);
export const LINK_URL_PROTOCOLS = Object.freeze([
	"http:",
	"https:",
	"mailto:",
	"tel:",
]);

/**
 * Returns the URL unchanged when its scheme (resolved the same way the browser
 * does, so relative paths inherit the page scheme) is in `allowedProtocols`,
 * otherwise an empty string. Blocks `javascript:`, `vbscript:` and the like.
 *
 * ```js
 * sanitizeURL("javascript:alert(1)", EMBED_URL_PROTOCOLS) // => ''
 * sanitizeURL("static/page.html", EMBED_URL_PROTOCOLS) // => 'static/page.html'
 * ```
 */
export function sanitizeURL(
	value: unknown,
	allowedProtocols: readonly string[],
	base = window.location.toString(),
): string {
	if (typeof value !== "string") return "";
	const url = value.trim();
	if (!url) return "";
	try {
		const { protocol } = new URL(url, base);
		return allowedProtocols.includes(protocol) ? url : "";
	} catch {
		return "";
	}
}
