"""Generic PyMuPDF AcroForm engine for declarative field binding, baking, and lineage."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pymupdf

from app.core.provenance import FieldLineageEntry


BindingTuple = Tuple[str, str, str, Optional[str], List[Any], Any]
FieldTransformFn = Callable[[str], str]


class AcroFormEngine:
    """Fills declarative AcroForm PDFs, appends overflow sheets, bakes widgets, and logs lineage.

    Attributes:
        templates_dir: Directory containing blank fillable AcroForm PDF templates.
        field_map_path: Path to declarative widget target JSON map (`form_field_maps.json`).
    """

    def __init__(
        self,
        templates_dir: Path,
        field_map_path: Optional[Path] = None,
    ) -> None:
        """Initializes the AcroForm engine.

        Args:
            templates_dir: Directory containing blank fillable PDF templates.
            field_map_path: Optional JSON map path (defaults to `<templates_dir.parent>/form_field_maps.json`).
        """
        self.templates_dir = templates_dir
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.field_map_path = field_map_path or (templates_dir.parent / "form_field_maps.json")
        self.field_maps = self._load_field_maps(self.field_map_path)

    @staticmethod
    def _load_field_maps(field_map_path: Path) -> Dict[str, Any]:
        """Loads declarative PDF widget target definitions from JSON."""
        if not field_map_path.exists():
            return {}
        try:
            return json.loads(field_map_path.read_text(encoding="utf-8")).get("forms", {})
        except Exception:
            return {}

    def ensure_template(
        self,
        form_id: str,
        fallback_title: Optional[str] = None,
        fallback_fields: Optional[List[str]] = None,
    ) -> Path:
        """Returns path to a fillable AcroForm PDF template, synthesizing one if absent."""
        path = self.templates_dir / f"{form_id}.pdf"
        if path.exists():
            return path

        title = fallback_title or f"Form {form_id}"
        field_names = fallback_fields or ["Primary_Name"]
        doc = pymupdf.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((48, 52), title, fontsize=12.5, fontname="helv")
        page.draw_line((48, 62), (564, 62))

        y = 84
        for fname in field_names:
            if y > 720:
                page = doc.new_page(width=612, height=792)
                y = 60
            page.insert_text(
                (48, y + 14), f"{fname.replace('_', ' ')}:", fontsize=9, fontname="helv"
            )
            widget = pymupdf.Widget()
            widget.field_name = fname
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pymupdf.Rect(215, y, 560, y + 22)
            widget.text_fontsize = 9.5
            widget.text_font = "helv"
            widget.border_width = 0.5
            widget.border_color = (0.7, 0.7, 0.7)
            widget.field_value = ""
            page.add_widget(widget)
            y += 32

        doc.save(str(path))
        doc.close()
        return path

    @staticmethod
    def append_overflow_sheet(
        doc: pymupdf.Document,
        form_id: str,
        lines: List[str],
        chunk_size: int = 24,
    ) -> None:
        """Appends clean overflow continuation sheets when rows exceed template widget slots."""
        for page_num, start in enumerate(range(0, len(lines), chunk_size), start=1):
            page = doc.new_page(width=612, height=792)
            page.insert_text(
                (48, 52),
                f"{form_id} — Overflow Continuation Sheet ({page_num})",
                fontsize=12,
                fontname="helv",
            )
            page.draw_line((48, 62), (564, 62))
            y = 84
            for ln in lines[start : start + chunk_size]:
                for wrapped in textwrap.wrap(ln, width=88) or [""]:
                    page.insert_text((48, y), wrapped, fontsize=9.5, fontname="helv")
                    y += 16

    def fill_and_bake_form(
        self,
        form_id: str,
        output_path: Path,
        bindings: Dict[str, BindingTuple],
        overflow_lines: Optional[List[str]] = None,
        watermark_draft: bool = False,
        fallback_title: Optional[str] = None,
        fallback_fields: Optional[List[str]] = None,
        field_transforms: Optional[Dict[str, FieldTransformFn]] = None,
    ) -> Tuple[Path, List[FieldLineageEntry]]:
        """Fills widgets for `form_id`, appends overflow pages, bakes, and returns lineage."""
        tmpl_path = self.ensure_template(
            form_id,
            fallback_title=fallback_title,
            fallback_fields=fallback_fields,
        )
        official_targets = (self.field_maps.get(form_id) or {}).get("targets", {})
        transforms = field_transforms or {}
        lineage_entries: List[FieldLineageEntry] = []

        doc = pymupdf.open(str(tmpl_path))

        # Scan field names first without holding detached Page/Annot references across loop iterations.
        all_doc_field_names = {
            widget.field_name
            for page in doc
            for widget in (page.widgets() or [])
        }
        use_official_map = any(
            tgt["field_name"] in all_doc_field_names
            for targets in official_targets.values()
            for tgt in targets
        )

        if use_official_map:
            # Build `(page_num, field_name, occurrence) -> (sem_key, target, entry)` lookup
            # so widgets are mutated inside `for pno, page in enumerate(doc, start=1):`
            # while every Annot stays bound to its live Page.
            slot_lookup: Dict[Tuple[int, str, int], Tuple[str, Dict[str, Any], BindingTuple]] = {}
            for sem_key, entry_tuple in bindings.items():
                if entry_tuple[0] == "":
                    continue
                for tgt in official_targets.get(sem_key, []):
                    key = (
                        int(tgt.get("page", 1)),
                        tgt["field_name"],
                        int(tgt.get("occurrence", 0)),
                    )
                    slot_lookup[key] = (sem_key, tgt, entry_tuple)

            for pno, page in enumerate(doc, start=1):
                occ_counts: Dict[str, int] = {}
                for widget in page.widgets() or []:
                    wname = widget.field_name
                    occ = occ_counts.get(wname, 0)
                    occ_counts[wname] = occ + 1
                    slot = slot_lookup.get((pno, wname, occ))
                    if not slot:
                        continue
                    _sem_key, tgt, entry_tuple = slot
                    val, dtype, cpath, formula, locs, ov = entry_tuple
                    mode = tgt.get("mode", "text")
                    write_val = val
                    if mode == "checkbox":
                        write_val = tgt.get("on_value", val)
                    elif wname in transforms:
                        write_val = transforms[wname](val)
                    elif tgt.get("transform") == "digits_9":
                        write_val = "".join(ch for ch in val if ch.isdigit())[:9] or val
                    elif widget.field_type_string == "ComboBox" and widget.choice_values:
                        matched_choice = next(
                            (c for c in widget.choice_values if val.lower() in c.lower()),
                            None,
                        )
                        if matched_choice is None:
                            continue
                        write_val = matched_choice
                    widget.field_value = write_val
                    widget.update()
                    lineage_entries.append(
                        FieldLineageEntry(
                            form_id=form_id,
                            pdf_field_name=wname,
                            form_line_ref=tgt.get("line_ref"),
                            rendered_value=val,
                            derivation_type=dtype,  # type: ignore[arg-type]
                            case_graph_path=cpath,
                            formula=formula,
                            source_locators=locs,
                            human_override=ov,
                        )
                    )
        else:
            for page in doc:
                for widget in page.widgets() or []:
                    fname = widget.field_name
                    if fname in bindings:
                        val, dtype, cpath, formula, locs, ov = bindings[fname]
                        write_val = transforms[fname](val) if fname in transforms else val
                        widget.field_value = write_val
                        widget.update()
                        if val != "":
                            lineage_entries.append(
                                FieldLineageEntry(
                                    form_id=form_id,
                                    pdf_field_name=fname,
                                    form_line_ref=f"{form_id} · {fname}",
                                    rendered_value=val,
                                    derivation_type=dtype,  # type: ignore[arg-type]
                                    case_graph_path=cpath,
                                    formula=formula,
                                    source_locators=locs,
                                    human_override=ov,
                                )
                            )

        # Permanently flatten interactive widgets into static PDF page streams.
        doc.bake(annots=True, widgets=True)

        if overflow_lines:
            self.append_overflow_sheet(doc, form_id, overflow_lines)

        if watermark_draft:
            for page in doc:
                page.insert_text(
                    (180, 400),
                    "DRAFT ONLY - DO NOT FILE",
                    fontsize=24,
                    color=(0.75, 0.25, 0.25),
                )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(output_path), garbage=4, deflate=True)
        doc.close()
        return output_path, lineage_entries

    def compile_packet(
        self,
        specs: List[Dict[str, Any]],
        output_dir: Path,
        watermark_draft: bool = False,
    ) -> Tuple[List[Path], Path, List[FieldLineageEntry]]:
        """Compiles a sequence of form specs into baked PDFs and `field_lineage.json`."""
        output_dir.mkdir(parents=True, exist_ok=True)
        generated_pdfs: List[Path] = []
        lineage_entries: List[FieldLineageEntry] = []

        for spec in specs:
            form_id = str(spec["form_id"])
            out_name = str(spec.get("output_filename") or f"{form_id}.pdf")
            out_path, form_lineage = self.fill_and_bake_form(
                form_id=form_id,
                output_path=output_dir / out_name,
                bindings=spec.get("bindings", {}),
                overflow_lines=spec.get("overflow_lines"),
                watermark_draft=watermark_draft,
                fallback_title=spec.get("fallback_title"),
                fallback_fields=spec.get("fallback_fields"),
                field_transforms=spec.get("field_transforms"),
            )
            generated_pdfs.append(out_path)
            lineage_entries.extend(form_lineage)

        lineage_path = output_dir / "field_lineage.json"
        lineage_path.write_text(
            json.dumps([e.model_dump(mode="json") for e in lineage_entries], indent=2),
            encoding="utf-8",
        )
        return generated_pdfs, lineage_path, lineage_entries
