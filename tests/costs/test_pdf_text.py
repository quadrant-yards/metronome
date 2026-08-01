from unittest.mock import MagicMock, patch

from metronome.costs.pdf_text import extract_text


def test_extract_text_joins_pages_with_newlines(tmp_path):
    pdf_path = tmp_path / "invoice.pdf"
    pdf_path.write_bytes(b"")

    page1 = MagicMock()
    page1.extract_text.return_value = "Page one text"
    page2 = MagicMock()
    page2.extract_text.return_value = "Page two text"

    fake_pdf = MagicMock()
    fake_pdf.pages = [page1, page2]
    fake_pdf.__enter__.return_value = fake_pdf
    fake_pdf.__exit__.return_value = False

    with patch("pdfplumber.open", return_value=fake_pdf) as mock_open:
        result = extract_text(pdf_path)

    mock_open.assert_called_once_with(pdf_path)
    assert result == "Page one text\nPage two text"


def test_extract_text_treats_a_page_with_no_extractable_text_as_empty_string(tmp_path):
    pdf_path = tmp_path / "blank.pdf"
    pdf_path.write_bytes(b"")

    blank_page = MagicMock()
    blank_page.extract_text.return_value = None
    text_page = MagicMock()
    text_page.extract_text.return_value = "Some text"

    fake_pdf = MagicMock()
    fake_pdf.pages = [blank_page, text_page]
    fake_pdf.__enter__.return_value = fake_pdf
    fake_pdf.__exit__.return_value = False

    with patch("pdfplumber.open", return_value=fake_pdf):
        result = extract_text(pdf_path)

    assert result == "\nSome text"
