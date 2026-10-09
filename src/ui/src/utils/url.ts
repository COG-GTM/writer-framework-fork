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

const SAFE_URL_PROTOCOLS = new Set(["http:", "https:", "mailto:", "tel:"]);

/**
 * Return the URL if its scheme is safe to navigate to (http, https, mailto,
 * tel, or a relative / `#page-key` link), otherwise `about:blank`.
 */
export function sanitizeUrl(
	url: unknown,
	base = window.location.href,
): string {
	if (url === undefined || url === null) return "";
	const value = String(url);
	if (value.trim() === "") return "";
	try {
		const { protocol } = new URL(value, base);
		if (SAFE_URL_PROTOCOLS.has(protocol)) return value;
	} catch {
		// unparsable URLs are rejected below
	}
	return "about:blank";
}
