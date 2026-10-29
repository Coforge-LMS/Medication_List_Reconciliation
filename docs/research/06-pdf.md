# 06 — PDF report library
OWNER: Sarthak Kakkar, to review and finalize
_Drafted 2026-10-29 by a research agent; facts verified against the sources listed below._

## Recommendation
Use **fpdf2 2.8.9** with two bundled DejaVu Sans TTFs (regular + bold), and **pypdf 6.21.4** as a dev-only test dependency. fpdf2 is a pure-Python wheel, needs no apt packages in `python:3.12-slim`, has a built-in `pdf.table()`, and is the least code for a one-day build. Runner-ups: ReportLab 5.1.0 (BSD, more boilerplate), WeasyPrint 70.0 (HTML/CSS, needs Pango apt packages).

## Rationale
Install sizes are on-disk `pip install --target` in `python:3.12-slim` (Python 3.12.16), measured 2026-10-29; they include Pillow.

| Library (latest, release date) | Py 3.12 and install in slim | Tables | License | Unicode / fonts | One-day fit |
|---|---|---|---|---|---|
| ReportLab 5.1.0 (2026-10-22) | Requires Python >=3.9; pure wheel (2.0 MB); deps Pillow, charset-normalizer; ~33 MB; no apt | `Table(data, colWidths, repeatRows)` + `TableStyle`; Paragraph cells for wrapping | BSD | WinAnsi core fonts; chars outside it fall back to Symbol/ZapfDingbats or draw a black box; `TTFont` fixes it | Medium: SimpleDocTemplate, styles, Paragraphs |
| fpdf2 2.8.9 (2026-09-29) | Requires Python >=3.10; pure wheel (341 KB); deps Pillow, fonttools, defusedxml; ~56 MB; no apt | `with pdf.table() as t:` with auto-wrap, per-column widths, headings repeated on every page | LGPL-3.0-only | Core fonts Latin-1 only, raises on others; `add_font()` TTF fixes it | Best: least code |
| WeasyPrint 70.0 (2026-09-08) | Requires Python >=3.10; pure wheel (329 KB) but ~77 MB pip deps plus apt `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0` (~17 MB); `OSError` without them | Plain HTML `<table>` + CSS | BSD | Fonts via fontconfig; em dash, µ, → rendered correctly in my test | Good if team likes HTML templates; heaviest image |

- Verified by running in `python:3.12-slim` with the exact pins: the sketch below, a FastAPI route and 3 pytest tests all passed, with system fonts removed so only the bundled TTFs were used.
- Licenses: ReportLab and WeasyPrint are BSD (PyPI metadata). fpdf2 is `LGPL-3.0-only` (PyPI `license_expression`). Using it unmodified as a pip dependency is the normal case; not legal advice.
- fpdf2 docs show the exact FastAPI pattern `Response(content=bytes(pdf.output()), media_type="application/pdf", headers=...)`.
- pypdf is worth adding: tiny (~5 MB, no deps on Python 3.12), dev-only (keep it out of the image), and fpdf2 itself lists pypdf in its own test extras.

## Pinned versions
- `fpdf2==2.8.9` (requires Python >=3.10; pulls Pillow `!=9.2.*,>=8.3.2`, fonttools `>=4.34.0`, defusedxml; my run resolved Pillow 13.0.0, fonttools 4.68.0, defusedxml 0.7.1)
- `pypdf==6.21.4` (dev only; released 2026-10-28, i.e. yesterday; installed and passed on Python 3.12)
- `fastapi`, `httpx`, `pytest`: whatever the team's stack already pins (my run used fastapi 0.162.0)
- Fonts: `DejaVuSans.ttf` (759,720 B) and `DejaVuSans-Bold.ttf` (708,920 B) from Debian `fonts-dejavu-core`, committed under `app/fonts/` with the license text.

## Commands and config snippets
```text
# requirements.txt          # requirements-dev.txt
fpdf2==2.8.9                pypdf==6.21.4
```
```dockerfile
FROM python:3.12-slim              # no apt-get needed for fpdf2
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/                     # includes app/fonts/*.ttf
```
Get the fonts once: `docker run --rm -v "$PWD/app/fonts:/o" python:3.12-slim sh -c 'apt-get update -qq && apt-get install -y -qq fonts-dejavu-core && cd /usr/share/fonts/truetype/dejavu && cp DejaVuSans.ttf DejaVuSans-Bold.ttf /o/'`. Tested sketch (`app/report_pdf.py`; dict shapes are placeholders, adapt to the real models):
```python
from datetime import datetime, timezone
from pathlib import Path
from fpdf import FPDF

FONTS = Path(__file__).parent / "fonts"
DISCLAIMER = "Synthetic data. Reports discrepancies only; does not recommend treatment."
NL = dict(new_x="LMARGIN", new_y="NEXT")

def _h(pdf, text, size=12):
    pdf.set_font("dv", "B", size); pdf.cell(0, 8, text, **NL); pdf.set_font("dv", size=10)

def _table(pdf, header, rows):
    if not rows:
        pdf.cell(0, 6, "(none)", **NL); return
    with pdf.table() as t:  # first row = headings; long cells wrap; headings repeat per page
        for r in (header, *rows):
            row = t.row()
            for c in r:
                row.cell("" if c is None else str(c))

def build_pdf(patient, fhir, pharmacy, findings, summary) -> bytes:
    pdf = FPDF(format="A4")
    pdf.add_font("dv", fname=FONTS / "DejaVuSans.ttf")
    pdf.add_font("dv", style="B", fname=FONTS / "DejaVuSans-Bold.ttf")  # table headings are bold
    pdf.add_page(); _h(pdf, "Medication Reconciliation Report", 16)
    pdf.multi_cell(0, 5, f"Patient: {patient['name']} (ID {patient['id']})\n"
                         f"Generated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC\n{DISCLAIMER}", **NL)
    for title, meds in (("FHIR medication list", fhir), ("Pharmacy medication list", pharmacy)):
        _h(pdf, title)
        _table(pdf, ["Medication", "Dose", "Frequency"], [[m["name"], m.get("dose"), m.get("frequency")] for m in meds])
    _h(pdf, "Findings")
    if not findings:
        pdf.cell(0, 6, "No discrepancies found", **NL)
    for ftype in dict.fromkeys(f["type"] for f in findings):  # unknown types render too
        _h(pdf, ftype.replace("_", " ").title(), 10)
        _table(pdf, ["Medication", "FHIR value", "Pharmacy value"],
               [[f["medication"], f.get("fhir_value"), f.get("pharmacy_value")] for f in findings if f["type"] == ftype])
    _h(pdf, "Summary"); pdf.multi_cell(0, 5, summary, **NL)
    return bytes(pdf.output())  # output() returns bytearray
```
FastAPI route (sync `def`, so FastAPI runs the blocking fpdf2 call in its threadpool):
```python
return Response(content=data, media_type="application/pdf",
                headers={"Content-Disposition": f'attachment; filename="reconciliation-{rid}.pdf"'})
```
pytest (tested; `pdf_text` collapses whitespace because wrapping changes newlines):
```python
def pdf_text(b): return " ".join(" ".join(p.extract_text() for p in PdfReader(io.BytesIO(b)).pages).split())
def test_zero_findings():
    b = build_pdf(P, [], [], [], "0 findings")   # summary must not contain the phrase under test
    assert b.startswith(b"%PDF-") and "No discrepancies found" in pdf_text(b) and "does not recommend treatment" in pdf_text(b)
def test_unknown_type_and_unicode():   # a future type string and non-Latin-1 chars must still render
    f = [{"type": "future_type", "medication": "Aspirin — 81 µg", "fhir_value": "→", "pharmacy_value": None}]
    assert "Future Type" in pdf_text(build_pdf(P, [{"name": "A"}], [], f, "1 finding"))
def test_endpoint():
    r = TestClient(app).get("/reports/p1/pdf")
    assert r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF-")
```

## Gotchas
- **Core fonts break the app:** fpdf2 Helvetica/Times/Courier raise `FPDFUnicodeEncodingException` (an HTTP 500) on em dash U+2014, en dash, curly quotes, →, ≥, € and Greek µ U+03BC. Latin-1 µ U+00B5 and é are fine. Any TTF registered with `add_font()` avoids this (tested: dash, µ, μ, →, ≥ render and extract correctly).
- **Table headings are bold by default:** with only a regular TTF registered, `pdf.table()` raises `FPDFException` ("require the corresponding font style to be added"). Register the Bold file too (as in the sketch).
- **Glyphs missing from DejaVu** (e.g. CJK): no exception, only a `fpdf.output` log warning and blank glyphs. Acceptable for synthetic data.
- **Fonts must ship with the repo:** `/usr/share/fonts/...` exists only where `fonts-dejavu-core` is installed, so macOS developers would fail. Bundling avoids this; the DejaVu license allows bundling if copyright notices are included and modified fonts are renamed.
- **Raw-byte checks:** content streams use `/FlateDecode` and TTF text is glyph-encoded, so grepping the bytes for a phrase is unreliable. Use pypdf. pypdf's docs warn that whitespace is hard to reproduce, hence the whitespace collapse.
- `pdf.output()` returns a `bytearray`; wrap with `bytes()` for `Response`.
- Validate or slugify `rid` before putting it in the `Content-Disposition` filename.
- An empty list is guarded with "(none)"; a header-only `pdf.table()` was not tested.

## Rejected alternatives
- **ReportLab 5.1.0:** solid and BSD, and degrades without exceptions, but chars outside WinAnsi/Symbol silently become a black box (tested with 日, ł, 😀), which is bad for clinical text. More boilerplate (SimpleDocTemplate, TableStyle, Paragraph styles, `TTFont` registration). Plain-string cells not wrapping is from experience, UNVERIFIED in the docs page I fetched. Pick it if LGPL is a concern.
- **WeasyPrint 70.0:** nicest to style (Jinja HTML + CSS) and correct with Unicode out of the box, but the import fails with `OSError: cannot load library 'libgobject-2.0-0'` until the three Pango/HarfBuzz apt packages are installed, and the image grows by ~94 MB in total (pip + apt). Worth it only if the team wants an HTML template.

## Sources
- [fpdf2 on PyPI](https://pypi.org/project/fpdf2/): version 2.8.9, Python >=3.10, LGPL-3.0-only, pure wheel (fetched 2026-10-29)
- [ReportLab on PyPI](https://pypi.org/project/reportlab/): version 5.1.0, Python >=3.9, BSD, extras (fetched 2026-10-29)
- [WeasyPrint on PyPI](https://pypi.org/project/weasyprint/): version 70.0, Python >=3.10, BSD classifier (fetched 2026-10-29)
- [pypdf on PyPI](https://pypi.org/project/pypdf/): version 6.21.4, BSD-3-Clause, `extract_text()` example (fetched 2026-10-29)
- [fpdf2 PyPI JSON](https://pypi.org/pypi/fpdf2/json), [ReportLab PyPI JSON](https://pypi.org/pypi/reportlab/json), [WeasyPrint PyPI JSON](https://pypi.org/pypi/weasyprint/json), [pypdf PyPI JSON](https://pypi.org/pypi/pypdf/json): `requires_dist` dependency lists (fetched 2026-10-29)
- [fpdf2 2.8.9 JSON](https://pypi.org/pypi/fpdf2/2.8.9/json), [ReportLab 5.1.0 JSON](https://pypi.org/pypi/reportlab/5.1.0/json), [WeasyPrint 70.0 JSON](https://pypi.org/pypi/weasyprint/70.0/json): wheel and sdist file names and sizes (fetched 2026-10-29)
- [fpdf2 Tables](https://py-pdf.github.io/fpdf2/Tables.html): `pdf.table()`, col_widths, headings_style, repeated headings, wrapping (fetched 2026-10-29)
- [fpdf2 Unicode](https://py-pdf.github.io/fpdf2/Unicode.html): core fonts limited, `FPDFUnicodeEncodingException`, `add_font()`, fallback fonts (fetched 2026-10-29)
- [fpdf2 usage in web APIs](https://py-pdf.github.io/fpdf2/UsageInWebAPI.html): FastAPI `Response(content=bytes(pdf.output()), ...)` (fetched 2026-10-29)
- [ReportLab tables](https://docs.reportlab.com/reportlab/userguide/ch7_tables/): `Table`, `colWidths`, `repeatRows`, `TableStyle` (fetched 2026-10-29)
- [ReportLab fonts](https://docs.reportlab.com/reportlab/userguide/ch3_fonts/): WinAnsi standard fonts, Symbol/ZapfDingbats fallback, `TTFont` registration (fetched 2026-10-29)
- [WeasyPrint first steps](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html): Pango >=1.44, Debian/Ubuntu apt package lists (fetched 2026-10-29)
- [pypdf text extraction](https://pypdf.readthedocs.io/en/stable/user/extract-text.html): `extract_text()` and its whitespace and table caveats (fetched 2026-10-29)
- [DejaVu license](https://dejavu-fonts.github.io/License.html): free to bundle and redistribute with notices (fetched 2026-10-29)
- Own measurements (no URL): all sizes, errors and test results above come from runs in `python:3.12-slim` on 2026-10-29.
