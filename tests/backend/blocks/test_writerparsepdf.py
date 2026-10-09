from unittest.mock import MagicMock, patch

import pytest

from writer.blocks.writerparsepdf import WriterParsePDFByFileID
from writer.ss_types import WriterConfigurationError


@pytest.mark.asyncio
async def test_parse_pdf_by_file_id_success_markdown(session, runner):
    file_id = "3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42"

    with patch("writer.ai.WriterAIManager.acquire_client") as mock_client:
        mock_response = MagicMock()
        mock_response.content = "## Parsed Markdown Output"
        mock_client.return_value.tools.parse_pdf.return_value = mock_response

        component = session.add_fake_component({})
        block = WriterParsePDFByFileID(component, runner, {})
        block._get_field = lambda name, *args, **kwargs: file_id if name == "file" else "yes"

        block.run()

        mock_client.return_value.tools.parse_pdf.assert_called_once_with(file_id, format="markdown")
        assert block.result == "## Parsed Markdown Output"
        assert block.outcome == "success"


@pytest.mark.asyncio
async def test_parse_pdf_by_file_id_success_plain_text(session, runner):
    file_id = "A1B2C3D4-E5F6-4789-8ABC-DEF012345678"

    with patch("writer.ai.WriterAIManager.acquire_client") as mock_client:
        mock_response = MagicMock()
        mock_response.content = "Plain text output"
        mock_client.return_value.tools.parse_pdf.return_value = mock_response

        component = session.add_fake_component({})
        block = WriterParsePDFByFileID(component, runner, {})
        block._get_field = lambda name, *args, **kwargs: file_id if name == "file" else "no"

        block.run()

        mock_client.return_value.tools.parse_pdf.assert_called_once_with(file_id, format="text")
        assert block.result == "Plain text output"
        assert block.outcome == "success"


@pytest.mark.asyncio
async def test_parse_pdf_by_file_id_error(session, runner):
    file_id = "0b8f6a52-1c3d-4e7f-a9b0-c2d4e6f80a1b"

    with patch("writer.ai.WriterAIManager.acquire_client") as mock_client:
        mock_client.return_value.tools.parse_pdf.side_effect = Exception("Parse failed")

        component = session.add_fake_component({})
        block = WriterParsePDFByFileID(component, runner, {})
        block._get_field = lambda name, *args, **kwargs: file_id if name == "file" else "yes"

        with pytest.raises(Exception, match="Parse failed"):
            block.run()
        assert block.outcome == "error"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file_id",
    [
        "../../v1/files",
        "3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42/../../files",
        "3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42?format=text",
        "3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42#",
        "3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42\n",
        "{3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42}",
        "3f2b1c9e8d4a4b6f9e217a5c0d8e1f42",
        "file-uuid-456",
        {"id": "3f2b1c9e-8d4a-4b6f-9e21-7a5c0d8e1f42"},
    ],
)
async def test_parse_pdf_by_file_id_rejects_non_uuid(session, runner, file_id):
    with patch("writer.ai.WriterAIManager.acquire_client") as mock_client:
        component = session.add_fake_component({})
        block = WriterParsePDFByFileID(component, runner, {})
        block._get_field = lambda name, *args, **kwargs: file_id if name == "file" else "yes"

        with pytest.raises(WriterConfigurationError, match="UUID"):
            block.run()

        mock_client.return_value.tools.parse_pdf.assert_not_called()
        assert block.outcome == "error"


@pytest.mark.asyncio
async def test_parse_pdf_by_file_id_requires_file(session, runner):
    with patch("writer.ai.WriterAIManager.acquire_client") as mock_client:
        component = session.add_fake_component({"file": ""})
        block = WriterParsePDFByFileID(component, runner, {})

        with pytest.raises(WriterConfigurationError, match="required"):
            block.run()

        mock_client.return_value.tools.parse_pdf.assert_not_called()
        assert block.outcome == "error"
