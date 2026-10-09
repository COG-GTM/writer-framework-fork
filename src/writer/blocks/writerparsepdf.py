import re

from writer.abstract import register_abstract_template
from writer.blocks.base_block import WriterBlock
from writer.ss_types import AbstractTemplate, WriterConfigurationError

UUID_PATTERN = re.compile(
    r"(?:urn:uuid:)?([0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12})", re.IGNORECASE
)


class WriterParsePDFByFileID(WriterBlock):
    @classmethod
    def register(cls, type: str):
        super(WriterParsePDFByFileID, cls).register(type)
        register_abstract_template(
            type,
            AbstractTemplate(
                baseType="blueprints_node",
                writer={
                    "name": "Parse PDF tool",
                    "description": "Uses Writer API to extract the text content of a PDF file stored in Writer cloud.",
                    "category": "Writer",
                    "fields": {
                        "file": {
                                "name": "File",
                                "type": "Text",
                                "default": "",
                                "desc": "UUID of a file object in Files API.",
                                "validator": {
                                    "type": "string",
                                    "format": "uuid"
                                }
                        },
                        "markdown": {
                            "name": "Enable markdown",
                            "type": "Boolean",
                            "default": "yes",
                            "validator": {
                                "type": "boolean",
                            },
                        }
                    },
                    "outs": {
                        "success": {
                            "name": "Success",
                            "description": "The PDF was parsed successfully.",
                            "style": "success",
                        },
                        "error": {
                            "name": "Error",
                            "description": "There was an error parsing the PDF.",
                            "style": "error",
                        },
                    },
                },
            ),
        )

    def run(self):
        try:
            import writer.ai

            file_field = self._get_field("file", required=True)
            uuid_match = (
                UUID_PATTERN.fullmatch(file_field) if isinstance(file_field, str) else None
            )
            if uuid_match is None:
                raise WriterConfigurationError(
                    "The field `file` must be the UUID of a file object in Files API."
                )
            file_uuid = uuid_match.group(1)
            markdown_input = self._get_field("markdown", False, "yes") == "yes"

            client = writer.ai.WriterAIManager.acquire_client()

            response = client.tools.parse_pdf(
                file_uuid,
                format="markdown" if markdown_input else "text"
            )

            self.result = response.content
            self.outcome = "success"

        except BaseException as e:
            self.outcome = "error"
            raise e
