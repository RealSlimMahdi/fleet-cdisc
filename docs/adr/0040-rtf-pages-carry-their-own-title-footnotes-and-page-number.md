# RTF pages carry their own title, footnotes and page number

The alpha audit of 2 November 2026 (findings c1-820 and c1-456) found two page faults in the TLG renderers:

- `render_rtf` broke a logical page every 40 rows and wrote "Page X of Y" as body text. With a two-line column header, footnotes or wrapped rows, 40 rows did not fit one landscape Letter page. Word then made an overflow page with no title, and the counter sat on the wrong physical page.
- `paginate` cut a page by row count only. A page could start at a statistic row (Median) or a preferred term, with its parameter, visit or SOC on the page before.

We decided that every physical page shows what it is: its title, its parents and its own page number.

## The decision

- **Title and footnotes in the Word header and footer by default, BODYTITLE on request** (Mahdi, c1-820 C). `render_rtf` and `render_listing_rtf` write the title and subtitle in one `{\header}` group and the footnotes in one `{\footer}` group, as the SAS ODS RTF default. `body_title=True` writes them in the body at each page break, as ODS RTF BODYTITLE and r2rtf.
- **The page number is a Word field.** The footer always holds `Page {PAGE} of {NUMPAGES}`, so each physical page has a correct number in both layouts.
- **The page budget is in points.** A page holds the rows that fit 468 pt (landscape Letter, 1 inch margins). The title, the column-header lines, the footnotes (in the body, or when the header or footer is taller than its margin) and the wrapped lines of each row count. A line is 1.2 times the font size, and a cell wraps at the Courier New width. `rows_per_page` (default 40) stays as a cap.
- **A continued page repeats its parents.** `paginate` finds the parents of the first row from `TableRow.indent` and repeats them with the suffix " (continued)" and empty cells. These rows count in the page. The statistic rows of one level stay on one page when they fit; a larger block is split. The first page of a `page_by` block has no continued row. `render_pdf` uses the RTF default of 40 rows per page, so its pages also come from the model layer.

## Considered options

- **Header and footer only** (c1-820 A). Rejected as the only layout: a body-only text check does not see the title, and a writer who copies the table into a CSR loses it.
- **Body only, with a line budget** (c1-820 B). Rejected as the only layout: when the budget is too high (a long verbatim term, another font), an overflow page has a number but no title.
- **A new pagination argument for continued rows.** Rejected: one default is simpler, and a page without its parents is never correct.

## Consequences

- Text viewers that drop RTF header and footer groups (TextEdit, textutil) do not show the default title, footnotes or page number. Word does. Use `body_title=True` when a QC script reads the RTF text.
- A QC script that searches the RTF for the literal "Page 1 of" no longer matches.
- RTF and PPTX pages, and PDF pages, can hold fewer rows than before and can start with "(continued)" rows.
- The two layouts need their own visual check.
