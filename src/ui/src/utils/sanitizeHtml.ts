import type { Config, UponSanitizeAttributeHook } from "dompurify";

/**
 * Restrictive DOMPurify configuration for HTML generated from markdown
 * (`marked` keeps inline HTML, so this is the only sanitization step).
 */
export const SANITIZE_HTML_CONFIG: Config = {
	FORBID_TAGS: [
		"style",
		"form",
		"input",
		"button",
		"textarea",
		"select",
		"option",
		"svg",
		"math",
		"template",
		"noscript",
	],
	ALLOWED_URI_REGEXP:
		/^(?:(?:https?|mailto|tel):|(?![/\\]{2})[^a-z]|[a-z+.-]+(?:[^a-z+.\-:]|$))/i,
};

const SAFE_STYLE_REGEXP =
	/^\s*background(?:-color)?\s*:\s*[#a-z0-9(),./%\s-]+;?\s*$/i;
const UNSAFE_STYLE_REGEXP = /url\s*\(|expression|image|var\s*\(|\\|\/\*/i;

/**
 * Only keep inline styles that set a background colour (used by annotated
 * text); any other inline style is dropped.
 */
export function isSafeInlineStyle(value: string) {
	return SAFE_STYLE_REGEXP.test(value) && !UNSAFE_STYLE_REGEXP.test(value);
}

export const restrictInlineStyle: UponSanitizeAttributeHook = (_node, data) => {
	if (data.attrName !== "style") return;
	if (!isSafeInlineStyle(data.attrValue)) data.keepAttr = false;
};

export const SANITIZE_HTML_HOOKS = {
	uponSanitizeAttribute: restrictInlineStyle,
};

/** Options for the `vue-dompurify-html` plugin. */
export const VUE_DOMPURIFY_HTML_OPTIONS = {
	default: SANITIZE_HTML_CONFIG,
	hooks: SANITIZE_HTML_HOOKS,
};
