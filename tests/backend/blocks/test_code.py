import sys
import types

import pytest
from writer.blocks.code import CodeBlock
from writer.ss_types import WriterConfigurationError


def test_run_code(session, runner, monkeypatch):
    fake_module = types.ModuleType("fake_writeruserapp")
    fake_module.my_fn = lambda: "Monkeypatched!"
    monkeypatch.setitem(sys.modules, "writeruserapp", fake_module)
    component = session.add_fake_component(
        {
            "code": """
print('hi testing stdout ' + str(test_thing_ee) + my_fn())
set_output("return " + str(test_thing_ee))
"""
        }
    )
    block = CodeBlock(component, runner, {"test_thing_ee": 26})
    block.run()
    assert block.outcome == "success"
    assert block.result == "return 26"


def test_run_invalid_code(session, runner, monkeypatch):
    fake_module = types.ModuleType("fake_writeruserapp")
    fake_module.my_fn = lambda: "Monkeypatched!"
    monkeypatch.setitem(sys.modules, "writeruserapp", fake_module)

    component = session.add_fake_component(
        {
            "code": """
print(1/0)
"""
        }
    )
    block = CodeBlock(component, runner, {})
    with pytest.raises(ZeroDivisionError):
        block.run()
    assert block.outcome == "error"


@pytest.fixture
def fake_userapp(monkeypatch):
    monkeypatch.setitem(sys.modules, "writeruserapp", types.ModuleType("fake_writeruserapp"))


def test_code_templates_are_not_expanded(session, runner, fake_userapp):
    session.session_state["name"] = "x'); set_output('injected') #"
    component = session.add_fake_component(
        {"code": "set_output('@{name}')"}
    )
    block = CodeBlock(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert block.result == "@{name}"


def test_code_template_payload_injection_is_not_executed(session, runner, fake_userapp):
    payload = "x'); import os; state['pwned'] = os.getcwd() #"
    component = session.add_fake_component(
        {"code": "set_output('Hello @{payload}')"}
    )
    block = CodeBlock(component, runner, {"payload": payload})
    block.run()
    assert block.outcome == "success"
    assert block.result == "Hello @{payload}"
    assert session.session_state["pwned"] is None


def test_code_reads_values_from_globals(session, runner, fake_userapp):
    session.session_state["name"] = "x'); set_output('injected') #"
    component = session.add_fake_component(
        {"code": "set_output('Hello ' + state['name'] + ' ' + payload)"}
    )
    block = CodeBlock(component, runner, {"payload": "x') #"})
    block.run()
    assert block.outcome == "success"
    assert block.result == "Hello x'); set_output('injected') # x') #"


def test_code_bare_template_raises_configuration_error(session, runner, fake_userapp):
    component = session.add_fake_component(
        {"code": "set_output(@{payload})"}
    )
    block = CodeBlock(component, runner, {"payload": "1"})
    with pytest.raises(WriterConfigurationError, match="not supported in Python code blocks"):
        block.run()
    assert block.outcome == "error"


def test_code_syntax_error_without_template_is_raised(session, runner, fake_userapp):
    component = session.add_fake_component({"code": "set_output("})
    block = CodeBlock(component, runner, {})
    with pytest.raises(SyntaxError):
        block.run()
    assert block.outcome == "error"


def test_code_unrelated_syntax_error_with_template_literal_is_raised(session, runner, fake_userapp):
    component = session.add_fake_component(
        {"code": "set_output('@{name}')  # @{name}\nif :\n    pass"}
    )
    block = CodeBlock(component, runner, {})
    with pytest.raises(SyntaxError):
        block.run()
    assert block.outcome == "error"
