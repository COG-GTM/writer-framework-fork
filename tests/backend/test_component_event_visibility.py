import json

import pytest
import writer as wf
from writer.core import Config, EventHandler
from writer.core_ui import Component
from writer.evaluator import Evaluator
from writer.ss_types import WriterEvent

from tests.backend.fixtures import core_ui_fixtures

HIDDEN = {"expression": False, "binding": "", "reversed": False}


def _custom(binding, reversed=False):
    return {"expression": "custom", "binding": binding, "reversed": reversed}


PAYLOADS = {"wf-click": {"ctrlKey": True}}


def _click_binding():
    return {"eventType": "wf-click", "stateRef": "clicked"}


def _path(*component_ids, instance_numbers=None):
    numbers = instance_numbers or [0] * len(component_ids)
    return [
        {"componentId": component_id, "instanceNumber": number}
        for component_id, number in zip(component_ids, numbers)
    ]


def _components():
    return [
        Component(id="page1", parentId="root", type="page", content={"key": "main"}),
        Component(id="public_btn", parentId="page1", type="button", binding=_click_binding()),
        Component(
            id="admin_btn",
            parentId="page1",
            type="button",
            binding=_click_binding(),
            visible=_custom("is_admin"),
        ),
        Component(
            id="guest_btn",
            parentId="page1",
            type="button",
            binding=_click_binding(),
            visible=_custom("is_admin", reversed=True),
        ),
        Component(id="hidden_section", parentId="page1", type="section", visible=HIDDEN),
        Component(id="nested_btn", parentId="hidden_section", type="button", binding=_click_binding()),
        Component(id="hidden_page", parentId="root", type="page", visible=HIDDEN),
        Component(id="hidden_page_btn", parentId="hidden_page", type="button", binding=_click_binding()),
        Component(
            id="hidden_page_timer",
            parentId="hidden_page",
            type="timer",
            binding={"eventType": "wf-tick", "stateRef": "clicked"},
        ),
        Component(id="reuse1", parentId="page1", type="reuse", content={"proxyId": "nested_btn"}),
        Component(
            id="repeater1",
            parentId="page1",
            type="repeater",
            content={
                "repeaterObject": "@{rows}",
                "keyVariable": "rowId",
                "valueVariable": "row",
            },
        ),
        Component(
            id="row_btn",
            parentId="repeater1",
            type="button",
            binding=_click_binding(),
            visible=_custom("row.enabled"),
        ),
        Component(
            id="active_timer",
            parentId="hidden_section",
            type="timer",
            binding={"eventType": "wf-tick", "stateRef": "clicked"},
        ),
        Component(
            id="inactive_timer",
            parentId="hidden_section",
            type="timer",
            content={"isActive": "no"},
            binding={"eventType": "wf-tick", "stateRef": "clicked"},
        ),
    ]


@pytest.fixture
def session():
    session = wf.session_manager.get_new_session()
    session.session_component_tree = core_ui_fixtures.build_fake_component_tree(
        _components(), init_root=True
    )
    session.session_state["is_admin"] = False
    session.session_state["clicked"] = "unset"
    session.session_state["rows"] = [{"enabled": True}, {"enabled": False}]
    return session


def _fire(session, instance_path, event_type="wf-click"):
    handler = EventHandler(session)
    return handler.handle(
        WriterEvent(type=event_type, instancePath=instance_path, payload=PAYLOADS.get(event_type))
    )


def _assert_rejected(session, instance_path, event_type="wf-click"):
    result = _fire(session, instance_path, event_type)
    assert result["ok"] is False
    assert session.session_state["clicked"] == "unset"


def _assert_accepted(session, instance_path, event_type="wf-click"):
    result = _fire(session, instance_path, event_type)
    assert result["ok"] is True, result
    assert session.session_state["clicked"] != "unset"


def test_visible_component_event_is_handled(session):
    _assert_accepted(session, _path("root", "page1", "public_btn"))


def test_component_hidden_by_binding_is_rejected(session):
    _assert_rejected(session, _path("root", "page1", "admin_btn"))


def test_component_shown_by_binding_is_handled(session):
    session.session_state["is_admin"] = True
    _assert_accepted(session, _path("root", "page1", "admin_btn"))


def test_reversed_binding_shows_component_when_falsy(session):
    _assert_accepted(session, _path("root", "page1", "guest_btn"))


def test_reversed_binding_hides_component_when_truthy(session):
    session.session_state["is_admin"] = True
    _assert_rejected(session, _path("root", "page1", "guest_btn"))


def test_component_with_hidden_ancestor_is_rejected(session):
    _assert_rejected(session, _path("root", "page1", "hidden_section", "nested_btn"))


def test_component_on_hidden_page_is_rejected(session):
    _assert_rejected(session, _path("root", "hidden_page", "hidden_page_btn"))


@pytest.mark.parametrize(
    "instance_path",
    [
        _path("nested_btn"),
        _path("root", "nested_btn"),
        _path("root", "page1", "nested_btn"),
        _path("page1", "public_btn"),
        _path("root", "page1", "unknown", "public_btn"),
        _path("root", "page1", "public_btn", instance_numbers=[0, 0, -1]),
    ],
)
def test_instance_path_not_following_the_tree_is_rejected(session, instance_path):
    _assert_rejected(session, instance_path)


def test_unknown_target_is_rejected(session):
    _assert_rejected(session, _path("root", "page1", "missing"))


def test_reused_component_is_handled_through_its_reuse(session):
    _assert_accepted(session, _path("root", "page1", "reuse1", "nested_btn"))


def test_reuse_cannot_proxy_a_different_component(session):
    _assert_rejected(session, _path("root", "page1", "reuse1", "hidden_page_btn"))


def test_repeater_instance_visibility_uses_its_context(session):
    _assert_rejected(
        session,
        _path("root", "page1", "repeater1", "row_btn", instance_numbers=[0, 0, 0, 1]),
    )
    _assert_accepted(
        session,
        _path("root", "page1", "repeater1", "row_btn", instance_numbers=[0, 0, 0, 0]),
    )


def test_out_of_range_repeater_instance_is_rejected(session):
    _assert_rejected(
        session,
        _path("root", "page1", "repeater1", "row_btn", instance_numbers=[0, 0, 0, 5]),
    )


def test_active_timer_ticks_while_hidden(session):
    _assert_accepted(
        session, _path("root", "page1", "hidden_section", "active_timer"), "wf-tick"
    )


def test_active_timer_on_hidden_page_is_rejected(session):
    _assert_rejected(session, _path("root", "hidden_page", "hidden_page_timer"), "wf-tick")


def test_inactive_hidden_timer_is_rejected(session):
    _assert_rejected(
        session, _path("root", "page1", "hidden_section", "inactive_timer"), "wf-tick"
    )


def test_hidden_timer_only_bypasses_visibility_for_ticks(session):
    session.session_component_tree.get_component("active_timer").binding = _click_binding()
    _assert_rejected(session, _path("root", "page1", "hidden_section", "active_timer"))


def test_edit_mode_does_not_enforce_visibility(session, monkeypatch):
    monkeypatch.setattr(Config, "mode", "edit")
    _assert_accepted(session, _path("root", "page1", "hidden_section", "nested_btn"))


def test_visibility_truthiness_matches_the_frontend(session):
    evaluator = Evaluator(session.session_state, session.session_component_tree)
    path = _path("root", "page1", "admin_btn")
    for value, expected in [
        ([], True),
        ({}, True),
        ("0", True),
        (0, False),
        ("", False),
        (None, False),
        (float("nan"), False),
    ]:
        session.session_state["is_admin"] = value
        assert evaluator.is_component_visible(path) is expected, value


def test_repeater_object_as_json_string(session):
    session.session_component_tree.get_component("repeater1").content["repeaterObject"] = json.dumps(
        {"a": {"enabled": False}}
    )
    _assert_rejected(
        session,
        _path("root", "page1", "repeater1", "row_btn"),
    )
