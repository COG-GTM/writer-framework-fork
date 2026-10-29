<template>
	<span ref="root" :style="{ display: 'contents' }" />
</template>

<script setup lang="ts">
import { onMounted, ref, toRef, watch } from "vue";
import { createElement, icons } from "lucide";

defineOptions({
	inheritAttrs: false,
});

const props = defineProps({
	name: { type: String, required: true },
});

const root = ref<HTMLSpanElement>();

function toPascalCase(name: string) {
	const camel = name.replace(/^([A-Z])|[\s-_]+(\w)/g, (_match, p1, p2) =>
		p2 ? p2.toUpperCase() : p1.toLowerCase(),
	);
	return camel.charAt(0).toUpperCase() + camel.slice(1);
}

function renderIcon(name: string) {
	const el = root.value;
	if (!el) return;

	const iconName = toPascalCase(name);
	const iconNode = Object.hasOwn(icons, iconName)
		? icons[iconName as keyof typeof icons]
		: undefined;

	if (!iconNode) {
		el.replaceChildren();
		return;
	}

	el.replaceChildren(
		createElement(iconNode, {
			"data-lucide": name,
			class: `lucide lucide-${name}`,
			width: "1em",
			height: "1em",
		}),
	);
}

onMounted(() => renderIcon(props.name));

watch(
	toRef(props, "name"),
	(newName) => {
		renderIcon(newName);
	},
	{ flush: "post" },
);
</script>
