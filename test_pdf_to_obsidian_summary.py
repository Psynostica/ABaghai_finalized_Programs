"""
Tests for pdf_to_obsidian_summary.py
"""

import os
import sys
import tempfile

import pytest

# Ensure the module can be imported
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pdf_to_obsidian_summary import (
    _is_heading,
    _pick_key_sentences,
    _split_into_sentences,
    build_roman_outline,
    detect_sections,
    extract_abstract,
    extract_authors,
    extract_date,
    extract_key_findings,
    extract_text_from_pdf,
    extract_title,
    generate_summary,
    load_template,
    render_template,
    roman,
)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Roman numeral helper
# ---------------------------------------------------------------------------
class TestRoman:
    def test_basic_values(self):
        assert roman(1) == "I"
        assert roman(4) == "IV"
        assert roman(10) == "X"
        assert roman(14) == "XIV"
        assert roman(20) == "XX"

    def test_out_of_range(self):
        assert roman(21) == "21"
        assert roman(0) == "0"


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------
class TestHeadingDetection:
    def test_known_headings(self):
        assert _is_heading("INTRODUCTION") is True
        assert _is_heading("CONCLUSION") is True
        assert _is_heading("REFERENCES") is True
        assert _is_heading("ASSUMPTIONS") is True
        assert _is_heading("DATA CLEANING") is True

    def test_non_headings(self):
        assert _is_heading("") is False
        assert _is_heading("This is a regular sentence.") is False
        assert _is_heading("ab") is False

    def test_exclusions(self):
        assert _is_heading("Data Fields  Description  Value Example(s)") is False
        assert _is_heading("Data Type: String Object") is False


# ---------------------------------------------------------------------------
# Sentence splitting
# ---------------------------------------------------------------------------
class TestSentenceSplitting:
    def test_basic_split(self):
        text = "First sentence. Second sentence. Third one."
        result = _split_into_sentences(text)
        assert len(result) == 3

    def test_single_sentence(self):
        result = _split_into_sentences("Just one sentence.")
        assert len(result) == 1


class TestPickKeySentences:
    def test_fewer_than_max(self):
        text = "Short text. Only two."
        result = _pick_key_sentences(text, max_sentences=4)
        assert len(result) == 2

    def test_max_limit(self):
        text = "One. Two. Three. Four. Five. Six. Seven."
        result = _pick_key_sentences(text, max_sentences=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------
class TestExtractTitle:
    def test_single_line_title(self):
        text = "Enhancing Drug Safety through Data Management\nAsh Baghai\n8/25/2024"
        assert extract_title(text) == "Enhancing Drug Safety through Data Management"

    def test_multiline_title(self):
        text = (
            "An Exploratory Analysis of Errors in and Relationship between\n"
            "Chromatography Database Calculations\n"
            "DSCI200 August 2024 Project 2 | Ash Baghai\n"
        )
        title = extract_title(text)
        assert "Exploratory Analysis" in title
        assert "Chromatography Database Calculations" in title


class TestExtractAuthors:
    def test_simple_author(self):
        text = "Some Title\nAsh Baghai\n8/25/2024"
        assert extract_authors(text) == "Ash Baghai"

    def test_pipe_format_author(self):
        text = (
            "An Exploratory Analysis of Errors in and Relationship between\n"
            "Chromatography Database Calculations\n"
            "DSCI200 August 2024 Project 2 | Ash Baghai\n"
        )
        assert extract_authors(text) == "Ash Baghai"


class TestExtractDate:
    def test_slash_date(self):
        text = "Title\nAuthor\n8/25/2024\nSome other text"
        assert extract_date(text) == "8/25/2024"

    def test_month_year_date(self):
        text = "Title\nDSCI200 August 2024 Project"
        assert extract_date(text) == "August 2024"

    def test_no_date(self):
        text = "Title\nAuthor\nNo date here"
        assert extract_date(text) == "Unknown"


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------
class TestDetectSections:
    def test_basic_sections(self):
        text = "INTRODUCTION\nSome intro text.\nCONCLUSION\nSome conclusion."
        sections = detect_sections(text)
        headings = [h for h, _ in sections]
        assert "Introduction" in headings
        assert "Conclusion" in headings

    def test_body_captured(self):
        text = "INTRODUCTION\nFirst sentence.\nSecond sentence.\nCONCLUSION\nDone."
        sections = detect_sections(text)
        intro = [b for h, b in sections if h == "Introduction"]
        assert len(intro) == 1
        assert "First sentence" in intro[0]


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
class TestTemplateRendering:
    def test_render_replaces_placeholders(self):
        template = "# {{title}}\nBy {{authors}}"
        result = render_template(template, {"title": "My Paper", "authors": "A. Author"})
        assert result == "# My Paper\nBy A. Author"

    def test_load_template(self):
        template = load_template(os.path.join(REPO_DIR, "obsidian_template.md"))
        assert "{{title}}" in template
        assert "{{content_notes}}" in template


# ---------------------------------------------------------------------------
# Roman numeral outline builder
# ---------------------------------------------------------------------------
class TestBuildRomanOutline:
    def test_basic_outline(self):
        sections = [
            ("Introduction", "This is the intro. It covers background."),
            ("Methods", "We used Python. Data was collected."),
        ]
        outline = build_roman_outline(sections)
        assert "### I. Introduction" in outline
        assert "### II. Methods" in outline

    def test_none_heading_skipped(self):
        sections = [
            (None, "Preamble text"),
            ("Results", "We found things."),
        ]
        outline = build_roman_outline(sections)
        assert "### I. Results" in outline
        assert "Preamble" not in outline


# ---------------------------------------------------------------------------
# Integration: PDF extraction (requires actual PDFs in repo)
# ---------------------------------------------------------------------------
class TestPDFExtraction:
    @pytest.fixture
    def drug_safety_pdf(self):
        path = os.path.join(
            REPO_DIR,
            "ABaghai_Enhancing Drug Safety through Data Management and Analytics.pdf",
        )
        if not os.path.isfile(path):
            pytest.skip("PDF not found in repository")
        return path

    @pytest.fixture
    def chromatography_pdf(self):
        path = os.path.join(
            REPO_DIR,
            "Abaghai_An Exploratory Analysis of Errors in and Relationship between Chromatography Database Calculations.pdf",
        )
        if not os.path.isfile(path):
            pytest.skip("PDF not found in repository")
        return path

    def test_extract_text_drug_safety(self, drug_safety_pdf):
        text, pages, n = extract_text_from_pdf(drug_safety_pdf)
        assert n == 5
        assert len(pages) == 5
        assert "Drug Safety" in text or "drug safety" in text.lower()

    def test_extract_text_chromatography(self, chromatography_pdf):
        text, pages, n = extract_text_from_pdf(chromatography_pdf)
        assert n == 11
        assert len(pages) == 11
        assert "Chromatography" in text

    def test_full_summary_drug_safety(self, drug_safety_pdf):
        summary = generate_summary(drug_safety_pdf)
        assert "Enhancing Drug Safety" in summary
        assert "Ash Baghai" in summary
        assert "### I." in summary
        assert "Content Notes" in summary

    def test_full_summary_chromatography(self, chromatography_pdf):
        summary = generate_summary(chromatography_pdf)
        assert "Chromatography" in summary
        assert "Ash Baghai" in summary
        assert "### I." in summary
        assert "Roman" not in summary or "Content Notes" in summary

    def test_output_file_written(self, drug_safety_pdf):
        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            summary = generate_summary(drug_safety_pdf)
            with open(tmp_path, "w") as f:
                f.write(summary)
            assert os.path.isfile(tmp_path)
            with open(tmp_path) as f:
                content = f.read()
            assert "### I." in content
        finally:
            os.unlink(tmp_path)
