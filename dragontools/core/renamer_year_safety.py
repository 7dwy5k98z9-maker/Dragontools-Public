"""Keep provider evidence separate from the requested release/start year."""


def year_review_warning(requested_year, candidate_year):
    if requested_year is None:
        return None
    if candidate_year is None:
        return "Provider-Jahr fehlt; gewünschtes Jahr ist nicht bestätigt."
    if candidate_year != requested_year:
        return f"Provider-Jahr {candidate_year} weicht vom Suchjahr {requested_year} ab; Auswahl prüfen."
    return None


def apply_year_review(status, warnings, requested_year, candidate_year):
    warning = year_review_warning(requested_year, candidate_year)
    if warning:
        warnings.append(warning)
        if status == "ok":
            return "manual_review"
    return status
