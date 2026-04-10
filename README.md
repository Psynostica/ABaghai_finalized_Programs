# ABaghai_finalized_Programs

## PDF Journal Article to Obsidian Summary Generator

A Python tool that extracts text from PDF journal articles and generates comprehensive Obsidian-compatible markdown summaries using **Roman numeral outline format**.

### Features

- Extracts metadata (title, authors, date) from PDF articles
- Detects and organizes document sections automatically
- Generates content notes in **Roman numeral outline** format (I, II, III, …)
- Produces Obsidian-ready markdown with YAML front matter
- Extracts key findings, methodology, and references into dedicated sections
- Customizable template (`obsidian_template.md`)

### Requirements

```
pip install -r requirements.txt
```

### Usage

```bash
# Basic usage — generates <pdf_name>_summary.md in the current directory
python pdf_to_obsidian_summary.py article.pdf

# Specify output file
python pdf_to_obsidian_summary.py article.pdf --output my_summary.md

# Use a custom Obsidian template
python pdf_to_obsidian_summary.py article.pdf --template my_template.md
```

### Example

```bash
python pdf_to_obsidian_summary.py "ABaghai_Enhancing Drug Safety through Data Management and Analytics.pdf"
```

Produces a markdown file with:
- YAML front matter (title, authors, date, tags)
- Abstract / Overview
- Content Notes in Roman numeral outline (I. Introduction, II. Methods, …)
- Key Findings & Takeaways
- Methodology
- References
- Personal Notes section

### Files

| File | Description |
|------|-------------|
| `pdf_to_obsidian_summary.py` | Main script — PDF text extraction and summary generation |
| `obsidian_template.md` | Obsidian markdown template with placeholder fields |
| `requirements.txt` | Python dependencies |
| `test_pdf_to_obsidian_summary.py` | Unit and integration tests |
| `ABaghai_Enhancing_Drug_Safety_summary.md` | Example output summary |
| `ABaghai_Chromatography_Analysis_summary.md` | Example output summary |

### Running Tests

```bash
pip install pytest
python -m pytest test_pdf_to_obsidian_summary.py -v
```