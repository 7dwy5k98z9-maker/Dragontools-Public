"""Validate pip specifiers with the declared packaging dependency."""
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import Version, InvalidVersion


def has_reproducible_bound(spec):
    try:
        values = SpecifierSet(str(spec or ''))
        if values.is_unsatisfiable() or any(item.operator == '===' for item in values):
            return False
        pinned = [item for item in values if item.operator == '==' and '*' not in item.version]
        if pinned:
            return any(values.contains(Version(item.version), prereleases=True) for item in pinned)
        if any(item.operator == '~=' for item in values):
            return True
        operators = {item.operator for item in values}
        return bool(operators & {'>', '>='}) and bool(operators & {'<', '<='})
    except (InvalidSpecifier, InvalidVersion, ValueError):
        return False
