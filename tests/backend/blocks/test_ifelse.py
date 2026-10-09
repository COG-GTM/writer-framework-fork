import itertools
import sys
import types

import pytest
from writer.blocks.ifelse import IfElseBlock
from writer.ss_types import WriterConfigurationError

INJECTION = "\" or state.__setitem__(\"pwned\", True) or \""
component_ids = itertools.count()


@pytest.fixture(autouse=True)
def fake_user_app(monkeypatch):
    fake_module = types.ModuleType("fake_writeruserapp")
    fake_module.limit = 10
    monkeypatch.setitem(sys.modules, "writeruserapp", fake_module)


def run_expression(session, runner, expression, execution_environment=None):
    component = session.add_fake_component(
        {"expression": expression}, id=f"ifelse_{next(component_ids)}"
    )
    block = IfElseBlock(component, runner, execution_environment or {})
    block.run()
    return block


def test_expression_true(session, runner):
    session.session_state["counter"] = 11
    block = run_expression(session, runner, 'state["counter"] > limit')
    assert block.outcome == "true"


def test_expression_false(session, runner):
    session.session_state["counter"] = 3
    block = run_expression(session, runner, 'state["counter"] > limit')
    assert block.outcome == "false"


def test_payload_variable(session, runner):
    block = run_expression(session, runner, 'payload == "yes"', {"payload": "yes"})
    assert block.outcome == "true"


def test_quoted_template_compares_text(session, runner):
    block = run_expression(session, runner, '"@{payload}" == "yes"', {"payload": "yes"})
    assert block.outcome == "true"
    block = run_expression(session, runner, '"@{payload}" == "yes"', {"payload": "no"})
    assert block.outcome == "false"


def test_quoted_template_does_not_inject_code(session, runner):
    block = run_expression(session, runner, '"@{payload}" == "yes"', {"payload": INJECTION})
    assert block.outcome == "false"
    assert "pwned" not in session.session_state


def test_single_quoted_and_embedded_templates(session, runner):
    block = run_expression(
        session, runner, "'Hi @{payload}!' == \"Hi \" + payload + \"!\"", {"payload": INJECTION}
    )
    assert block.outcome == "true"
    assert "pwned" not in session.session_state


def test_unquoted_template_is_a_value_not_code(session, runner):
    block = run_expression(
        session, runner, "@{payload} == 'state.__setitem__(\"pwned\", True)'",
        {"payload": 'state.__setitem__("pwned", True)'},
    )
    assert block.outcome == "true"
    assert "pwned" not in session.session_state


def test_full_template_is_a_value_not_code(session, runner):
    block = run_expression(session, runner, "@{payload}", {"payload": "False"})
    # Non-empty string, so truthy; it's no longer evaluated as source.
    assert block.outcome == "true"
    block = run_expression(session, runner, "@{payload}", {"payload": False})
    assert block.outcome == "false"


def test_numeric_template(session, runner):
    session.session_state["counter"] = 11
    block = run_expression(session, runner, "@{counter} > 10")
    assert block.outcome == "true"


def test_non_string_template_in_quotes_is_json(session, runner):
    session.session_state["tags"] = ["a", "b"]
    block = run_expression(session, runner, "'@{tags}' == '[\"a\", \"b\"]'")
    assert block.outcome == "true"


def test_escaped_template_is_left_as_is(session, runner):
    block = run_expression(session, runner, "r'\\@{payload}' == chr(92) + '@' + '{payload}'", {"payload": "x"})
    assert block.outcome == "true"


def test_template_in_fstring_rejected(session, runner):
    with pytest.raises(WriterConfigurationError):
        run_expression(session, runner, 'f"@{payload}" == "yes"', {"payload": "yes"})


def test_dangerous_builtins_unavailable(session, runner):
    with pytest.raises(NameError):
        run_expression(session, runner, "__import__('os').getcwd()")
    with pytest.raises(NameError):
        run_expression(session, runner, "eval('1')")
    block = run_expression(session, runner, "len([1, 2]) == 2 and any([0, 1])")
    assert block.outcome == "true"


def test_invalid_expression(session, runner):
    with pytest.raises(SyntaxError):
        run_expression(session, runner, "x = 1")


def test_template_in_triple_quoted_string_with_quotes(session, runner):
    block = run_expression(
        session, runner, "'''it's @{payload}''' == \"it's \" + payload", {"payload": INJECTION}
    )
    assert block.outcome == "true"
    assert "pwned" not in session.session_state


def test_template_in_implicitly_concatenated_strings(session, runner):
    block = run_expression(
        session, runner, "('a' \"@{payload}\"\n  'b') == 'a' + payload + 'b'", {"payload": INJECTION}
    )
    assert block.outcome == "true"
    assert "pwned" not in session.session_state


def test_template_in_bytes_rejected(session, runner):
    with pytest.raises(WriterConfigurationError):
        run_expression(session, runner, "b'@{payload}' == b'x'", {"payload": "x"})


def test_non_json_template_values(session, runner):
    block = run_expression(session, runner, "@{result} == b'ok'", {"result": b"ok"})
    assert block.outcome == "true"


def test_whole_quoted_template_expression(session, runner):
    block = run_expression(session, runner, '"@{payload}"', {"payload": INJECTION})
    assert block.outcome == "true"
    assert "pwned" not in session.session_state
