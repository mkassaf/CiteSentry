from __future__ import annotations

from pathlib import Path

# Lazily built and cached: create_model_dict() loads several deep-learning
# (layout/OCR) models, so we pay that cost once per process, not once per PDF.
_converter = None


def _get_converter():
    global _converter
    if _converter is None:
        from marker.config.parser import ConfigParser
        from marker.converters.pdf import PdfConverter
        from marker.models import create_model_dict

        config_parser = ConfigParser({"output_format": "markdown"})
        _converter = PdfConverter(
            config=config_parser.generate_config_dict(),
            artifact_dict=create_model_dict(),
            processor_list=config_parser.get_processors(),
            renderer=config_parser.get_renderer(),
            llm_service=config_parser.get_llm_service(),
        )
    return _converter


def convert_pdf_to_markdown(path: Path) -> str | None:
    """
    Convert a PDF to Markdown using marker (https://github.com/datalab-to/marker).

    Returns None if the optional `marker-pdf` package isn't installed or
    conversion fails for any reason, so callers can fall back to a lighter
    text-extraction backend.
    """
    try:
        from marker.output import text_from_rendered
    except ImportError:
        return None

    try:
        rendered = _get_converter()(str(path))
        text, _, _ = text_from_rendered(rendered)
        return text or None
    except Exception:
        return None
