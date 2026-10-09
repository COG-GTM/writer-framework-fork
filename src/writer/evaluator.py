import io
import json
import os
import re
import tokenize
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import writer.core
import writer.core_ui
from writer.ss_types import (
    InstancePath,
    WriterConfigurationError,
)

if TYPE_CHECKING:
    from writer.core import WriterState
    from writer.core_ui import ComponentTree


class Evaluator:
    """
    Evaluates templates and expressions in the backend.
    It allows for the sanitisation of frontend inputs.
    """

    TEMPLATE_REGEX = re.compile(r"[\\]?@{([^{]*?)}")
    CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
    STRING_PREFIX_REGEX = re.compile(r"^[A-Za-z]*")

    def __init__(self, state: "WriterState", component_tree: "ComponentTree"):
        self.state = state
        self.component_tree = component_tree
        self.serializer = writer.core.StateSerialiser()

    def evaluate_field(
        self,
        instance_path: InstancePath,
        field_key: str,
        as_json=False,
        default_field_value="",
        base_context={},
    ) -> Any:
        def decode_json(text):
            if not isinstance(text, str):
                return text
            try:
                # Remove control chars
                clean_text = Evaluator.CONTROL_CHARS.sub("", text)
                return json.loads(clean_text, strict=False)
            except json.JSONDecodeError as exception:
                raise WriterConfigurationError(
                    "Error decoding JSON. " + str(exception)
                ) from exception

        component_id = instance_path[-1]["componentId"]
        component = self.component_tree.get_component(component_id)
        if not component:
            raise ValueError(f'Component with id "{component_id}" not found.')

        field_value = component.content.get(field_key) or default_field_value
        full_match = self.TEMPLATE_REGEX.fullmatch(field_value)

        def replacer(matched: re.Match):
            if matched.group(0)[0] == "\\":  # Escaped @, don't evaluate
                return matched.group(0)
            expr = matched.group(1).strip()
            expr_value = self.evaluate_expression(expr, instance_path, base_context)
            if full_match is not None:
                return expr_value
            if as_json:
                dumped = expr_value
                if not isinstance(dumped, str):
                    dumped = json.dumps(dumped)
                else:
                    dumped = json.dumps(dumped)[1:-1]
                return re.sub(r'(?<!\\)"', r'\"', dumped)
            if not isinstance(expr_value, str):
                return json.dumps(expr_value)
            return expr_value

        if full_match is None:
            replaced = self.TEMPLATE_REGEX.sub(replacer, field_value)
        else:
            replaced = replacer(full_match)
        if as_json:
            replaced = decode_json(replaced)

        return replaced

    def evaluate_code_field(
        self,
        instance_path: InstancePath,
        field_key: str,
        default_field_value="",
        base_context={},
        mode="exec",
    ) -> Tuple[str, Dict[str, Any]]:
        """
        Prepares a field holding Python source (e.g. an If-Else expression or a Code block)
        for compile()/eval()/exec().

        Template values are never spliced into the source. Each template is replaced by a
        placeholder variable and its value is returned in the bindings, which the caller
        must add to the globals used for execution. Templates used as the content of a
        string literal (e.g. "@{payload}" == "yes") are bound as text, as before.
        `mode` is the compile() mode the source is meant for ("exec" or "eval").
        """

        component_id = instance_path[-1]["componentId"]
        component = self.component_tree.get_component(component_id)
        if not component:
            raise ValueError(f'Component with id "{component_id}" not found.')

        field_value = component.content.get(field_key) or default_field_value
        prefix = "__wf_template_"
        while prefix in field_value:
            prefix += "_"

        values: List[Any] = []

        def replacer(matched: re.Match):
            if matched.group(0)[0] == "\\":  # Escaped @, don't evaluate
                return matched.group(0)
            expr = matched.group(1).strip()
            values.append(self.evaluate_expression(expr, instance_path, base_context))
            return f"{prefix}{len(values) - 1}__"

        source = self.TEMPLATE_REGEX.sub(replacer, field_value)
        if not values:
            return source, {}
        return self._bind_code_templates(source, prefix, values, field_key, mode)

    def _bind_code_templates(
        self, source: str, prefix: str, values: List[Any], field_key: str, mode: str
    ) -> Tuple[str, Dict[str, Any]]:
        placeholder_regex = re.compile(re.escape(prefix) + r"\d+__")
        bindings: Dict[str, Any] = {f"{prefix}{i}__": value for i, value in enumerate(values)}
        substitute_name = f"{prefix}substitute__"

        def as_text(value: Any) -> str:
            return value if isinstance(value, str) else json.dumps(value)

        def substitute(literal: str) -> str:
            return placeholder_regex.sub(lambda m: as_text(bindings[m.group(0)]), literal)

        line_offsets = [0]
        for line in io.StringIO(source).readlines():
            line_offsets.append(line_offsets[-1] + len(line))

        def offset(position: Tuple[int, int]) -> int:
            return line_offsets[position[0] - 1] + position[1]

        try:
            tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
        except (tokenize.TokenError, SyntaxError):
            # Invalid source; compile() will report it. Placeholders stay plain names.
            return source, bindings

        def unsupported(where: str) -> WriterConfigurationError:
            return WriterConfigurationError(
                f"Templates (@{{...}}) can't be used in {where} in the field `{field_key}`. "
                'Reference the value as a variable instead, for example state["my_var"], payload or result.'
            )

        statement_start_types = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
        insignificant_types = (tokenize.NL, tokenize.COMMENT)
        significant = [t for t in tokens if t.type not in insignificant_types]

        # Indexes (in `significant`) of tokens that are part of match/case patterns,
        # where only literals are allowed.
        case_pattern: set = set()
        if mode == "exec":
            for i, token in enumerate(significant):
                at_statement_start = i == 0 or significant[i - 1].type in statement_start_types
                if not (at_statement_start and token.type == tokenize.NAME and token.string == "case"):
                    continue
                if i + 1 < len(significant) and significant[i + 1].string in (":", "=", ".", ","):
                    continue
                depth = 0
                for j in range(i + 1, len(significant)):
                    current = significant[j]
                    if current.type == tokenize.NEWLINE:
                        break
                    if current.string in ("(", "[", "{"):
                        depth += 1
                    elif current.string in (")", "]", "}"):
                        depth -= 1
                    elif depth == 0 and (current.string == ":" or current.string == "if"):
                        case_pattern.update(range(i + 1, j))
                        break

        # Runs of adjacent string literals (implicitly concatenated) that contain placeholders
        # are wrapped in a call that replaces the placeholders with the text of their values
        # at runtime, so the values never become part of the source.
        edits: List[Tuple[int, int]] = []
        i = 0
        while i < len(significant):
            token = significant[i]
            has_placeholder = placeholder_regex.search(token.string) is not None
            if token.type != tokenize.STRING:
                if has_placeholder and token.type != tokenize.NAME:
                    # e.g. the literal parts of f-strings, tokenized separately since Python 3.12
                    raise unsupported("f-strings or bytes literals")
                i += 1
                continue

            run_first = i
            while i + 1 < len(significant) and significant[i + 1].type == tokenize.STRING:
                i += 1
            run = significant[run_first : i + 1]
            i += 1
            if not any(placeholder_regex.search(t.string) for t in run):
                continue
            for t in run:
                string_prefix = self.STRING_PREFIX_REGEX.match(t.string).group(0).lower()  # type: ignore[union-attr]
                if placeholder_regex.search(t.string) and ("f" in string_prefix or "b" in string_prefix):
                    raise unsupported("f-strings or bytes literals")
            if case_pattern.intersection(range(run_first, i)):
                raise unsupported("match/case patterns")
            if mode == "exec":
                at_statement_start = run_first == 0 or significant[run_first - 1].type in statement_start_types
                at_statement_end = i >= len(significant) or significant[i].type in (
                    tokenize.NEWLINE,
                    tokenize.ENDMARKER,
                ) or significant[i].string == ";"
                if at_statement_start and at_statement_end:
                    raise unsupported("docstrings or bare string statements")
            edits.append((offset(run[0].start), offset(run[-1].end)))

        for start, end in reversed(edits):
            source = f"{source[:start]}{substitute_name}({source[start:end]}){source[end:]}"

        if edits:
            bindings[substitute_name] = substitute
        return source, bindings

    def get_context_data(self, instance_path: InstancePath, base_context={}) -> Dict[str, Any]:
        context: Dict[str, Any] = base_context
        for i in range(len(instance_path)):
            path_item = instance_path[i]
            component_id = path_item["componentId"]
            component = self.component_tree.get_component(component_id)
            if not component:
                continue
            if component.type != "repeater":
                continue
            if i + 1 >= len(instance_path):
                continue
            repeater_instance_path = instance_path[0 : i + 1]
            next_instance_path = instance_path[0 : i + 2]
            instance_number = next_instance_path[-1]["instanceNumber"]
            repeater_object = self.evaluate_field(
                repeater_instance_path,
                "repeaterObject",
                True,
                """{ "a": { "desc": "Option A" }, "b": { "desc": "Option B" } }""",
            )
            key_variable = self.evaluate_field(
                repeater_instance_path, "keyVariable", False, "itemId"
            )
            value_variable = self.evaluate_field(
                repeater_instance_path, "valueVariable", False, "item"
            )

            repeater_items: List[Tuple[Any, Any]] = []
            if isinstance(repeater_object, dict):
                repeater_items = list(repeater_object.items())
            elif isinstance(repeater_object, list):
                repeater_items = list(enumerate(repeater_object))
            else:
                raise ValueError(
                    "Cannot produce context. Repeater object must evaluate to a dictionary."
                )

            context[key_variable] = repeater_items[instance_number][0]
            context[value_variable] = repeater_items[instance_number][1]

        if len(instance_path) > 0:
            context["target"] = instance_path[-1]["componentId"]

        return context

    def set_state(
        self, expr: str, instance_path: InstancePath, value: Any, base_context={}
    ) -> None:
        accessors = self.parse_expression(expr, instance_path, base_context)
        state_ref = self.state

        for accessor in accessors[:-1]:
            if isinstance(state_ref, list):
                state_ref = state_ref[int(accessor)]
            else:
                state_ref = state_ref[accessor]

        if not isinstance(
            state_ref, (writer.core.State, writer.core.WriterState, writer.core.StateProxy, dict)
        ):
            raise ValueError(
                f'Reference "{expr}" cannot be translated to state. Found value of type "{type(state_ref)}".'
            )

        state_ref[accessors[-1]] = value

    def parse_expression(
        self, expr: str, instance_path: Optional[InstancePath] = None, base_context={}
    ) -> List[str]:
        """Returns a list of accessors from an expression."""

        if not isinstance(expr, str):
            raise ValueError(
                f'Expression must be of type string. Value of type "{ type(expr) }" found.'
            )

        accessors: List[str] = []
        s = ""
        level = 0

        i = 0
        while i < len(expr):
            character = expr[i]
            if character == "\\":
                if i + 1 < len(expr):
                    s += expr[i + 1]
                    i += 1
            elif character == ".":
                if level == 0:
                    accessors.append(s)
                    s = ""
                else:
                    s += character
            elif character == "[":
                if level == 0:
                    accessors.append(s)
                    s = ""
                else:
                    s += character
                level += 1
            elif character == "]":
                level -= 1
                if level == 0:
                    s = str(self.evaluate_expression(s, instance_path, base_context))
                else:
                    s += character
            else:
                s += character

            i += 1

        if s:
            accessors.append(s)

        return accessors

    def get_env_variable_value(self, expr: str):
        return os.getenv(expr[1:])

    def evaluate_expression(
        self, expr: str, instance_path: Optional[InstancePath] = None, base_context={}
    ) -> Any:
        context_data = base_context
        result = None
        if instance_path:
            context_data = self.get_context_data(instance_path, base_context)
        context_ref: Any = context_data
        state_ref: Any = self.state.user_state
        accessors: List[str] = self.parse_expression(expr, instance_path, base_context)

        result = self._apply_accessors(accessors, state_ref, context_ref)

        if isinstance(result, writer.core.StateProxy):
            return result.to_dict()

        if result is None and expr.startswith("$"):
            return self.get_env_variable_value(expr)

        return result

    def _apply_accessors(self, accessors: List[str], state_ref: Any, context_ref: Any = None) -> Any:
        if not accessors:
            return state_ref
        
        result = self._apply_accessor(accessors[0], context_ref)
        if result is None:
            result = self._apply_accessor(accessors[0], state_ref)

        for accessor in accessors[1:]:
            result = self._apply_accessor(accessor, result)

        return result

    def _apply_accessor(self, accessor: str, target: Any) -> Any:
        if isinstance(target, (writer.core.StateProxy, dict)):
            return target.get(accessor)
        
        if isinstance(target, list):
            try:
                return target[int(accessor)]
            except IndexError:
                pass
        
        return None