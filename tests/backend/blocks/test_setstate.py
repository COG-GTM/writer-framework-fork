import pytest
from writer.blocks.setstate import SetState
from writer.blueprints import BlueprintRunner
from writer.ss_types import WriterConfigurationError


def test_basic_assignment(session):
    component = session.add_fake_component({"element": "my_element", "value": "my_value"})
    runner = BlueprintRunner(session)
    block = SetState(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert session.session_state["my_element"] == "my_value"


def test_json_assignment(session):
    component = session.add_fake_component(
        {"element": "my_element", "value": '{ "dog": true, "cat": 0 }', "valueType": "JSON"}
    )
    runner = BlueprintRunner(session)
    block = SetState(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert session.session_state["my_element"]["dog"] is True
    assert session.session_state["my_element"]["cat"] == 0


def test_nested_assignment_without_parent(session):
    component = session.add_fake_component(
        {"element": "parent_element.my_element", "value": "my_value"}
    )
    runner = BlueprintRunner(session)
    block = SetState(component, runner, {})
    with pytest.raises(ValueError):
        block.run()
    assert block.outcome == "error"


def test_nested_assignment_with_parent(session, runner):
    session.session_state["parent_element"] = {"sibling_element": "yes"}
    component = session.add_fake_component(
        {"element": "parent_element.my_element", "value": "my_value"}
    )
    block = SetState(component, runner, {})
    block.run()
    assert block.outcome == "success"
    assert session.session_state["parent_element"]["sibling_element"] == "yes"
    assert session.session_state["parent_element"]["my_element"] == "my_value"


def test_assignment_with_empty_element(session):
    component = session.add_fake_component({"element": "", "value": "my_value"})
    runner = BlueprintRunner(session)
    block = SetState(component, runner, {})
    with pytest.raises(ValueError):
        block.run()
    assert block.outcome == "error"


def test_assignment_with_empty_value(session):
    component = session.add_fake_component({"element": "my_element", "value": ""})
    runner = BlueprintRunner(session)
    block = SetState(component, runner, {})
    block.run()
    assert block.outcome == "success"


def test_templated_path_segment_is_literal(session, runner):
    session.session_state["answers"] = {"q1": "keep"}
    component = session.add_fake_component(
        {"element": "answers.@{payload.key}", "value": "my_value"}
    )
    block = SetState(component, runner, {"payload": {"key": "q1.x[$HOME]\\"}})
    block.run()
    assert block.outcome == "success"
    assert session.session_state["answers"]["q1"] == "keep"
    assert session.session_state["answers"]["q1.x[$HOME]\\"] == "my_value"


def test_templated_path_segment(session, runner):
    session.session_state["answers"] = {}
    component = session.add_fake_component(
        {"element": "answers.@{payload.key}", "value": "my_value"}
    )
    block = SetState(component, runner, {"payload": {"key": "q2"}})
    block.run()
    assert block.outcome == "success"
    assert session.session_state["answers"]["q2"] == "my_value"


def test_templated_full_path_env_lookup_is_literal(session, runner, monkeypatch):
    monkeypatch.setenv("WF_TEST_SECRET", "top-secret")
    component = session.add_fake_component({"element": "@{payload}", "value": "my_value"})
    block = SetState(component, runner, {"payload": "$WF_TEST_SECRET"})
    block.run()
    assert session.session_state["$WF_TEST_SECRET"] == "my_value"


def test_template_inside_brackets_is_rejected(session, runner):
    session.session_state["answers"] = {}
    component = session.add_fake_component(
        {"element": "answers[@{payload}]", "value": "my_value"}
    )
    block = SetState(component, runner, {"payload": "$HOME"})
    with pytest.raises(WriterConfigurationError):
        block.run()
    assert block.outcome == "error"


def test_missing_path_error_does_not_leak_accessor_values(session, runner, monkeypatch):
    monkeypatch.setenv("WF_TEST_SECRET", "top-secret")
    session.session_state["parent_element"] = {}
    component = session.add_fake_component(
        {"element": "parent_element[$WF_TEST_SECRET].child", "value": "my_value"}
    )
    block = SetState(component, runner, {})
    with pytest.raises(ValueError) as excinfo:
        block.run()
    assert block.outcome == "error"
    assert "top-secret" not in str(excinfo.value)
