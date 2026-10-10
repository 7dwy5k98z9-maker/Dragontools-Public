"""Shared report cells and an Excel-readable CSV export."""
import csv
from pathlib import Path

from .renamer_completeness import season_label

REPORT_HEADERS = ("Serie", "Quelle", "Serien-ID", "Staffel", "Status", "Erwartete Folgen",
                  "Vorhandene Folgen", "Fehlende Folgen", "Zusätzliche Folgen", "Hinweise")


def result_cells(result):
    return (result.hit.display_title, result.hit.provider_label, str(result.hit.provider_id),
            "Serie" if result.season is None else season_label(result.season), result.status,
            str(len(result.expected)) if result.status != "Nicht prüfbar" else "–",
            str(len(result.present)), ", ".join(map(str, result.missing)),
            ", ".join(map(str, result.extra)), result.note)


def write_completeness_csv(results, path):
    with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, delimiter=";")
        writer.writerow(REPORT_HEADERS)
        for result in results:
            writer.writerow(_spreadsheet_cell(value) for value in result_cells(result))


def _spreadsheet_cell(value):
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value
