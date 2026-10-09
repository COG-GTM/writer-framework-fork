import contextlib
import json
import logging
import os
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Literal, Optional, Sequence

import writer.abstract
from writer.core import Config
from writer.keyvalue_storage import writer_kv_storage

if TYPE_CHECKING:
    from writer.blueprints import Graph, GraphNode
    from writer.core import Component


logger = logging.getLogger("journal")

JOURNAL_KEY_PREFIX = "wf-journal-"
INIT_LOGS_KEY_PREFIX = "wf-init-logs-"
JOURNAL_KEY_PREFIXES = (JOURNAL_KEY_PREFIX, INIT_LOGS_KEY_PREFIX)

RECORD_PAYLOADS_ENV_VAR = "WRITER_JOURNAL_RECORD_PAYLOADS"
REDACTED = "[REDACTED]"
OMITTED_PAYLOAD = f"[Payload not recorded. Set {RECORD_PAYLOADS_ENV_VAR}=1 to record trigger payloads.]"

_SENSITIVE_KEYS = {
    "authorization",
    "proxyauthorization",
    "cookie",
    "setcookie",
    "privatekey",
    "passwd",
    "credentials",
}
_SENSITIVE_KEY_SUFFIXES = ("apikey", "token", "secret", "password")
_MIN_MASKED_SECRET_LENGTH = 4


def is_journal_key(key: str) -> bool:
    return key.startswith(JOURNAL_KEY_PREFIXES)


def is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    normalized = "".join(ch for ch in key.lower() if ch.isalnum())
    return normalized in _SENSITIVE_KEYS or normalized.endswith(_SENSITIVE_KEY_SUFFIXES)


def _collect_strings(value: Any) -> List[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _collect_strings(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _collect_strings(v)]
    return []


def get_vault_secret_values() -> List[str]:
    from writer.vault import writer_vault

    try:
        secrets = writer_vault.get_secrets()
    except Exception:
        logger.warning("Couldn't load vault secrets to redact the Journal entry")
        secrets = {}
    values = {s for s in _collect_strings(secrets) if len(s) >= _MIN_MASKED_SECRET_LENGTH}
    return sorted(values, key=len, reverse=True)


def mask_secret_values(text: str, secret_values: Sequence[str]) -> str:
    for secret in secret_values:
        if secret in text:
            text = text.replace(secret, REDACTED)
    return text


def should_record_payloads() -> bool:
    if Config.mode == "edit":
        return True
    return os.getenv(RECORD_PAYLOADS_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


class JournalRecord:
    def __init__(
        self,
        execution_environment: Dict,
        title: str,
        graph: "Graph"
    ):
        from writer import core_ui

        self.started_at = datetime.now(timezone.utc)
        self.instance_type = "editor" if Config.mode == "edit" else "agent"

        # Get blueprint_id from the parent of any node in the graph
        # All nodes in a blueprint share the same parent blueprint component
        self.blueprint_id = graph.nodes[0].component.parentId if graph.nodes else None

        self.execution_environment = execution_environment
        self.trigger = {
            "event": execution_environment.get("context", {}).get("event"),
            "payload": execution_environment.get("payload") if should_record_payloads() else OMITTED_PAYLOAD,
            "component": {}
        }

        if self.trigger["event"] == "wf-run-blueprint":
            self.trigger["component"]["type"] = "blueprint"
            self.trigger["component"]["id"] = self.blueprint_id
            blueprint_component = core_ui.current_component_tree().get_component(self.trigger["component"]["id"])
            if blueprint_component is not None:
                self.trigger["component"]["title"] = blueprint_component.content.get("key")
        else:
            self.trigger["component"]["type"] = "block"
            component = graph.get_start_nodes()[0].component
            self.trigger["component"]["id"] = component.id
            self.trigger["component"]["title"] = self._get_block_info(component)["title"]

        if "API" in title:
            self.trigger["type"] = "API"
        elif "Cron" in title:
            self.trigger["type"] = "Cron"
        elif "UI" in title:
            self.trigger["type"] = "UI"
        else:
            self.trigger["type"] = "On demand"

        self.graph = graph
        self.block_outputs: Dict[str, Any] = {}
        for graph_node in self.graph.nodes:
            block_info = self._get_block_info(graph_node.component)
            self.block_outputs[graph_node.id] = {
                "component": {
                    "type": graph_node.component.type,
                    "id": graph_node.component.id,
                    "title": block_info["title"],
                    "category": block_info["category"]
                },
                "executions": []
            }

        self.is_runable = True
        self.result: Optional[Literal["success", "error", "stopped"]] = None

    def _get_block_info(self, component: "Component") -> Dict[str, str]:
        block_title = component.content.get("alias")
        component_definition = writer.abstract.templates.get(component.type)

        # If component has an alias, use it as title
        if block_title is not None:
            category = "Unknown category"
            if component_definition is not None:
                category = component_definition.writer.get("category", "Unknown category")
            return {
                "title": block_title,
                "category": category
            }

        # If no component definition found, return defaults
        if component_definition is None:
            return {
                "title": "Unknown block",
                "category": "Unknown category"
            }

        # Use component definition for both title and category
        return {
            "title": component_definition.writer.get("name", "Unknown block"),
            "category": component_definition.writer.get("category", "Unknown category")
        }

    def to_dict(self) -> Dict[str, Any]:
        block_outputs = deepcopy(self.block_outputs)
        for graph_node in self.graph.nodes:
            block_outputs[graph_node.id]["executions"].append(self.get_execution_data(graph_node))

        data = {
            "timestamp": self.started_at.isoformat(),
            "instanceType": self.instance_type,
            "blueprintId": self.blueprint_id,
            "trigger": self.trigger,
            "blockOutputs": block_outputs,
            "result": self.result,
        }
        sanitized_data = self._sanitize_data(data, get_vault_secret_values())
        return {
            **sanitized_data,
            "isRunable": self.is_runable,
        }

    def get_execution_data(self, graph_node: "GraphNode") -> Dict[str, Any]:
        result = graph_node.result
        if graph_node.outcome == "trigger" and not should_record_payloads():
            result = OMITTED_PAYLOAD
        execution_data: Dict[str, Any] = {
            "result": result,
            "outcome": graph_node.outcome,
        }

        # Add timing information if available
        if graph_node.tool:
            if hasattr(graph_node.tool, 'started_at') and graph_node.tool.started_at >= 0:
                execution_data["startedAt"] = graph_node.tool.started_at
            if hasattr(graph_node.tool, 'execution_time_in_seconds') and graph_node.tool.execution_time_in_seconds >= 0:
                execution_data["executionTimeInSeconds"] = graph_node.tool.execution_time_in_seconds

            # Add captured logs if available
            if hasattr(graph_node.tool, 'captured_stdout') and graph_node.tool.captured_stdout:
                execution_data["stdout"] = graph_node.tool.captured_stdout
            if hasattr(graph_node.tool, 'captured_logs') and graph_node.tool.captured_logs:
                execution_data["logs"] = graph_node.tool.captured_logs

            # Add error message if available (contains the traceback for errors)
            if hasattr(graph_node.tool, 'message') and graph_node.tool.message:
                execution_data["message"] = graph_node.tool.message

        return execution_data

    def _sanitize_data(self, data, secret_values: Sequence[str] = ()):
        if data is None:
            return None

        if isinstance(data, list):
            return [self._sanitize_data(item, secret_values) for item in data]
        if isinstance(data, dict):
            return {
                k: REDACTED if is_sensitive_key(k) and v is not None else self._sanitize_data(v, secret_values)
                for k, v in data.items()
            }
        if isinstance(data, str):
            return mask_secret_values(data, secret_values)
        if isinstance(data, (int, float, bool)):
            return data

        try:
            serializable = json.loads(json.dumps(data))
        except (TypeError, OverflowError):
            self.is_runable = False
            return f"Can't be displayed in the Journal. Value of type: {str(type(data))}."
        return self._sanitize_data(serializable, secret_values)

    def construct_key(self) -> str:
        return f"{JOURNAL_KEY_PREFIX}{self.instance_type[0]}-{int(self.started_at.timestamp() * 1000)}"
    
    def set_result(self, result: Literal["success", "error", "stopped"]) -> None:
        self.result = result

    def add_nested_execution(self, nested_record: "JournalRecord") -> None:
        for graph_node in nested_record.graph.nodes:
            if graph_node.id not in self.block_outputs:
                self.block_outputs[graph_node.id] = nested_record.block_outputs[graph_node.id]
            self.block_outputs[graph_node.id]["executions"].append(nested_record.get_execution_data(graph_node))
    
    def save(self) -> None:
        if "journal" not in Config.feature_flags or not writer_kv_storage.is_accessible():
            return
        data = self.to_dict()
        writer_kv_storage.save(self.construct_key(), data)


_parent_journal_record: ContextVar[Optional[JournalRecord]] = ContextVar("parent_journal_record", default=None)
_current_journal_record: ContextVar[Optional[JournalRecord]] = ContextVar("current_journal_record", default=None)

@contextlib.contextmanager
def use_journal_record_context(
    execution_environment: Dict,
    title: str,
    graph: "Graph"
):
    parent_record = _parent_journal_record.get()
    current_record = JournalRecord(execution_environment, title, graph)
    _current_journal_record.set(current_record)
    if parent_record is None:
        _parent_journal_record.set(current_record)

    try:
        yield current_record
    except BaseException as e:
        current_record.set_result("error")
        raise e
    finally:
        _current_journal_record.set(None)
        if parent_record is not None:
            parent_record.add_nested_execution(current_record)
        else:
            try:
                current_record.save()
            except Exception:
                logger.exception("Failed to save a Journal entry")
            _parent_journal_record.set(None)


def get_current_journal_record() -> Optional[JournalRecord]:
    return _current_journal_record.get()
