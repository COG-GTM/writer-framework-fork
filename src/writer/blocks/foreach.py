import os

from writer.abstract import register_abstract_template
from writer.blocks.base_block import BlueprintBlock
from writer.ss_types import AbstractTemplate, WriterConfigurationError

DEFAULT_MAX_ITEMS = 1000
DEFAULT_MAX_TOTAL_ITERATIONS = 10000
FANOUT_ENV_KEY = "foreach_fanout"


def _limit_from_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def max_items() -> int:
    return _limit_from_env("WRITER_FOREACH_MAX_ITEMS", DEFAULT_MAX_ITEMS)


def max_total_iterations() -> int:
    return _limit_from_env("WRITER_FOREACH_MAX_TOTAL_ITERATIONS", DEFAULT_MAX_TOTAL_ITERATIONS)


class ForEach(BlueprintBlock):
    @classmethod
    def register(cls, type: str):
        super(ForEach, cls).register(type)
        register_abstract_template(
            type,
            AbstractTemplate(
                baseType="blueprints_node",
                writer={
                    "name": "For-each loop",
                    "description": "Loops through each item in a list to run the same logic.",
                    "category": "Logic",
                    "fields": {
                        "items": {
                            "name": "Items",
                            "desc": "The item value will be passed in the execution environment. It will be available at @{item}, and its ID at @{itemId}. You can use either a list or a dictionary. At most 1000 items are allowed by default (WRITER_FOREACH_MAX_ITEMS).",
                            "default": "[]",
                            "init": '["France", "Poland"]',
                            "type": "Object",
                            "control": "Textarea",
                        },
                        "prefix": {
                            "name": "Prefix",
                            "type": "Text",
                            "desc": "If set, the item will be available at @{prefix_item} and the item id at @{prefix_itemId}.",
                        },
                    },
                    "outs": {
                        "loop": {
                            "name": "Loop",
                            "description": "Connect the branch that you'd like to loop on. The branch plugged in here will be executed once per item.",
                            "style": "dynamic",
                        },
                        "success": {
                            "name": "Success",
                            "description": "The branch referenced executed successfully for each item.",
                            "style": "success",
                        },
                        "error": {
                            "name": "Error",
                            "description": "The branch referenced has failed for at least one of the items.",
                            "style": "error",
                        },
                    },
                },
            ),
        )

    def run(self):
        try:
            items = self._get_field("items", as_json=True)
            prefix = str(self._get_field("prefix", as_json=False, default_field_value="")).strip()
            if prefix:
                prefix += "_"
            base_execution_environment = self.execution_environment

            if not isinstance(items, (list, dict)):
                raise ValueError("Items must be a list or dictionary.")

            fanout = self._check_limits(len(items), base_execution_environment)
            base_execution_environment = base_execution_environment | {FANOUT_ENV_KEY: fanout}

            if isinstance(items, list):
                blueprint_environments = [
                    base_execution_environment | {f"{prefix}itemId": i, f"{prefix}item": item}
                    for i, item in enumerate(items)
                ]

                results = self.runner.run_branch_batch(
                    self.component.id, "loop", blueprint_environments
                )
                self.result = results  # Return as a list

            elif isinstance(items, dict):
                blueprint_environments = {
                    str(item_id): base_execution_environment
                    | {f"{prefix}itemId": str(item_id), f"{prefix}item": item}
                    for item_id, item in items.items()
                }
                results = self.runner.run_branch_batch(
                    self.component.id, "loop", list(blueprint_environments.values())
                )
                self.result = {
                    item_id: results[i] for i, item_id in enumerate(blueprint_environments.keys())
                }

            self.outcome = "success"
        except BaseException as e:
            self.outcome = "error"
            raise e

    def _check_limits(self, item_count: int, execution_environment: dict) -> int:
        limit = max_items()
        if item_count > limit:
            raise WriterConfigurationError(
                f"For-each loop received {item_count} items, which exceeds the maximum of "
                f"{limit}. Reduce the number of items or raise WRITER_FOREACH_MAX_ITEMS."
            )

        parent_fanout = execution_environment.get(FANOUT_ENV_KEY, 1)
        if not isinstance(parent_fanout, int) or isinstance(parent_fanout, bool) or parent_fanout < 1:
            parent_fanout = 1
        fanout = parent_fanout * max(item_count, 1)
        total_limit = max_total_iterations()
        if fanout > total_limit:
            raise WriterConfigurationError(
                f"Nested for-each loops would run {fanout} iterations, which exceeds the maximum "
                f"of {total_limit}. Reduce the number of items or raise "
                "WRITER_FOREACH_MAX_TOTAL_ITERATIONS."
            )
        return fanout
