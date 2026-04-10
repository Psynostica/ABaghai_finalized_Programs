"""
PDF Journal Article to Obsidian Summary Generator
===================================================
Extracts text from a PDF journal article and generates a comprehensive
Obsidian-compatible markdown summary using Roman numeral outline format.

Usage:
    python pdf_to_obsidian_summary.py <pdf_file> [--output <output_file>] [--template <template_file>]

Examples:
    python pdf_to_obsidian_summary.py article.pdf
    python pdf_to_obsidian_summary.py article.pdf --output my_summary.md
    python pdf_to_obsidian_summary.py article.pdf --template my_template.md
"""

import argparse
import os
import re
import sys
from datetime import datetime

import PyPDF2


# ---------------------------------------------------------------------------
# Roman numeral helpers
# ---------------------------------------------------------------------------
ROMAN_NUMERALS = [
    "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X",
    "XI", "XII", "XIII", "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX",
]


def roman(n):
    """Return the Roman numeral string for integer *n* (1-based)."""
    if 1 <= n <= len(ROMAN_NUMERALS):
        return ROMAN_NUMERALS[n - 1]
    return str(n)


# ---------------------------------------------------------------------------
# PDF text extraction
# ---------------------------------------------------------------------------
def extract_text_from_pdf(pdf_path):
    """Read *pdf_path* and return (full_text, per_page_texts, num_pages)."""
    with open(pdf_path, "rb") as fh:
        reader = PyPDF2.PdfReader(fh)
        num_pages = len(reader.pages)
        page_texts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            page_texts.append(text)
    full_text = "\n".join(page_texts)
    return full_text, page_texts, num_pages


# ---------------------------------------------------------------------------
# Section detection
# ---------------------------------------------------------------------------

# Patterns that typically denote a section heading in academic papers
_HEADING_PATTERNS = [
    # ALL-CAPS lines (at least two words, or a single known keyword)
    re.compile(
        r"^(?:ABSTRACT|INTRODUCTION|BACKGROUND|METHODS?|METHODOLOGY|"
        r"RESULTS?|DISCUSSION|CONCLUSIONS?|REFERENCES?|ACKNOWLEDGEMENTS?|"
        r"APPENDIX|APPENDICES|DATA\b.*|STUDY DESIGN|HYPOTHES[IE]S|"
        r"POTENTIAL RISKS|DEFINITIONS?|ASSUMPTIONS?|QUESTIONS?|"
        r"OUTCOME|DATA CLEANING|GITHUB REPO|DATA SOURCE|"
        r"NETWORK .* ANALYSIS|CLUSTER ANALYSIS|"
        r"EXISTING LITERATURE|ANTICIPATED IMPACT|OVERVIEW|"
        r"RESEARCH QUESTIONS?|ERROR DETECTION.*|"
        r"IDENTIFYING CUSTOM FIELD.*|NETWORK CENTRALITY.*|"
        r"NETWORK GRAPH.*)\s*$",
        re.IGNORECASE,
    ),
    # Lines that are entirely uppercase, at least 4 chars, and look like
    # actual headings (not table headers or data descriptions)
    re.compile(r"^[A-Z][A-Z &,:\-]{3,}$"),
]

# Patterns that should NOT be treated as headings even if they match
_HEADING_EXCLUSIONS = [
    re.compile(r"^Data Fields", re.IGNORECASE),
    re.compile(r"^Data Type", re.IGNORECASE),
    re.compile(r"^Value Example", re.IGNORECASE),
    re.compile(r"^Size \d", re.IGNORECASE),
    re.compile(r"^Primary Data", re.IGNORECASE),
    re.compile(r"^Column Name", re.IGNORECASE),
    re.compile(r"^Description\s+The", re.IGNORECASE),
]

# Sub-section patterns (mixed-case bold-style or numbered headings)
_SUBHEADING_PATTERNS = [
    re.compile(r"^(?:Sub[- ]?Questions|Main Research Question|Null Hypothesis|"
               r"Alternative Hypothesis|Descriptive Phase|Modeling Phase|"
               r"Mismatch Detection.*|Recursive Analysis.*|"
               r"Network Graph Analysis|Network Centrality Analysis|"
               r"Cluster Analysis|Custom Field .*|Intended Audience|"
               r"Existing Literature|Anticipated Impact)\s*$", re.IGNORECASE),
    # Numbered headings like "1. Something" or "1) Something"
    re.compile(r"^\d+[.)]\s+[A-Z]"),
]


def _is_heading(line):
    """Return True if *line* looks like a major section heading."""
    stripped = line.strip()
    if not stripped or len(stripped) < 3:
        return False
    # Check exclusions first
    for pat in _HEADING_EXCLUSIONS:
        if pat.match(stripped):
            return False
    for pat in _HEADING_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def _is_subheading(line):
    """Return True if *line* looks like a sub-section heading."""
    stripped = line.strip()
    if not stripped:
        return False
    for pat in _SUBHEADING_PATTERNS:
        if pat.match(stripped):
            return True
    return False


def detect_sections(full_text):
    """Split *full_text* into a list of (heading, body_text) tuples."""
    lines = full_text.splitlines()
    sections = []
    current_heading = None
    current_body_lines = []

    for line in lines:
        if _is_heading(line):
            # Save previous section
            if current_heading is not None or current_body_lines:
                sections.append((current_heading, "\n".join(current_body_lines).strip()))
            current_heading = line.strip().title()
            current_body_lines = []
        else:
            current_body_lines.append(line)

    # Last section
    if current_heading is not None or current_body_lines:
        sections.append((current_heading, "\n".join(current_body_lines).strip()))

    return sections


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------
def extract_title(full_text):
    """Heuristic: the title is typically the first non-blank line(s).

    Handles titles that span multiple lines before the author/date line.
    """
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]
    if not lines:
        return "Untitled"

    title_parts = [lines[0]]

    for line in lines[1:]:
        # Stop collecting title lines when we hit an author-like line,
        # a date, or a section heading keyword.

        # A line that contains a pipe separator (course | author format)
        if "|" in line:
            break
        # A line that contains a date pattern
        if re.search(r"\d{1,2}/\d{1,2}/\d{4}|\b\d{4}\b", line) and len(line) < 60:
            break
        # A known section heading
        if _is_heading(line):
            break
        # If the previous title part ends with a preposition, conjunction,
        # or other continuation word, the next line is part of the title.
        prev = title_parts[-1].rstrip()
        ends_with_continuation = prev.endswith((" and", " or", " the",
            " of", " in", " for", " with", " between", " to", " from",
            " on", " at", " by", " an", " a"))

        # A short alpha-only line that does NOT continue the previous line
        # is likely an author name
        if (re.match(r"^[A-Za-z][A-Za-z\s.,&\-]+$", line)
                and len(line) < 60
                and not ends_with_continuation):
            break

        # The line is too long for a title
        if len(line) > 120:
            break

        title_parts.append(line)

        # Most titles are at most 3 lines
        if len(title_parts) >= 4:
            break

    return " ".join(title_parts) if title_parts else "Untitled"


def extract_authors(full_text):
    """Heuristic: author line usually follows the title."""
    lines = [l.strip() for l in full_text.splitlines() if l.strip()]

    # First, reconstruct the title to know how many lines to skip
    title = extract_title(full_text)
    title_line_count = 0
    for line in lines:
        title_line_count += 1
        # Once we've consumed all title lines, stop
        if title.endswith(line) or (title_line_count > 1 and line in title):
            break

    # Now look at lines after the title
    for line in lines[title_line_count:]:
        # Handle "DSCI200 August 2024 Project 2 | Ash Baghai" format
        pipe_match = re.search(r"\|\s*(.+)$", line)
        if pipe_match:
            return pipe_match.group(1).strip()
        # A short alpha-only line is likely an author name
        if re.match(r"^[A-Za-z][A-Za-z\s.,&\-]+$", line) and len(line) < 60:
            return line
    return "Unknown"


def extract_date(full_text):
    """Try to find a date in common formats near the top of the text."""
    # Check first 20 lines
    for line in full_text.splitlines()[:20]:
        # Patterns: 8/25/2024, August 2024, 2024-08-25, etc.
        m = re.search(
            r"\b(\d{1,2}/\d{1,2}/\d{4})\b"
            r"|(\b(?:January|February|March|April|May|June|July|August|"
            r"September|October|November|December)[,]?\s+\d{4}\b)"
            r"|(\d{4}-\d{2}-\d{2})",
            line,
        )
        if m:
            return m.group(0)
    return "Unknown"


# ---------------------------------------------------------------------------
# Content summarization helpers
# ---------------------------------------------------------------------------
def _clean_paragraph(text):
    """Collapse whitespace and clean up extracted PDF artefacts."""
    text = re.sub(r"\s+", " ", text)
    text = text.strip()
    return text


def _split_into_sentences(text):
    """Naive sentence splitter."""
    # Split on period followed by space and uppercase, or on newlines that
    # look like sentence boundaries.
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return [s.strip() for s in sentences if s.strip()]


def _pick_key_sentences(text, max_sentences=4):
    """Pick up to *max_sentences* representative sentences from *text*."""
    sentences = _split_into_sentences(_clean_paragraph(text))
    if len(sentences) <= max_sentences:
        return sentences
    # Pick first, last, and evenly spaced middle sentences
    indices = [0]
    if max_sentences >= 2:
        indices.append(len(sentences) - 1)
    if max_sentences >= 3:
        step = max(1, len(sentences) // (max_sentences - 1))
        for i in range(step, len(sentences) - 1, step):
            if len(indices) < max_sentences:
                indices.append(i)
    indices = sorted(set(indices))[:max_sentences]
    return [sentences[i] for i in indices]


# ---------------------------------------------------------------------------
# Roman numeral outline builder
# ---------------------------------------------------------------------------
def build_roman_outline(sections):
    """Build a Roman-numeral outline string from detected sections."""
    outline_parts = []
    major_num = 0

    for heading, body in sections:
        if heading is None:
            # Preamble / untitled initial block — use as overview
            continue

        major_num += 1
        outline_parts.append(f"### {roman(major_num)}. {heading}")

        if not body:
            outline_parts.append("   - *(No additional details extracted)*\n")
            continue

        # Break body into sub-topics (paragraphs or sub-headings)
        paragraphs = re.split(r"\n{2,}", body)
        sub_letter = ord("A")

        for para in paragraphs:
            para_clean = _clean_paragraph(para)
            if not para_clean or len(para_clean) < 10:
                continue

            # Check if this paragraph starts with a sub-heading
            first_line = para_clean.split(".")[0] if "." in para_clean else ""
            is_sub = _is_subheading(para.strip().splitlines()[0]) if para.strip() else False

            if is_sub:
                outline_parts.append(
                    f"   {chr(sub_letter)}. **{para.strip().splitlines()[0].strip()}**"
                )
                remaining = _clean_paragraph(
                    "\n".join(para.strip().splitlines()[1:])
                )
                if remaining:
                    key = _pick_key_sentences(remaining, max_sentences=3)
                    for s in key:
                        outline_parts.append(f"      - {s}")
            else:
                # Summarise the paragraph as bullet points
                key = _pick_key_sentences(para_clean, max_sentences=3)
                for s in key:
                    outline_parts.append(f"   - {s}")

            sub_letter += 1
            if sub_letter > ord("Z"):
                sub_letter = ord("A")

        outline_parts.append("")  # blank line between sections

    return "\n".join(outline_parts)


# ---------------------------------------------------------------------------
# Key findings extractor
# ---------------------------------------------------------------------------

_FINDINGS_KEYWORDS = [
    "conclusion", "key finding", "result", "outcome", "significant",
    "demonstrate", "revealed", "identified", "highlighted", "showed",
    "successfully", "improvement", "impact",
]


def extract_key_findings(sections):
    """Pull sentences from conclusion/results sections."""
    findings = []
    for heading, body in sections:
        if heading and any(
            kw in heading.lower()
            for kw in ["conclusion", "result", "outcome", "key finding", "anticipated impact"]
        ):
            sentences = _pick_key_sentences(body, max_sentences=5)
            findings.extend(sentences)

    if not findings:
        # Fallback: scan all body text for sentences with key words
        for _, body in sections:
            for sent in _split_into_sentences(body):
                if any(kw in sent.lower() for kw in _FINDINGS_KEYWORDS):
                    findings.append(sent)
                if len(findings) >= 5:
                    break

    bullet_lines = [f"- {f}" for f in findings[:8]]
    return "\n".join(bullet_lines) if bullet_lines else "- *No explicit key findings section detected.*"


# ---------------------------------------------------------------------------
# Methodology extractor
# ---------------------------------------------------------------------------

_METHOD_KEYWORDS = [
    "method", "study design", "approach", "descriptive phase",
    "modeling phase", "data cleaning", "data source",
    "cluster analysis", "network", "recursive",
]


def extract_methodology(sections):
    """Pull methodology-related content."""
    method_parts = []
    for heading, body in sections:
        if heading and any(kw in heading.lower() for kw in _METHOD_KEYWORDS):
            sentences = _pick_key_sentences(body, max_sentences=4)
            method_parts.extend(sentences)

    bullet_lines = [f"- {m}" for m in method_parts[:10]]
    return "\n".join(bullet_lines) if bullet_lines else "- *No explicit methodology section detected.*"


# ---------------------------------------------------------------------------
# References extractor
# ---------------------------------------------------------------------------
def extract_references(full_text):
    """Extract the references section if present."""
    # Find a REFERENCES heading and take everything after it
    m = re.search(r"(?:^|\n)\s*REFERENCES?\s*\n", full_text, re.IGNORECASE)
    if m:
        refs_text = full_text[m.end():]
        # Stop at next major heading (if any)
        end = re.search(r"\n\s*[A-Z]{4,}\s*\n", refs_text)
        if end:
            refs_text = refs_text[: end.start()]
        refs_text = refs_text.strip()
        if refs_text:
            # Format each reference as a numbered list item
            lines = [l.strip() for l in refs_text.splitlines() if l.strip()]
            numbered = []
            for i, line in enumerate(lines, 1):
                # If line already starts with a number, keep it
                if re.match(r"^\d+[.)]", line):
                    numbered.append(f"- {line}")
                else:
                    numbered.append(f"- {line}")
            return "\n".join(numbered)
    return "- *No references section detected.*"


# ---------------------------------------------------------------------------
# Abstract / overview extractor
# ---------------------------------------------------------------------------
def extract_abstract(sections, full_text):
    """Return text for the abstract/overview."""
    for heading, body in sections:
        if heading and any(
            kw in heading.lower()
            for kw in ["abstract", "overview", "introduction"]
        ):
            return _clean_paragraph(body[:1500])

    # Fallback: use the first substantial body block
    for _, body in sections:
        cleaned = _clean_paragraph(body)
        if len(cleaned) > 100:
            return cleaned[:1500]

    return _clean_paragraph(full_text[:1500])


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------
DEFAULT_TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "obsidian_template.md")


def load_template(template_path=None):
    """Load the Obsidian markdown template."""
    path = template_path or DEFAULT_TEMPLATE_PATH
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def render_template(template, replacements):
    """Replace ``{{key}}`` placeholders in *template* with values from *replacements*."""
    result = template
    for key, value in replacements.items():
        result = result.replace("{{" + key + "}}", value)
    return result


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------
def generate_summary(pdf_path, template_path=None):
    """End-to-end: read PDF → extract → summarise → render markdown."""
    full_text, _, num_pages = extract_text_from_pdf(pdf_path)
    sections = detect_sections(full_text)

    title = extract_title(full_text)
    authors = extract_authors(full_text)
    date_pub = extract_date(full_text)
    abstract = extract_abstract(sections, full_text)
    content_outline = build_roman_outline(sections)
    key_findings = extract_key_findings(sections)
    methodology = extract_methodology(sections)
    references = extract_references(full_text)

    template = load_template(template_path)

    replacements = {
        "title": title,
        "authors": authors,
        "date_published": date_pub,
        "date_summarized": datetime.now().strftime("%Y-%m-%d"),
        "source_file": os.path.basename(pdf_path),
        "num_pages": str(num_pages),
        "abstract": abstract,
        "content_notes": content_outline,
        "key_findings": key_findings,
        "methodology": methodology,
        "references": references,
    }

    return render_template(template, replacements)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Generate an Obsidian-compatible summary from a PDF journal article."
    )
    parser.add_argument("pdf_file", help="Path to the PDF file to summarize.")
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Output markdown file path. Defaults to <pdf_name>_summary.md",
    )
    parser.add_argument(
        "--template", "-t",
        default=None,
        help="Path to a custom Obsidian template. Defaults to obsidian_template.md",
    )
    args = parser.parse_args()

    if not os.path.isfile(args.pdf_file):
        print(f"Error: File not found: {args.pdf_file}", file=sys.stderr)
        sys.exit(1)

    summary_md = generate_summary(args.pdf_file, template_path=args.template)

    if args.output:
        out_path = args.output
    else:
        base = os.path.splitext(os.path.basename(args.pdf_file))[0]
        out_path = f"{base}_summary.md"

    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(summary_md)

    print(f"Summary written to: {out_path}")


if __name__ == "__main__":
    main()
