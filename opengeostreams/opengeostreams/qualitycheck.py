"""Rule-based water quality screening: station fitness per use case and parameter safety scales.

The dashboard shows each station as pass / caution / fail for human consumption,
agriculture, aquatic life or bathing, plus a safety scale for the selected parameter.
All of those rules and thresholds live here; ``build_quality_payload`` evaluates every
station sample once so the browser only has to pick the sample matching its filters.

Each use case has *core* checks (any exceedance fails the station) and *extended*
checks (exceedances downgrade a pass to caution). A station with none of the core
inputs measured is reported as insufficient data.
"""
from __future__ import annotations

import math
import re
from typing import Any, Iterable

USE_CASES = [
    {"key": "human_consumption", "label": "Human Consumption"},
    {"key": "agriculture", "label": "Agriculture"},
    {"key": "aquatic_life", "label": "Aquatic Life"},
    {"key": "bathing", "label": "Bathing"},
]
USE_CASE_KEYS = [item["key"] for item in USE_CASES]

STATUS_LABELS = {"safe": "Pass", "caution": "Caution", "unsafe": "Fail", "unknown": "Insufficient data"}

# For each use case, map screening inputs to dataset parameter names (compared case-insensitively,
# ignoring a trailing "(max)"/"(min)"). "confirmed" names feed the rules directly; "proxy" names are
# only near matches, so they are reported in the coverage but not screened.
SCREENING_PARAMETER_SPECS: dict[str, list[dict[str, Any]]] = {
    "human_consumption": [
        {"key": "pH", "confirmed": ["pH"]},
        {"key": "turbidity_ntu", "confirmed": ["Turbidity"]},
        {"key": "tds_mg_l", "confirmed": ["TDS"]},
        {"key": "nitrate_mg_l", "confirmed": [], "proxy": ["NO3-N", "Nitrate"]},
        {"key": "fluoride_mg_l", "confirmed": ["Fluoride"]},
        {"key": "chloride_mg_l", "confirmed": ["Chloride"]},
        {"key": "sulphate_mg_l", "confirmed": ["Sulphate", "SO4"]},
        {"key": "hardness_mg_l_as_caco3", "confirmed": ["TH as CaCO3"]},
        {"key": "alkalinity_mg_l_as_caco3", "confirmed": ["Total alkalinity as CaCO3"], "proxy": ["P-Alkalinity"]},
        {"key": "total_coliform_mpn_100ml", "confirmed": ["Total Coliform", "T-Coliform"]},
        {"key": "e_coli_present", "confirmed": []},
    ],
    "agriculture": [
        {"key": "pH", "confirmed": ["pH"]},
        {"key": "ec_us_cm", "confirmed": [], "proxy": ["Conductivity"]},
        {"key": "sar", "confirmed": []},
        {"key": "boron_mg_l", "confirmed": ["Boron(B)"]},
        {"key": "chloride_mg_l", "confirmed": ["Chloride"]},
        {"key": "nitrate_mg_l", "confirmed": [], "proxy": ["NO3-N", "Nitrate"]},
        {"key": "bicarbonate_mg_l", "confirmed": []},
        {"key": "carbonate_mg_l", "confirmed": []},
        {"key": "rsc_meq_l", "confirmed": []},
    ],
    "aquatic_life": [
        {"key": "pH", "confirmed": ["pH"]},
        {"key": "dissolved_oxygen_mg_l", "confirmed": ["DO"]},
        {"key": "free_ammonia_mg_l_as_n", "confirmed": [], "proxy": ["NH3-N"]},
        {"key": "bod_mg_l", "confirmed": ["BOD"]},
        {"key": "nitrate_mg_l", "confirmed": [], "proxy": ["NO3-N", "Nitrate"]},
        {"key": "phosphate_mg_l", "confirmed": ["Phosphate"], "proxy": ["Phosphate-P"]},
        {"key": "turbidity_ntu", "confirmed": ["Turbidity"]},
        {"key": "temperature_c", "confirmed": ["Temperature"]},
    ],
    "bathing": [
        {"key": "pH", "confirmed": ["pH"]},
        {"key": "dissolved_oxygen_mg_l", "confirmed": ["DO"]},
        {"key": "bod_mg_l", "confirmed": ["BOD"]},
        {"key": "total_coliform_mpn_100ml", "confirmed": ["Total Coliform", "T-Coliform"]},
        {"key": "fecal_coliform_mpn_100ml", "confirmed": ["Faecal Coliform"]},
        {"key": "turbidity_ntu", "confirmed": ["Turbidity"]},
        {"key": "e_coli_present", "confirmed": []},
    ],
}

# Minimum checks needed before a station can be classified at all.
CORE_KEYS_BY_USE_CASE = {
    "human_consumption": ["pH", "turbidity_ntu", "tds_mg_l", "nitrate_mg_l", "fluoride_mg_l", "total_coliform_mpn_100ml", "e_coli_present"],
    "agriculture": ["pH", "ec_us_cm", "sar", "boron_mg_l"],
    "aquatic_life": ["pH", "dissolved_oxygen_mg_l", "free_ammonia_mg_l_as_n"],
    "bathing": ["pH", "dissolved_oxygen_mg_l", "bod_mg_l", "total_coliform_mpn_100ml", "fecal_coliform_mpn_100ml", "e_coli_present"],
}

INPUT_LABELS = {
    "pH": "pH",
    "turbidity_ntu": "Turbidity",
    "tds_mg_l": "TDS",
    "nitrate_mg_l": "Nitrate",
    "fluoride_mg_l": "Fluoride",
    "chloride_mg_l": "Chloride",
    "sulphate_mg_l": "Sulphate",
    "hardness_mg_l_as_caco3": "Hardness",
    "alkalinity_mg_l_as_caco3": "Alkalinity",
    "total_coliform_mpn_100ml": "Total coliform",
    "fecal_coliform_mpn_100ml": "Fecal coliform",
    "e_coli_present": "E. coli",
    "ec_us_cm": "EC",
    "sar": "SAR",
    "boron_mg_l": "Boron",
    "bicarbonate_mg_l": "Bicarbonate",
    "carbonate_mg_l": "Carbonate",
    "rsc_meq_l": "RSC",
    "dissolved_oxygen_mg_l": "DO",
    "free_ammonia_mg_l_as_n": "Free ammonia",
    "bod_mg_l": "BOD",
    "phosphate_mg_l": "Phosphate",
    "temperature_c": "Temperature",
}

# Safety scale per use case and scale key. type "range" is safe between safeMin and safeMax,
# "max" is safe up to safeMax, "min" is safe from safeMin upward. domainMin/domainMax fix the
# drawn axis; without them the dashboard sizes the axis around the threshold and the value.
PARAMETER_SCALE_DEFINITIONS: dict[str, dict[str, dict[str, Any]]] = {
    "human_consumption": {
        "ph": {"label": "pH", "type": "range", "safeMin": 6.5, "safeMax": 8.5, "domainMin": 0, "domainMax": 14},
        "turbidity": {"label": "Turbidity", "type": "max", "safeMax": 1.0, "unit": "NTU"},
        "tds": {"label": "TDS", "type": "max", "safeMax": 500, "unit": "mg/L"},
        "nitrate": {"label": "Nitrate", "type": "max", "safeMax": 45, "unit": "mg/L"},
        "fluoride": {"label": "Fluoride", "type": "max", "safeMax": 1.0, "unit": "mg/L"},
        "chloride": {"label": "Chloride", "type": "max", "safeMax": 250, "unit": "mg/L"},
        "sulphate": {"label": "Sulphate", "type": "max", "safeMax": 200, "unit": "mg/L"},
        "hardness": {"label": "Hardness", "type": "max", "safeMax": 200, "unit": "mg/L as CaCO3"},
        "alkalinity": {"label": "Alkalinity", "type": "max", "safeMax": 200, "unit": "mg/L as CaCO3"},
        "total_coliform": {"label": "Total Coliform", "type": "max", "safeMax": 0, "unit": "MPN/100mL", "domainMin": 0, "domainMax": 1000},
    },
    "agriculture": {
        "ph": {"label": "pH", "type": "range", "safeMin": 6.0, "safeMax": 8.5, "domainMin": 0, "domainMax": 14},
        "conductivity": {"label": "Conductivity", "type": "max", "safeMax": 2250, "unit": "uS/cm"},
        "boron": {"label": "Boron", "type": "max", "safeMax": 2.0, "unit": "mg/L", "domainMin": 0, "domainMax": 4},
        "chloride": {"label": "Chloride", "type": "max", "safeMax": 140, "unit": "mg/L"},
        "nitrate": {"label": "Nitrate", "type": "max", "safeMax": 30, "unit": "mg/L"},
    },
    "aquatic_life": {
        "ph": {"label": "pH", "type": "range", "safeMin": 6.5, "safeMax": 8.5, "domainMin": 0, "domainMax": 14},
        "do": {"label": "Dissolved Oxygen", "type": "min", "safeMin": 4.0, "unit": "mg/L", "domainMin": 0, "domainMax": 10},
        "ammonia": {"label": "Free Ammonia", "type": "max", "safeMax": 1.2, "unit": "mg/L as N", "domainMin": 0, "domainMax": 3},
        "bod": {"label": "BOD", "type": "max", "safeMax": 3.0, "unit": "mg/L", "domainMin": 0, "domainMax": 10},
        "nitrate": {"label": "Nitrate", "type": "max", "safeMax": 10, "unit": "mg/L"},
        "phosphate": {"label": "Phosphate", "type": "max", "safeMax": 0.1, "unit": "mg/L", "domainMin": 0, "domainMax": 1},
        "turbidity": {"label": "Turbidity", "type": "max", "safeMax": 25, "unit": "NTU"},
        "temperature": {"label": "Temperature", "type": "max", "safeMax": 32, "unit": "°C", "domainMin": 0, "domainMax": 40},
    },
    "bathing": {
        "ph": {"label": "pH", "type": "range", "safeMin": 6.5, "safeMax": 8.5, "domainMin": 0, "domainMax": 14},
        "do": {"label": "Dissolved Oxygen", "type": "min", "safeMin": 5.0, "unit": "mg/L", "domainMin": 0, "domainMax": 10},
        "bod": {"label": "BOD", "type": "max", "safeMax": 3.0, "unit": "mg/L", "domainMin": 0, "domainMax": 10},
        "total_coliform": {"label": "Total Coliform", "type": "max", "safeMax": 0, "unit": "MPN/100mL", "domainMin": 0, "domainMax": 2000},
        "fecal_coliform": {"label": "Faecal Coliform", "type": "max", "safeMax": 0, "unit": "MPN/100mL", "domainMin": 0, "domainMax": 2000},
        "turbidity": {"label": "Turbidity", "type": "max", "safeMax": 10, "unit": "NTU"},
    },
}
# Scales shown for every use case that does not define its own.
GLOBAL_PARAMETER_SCALE_DEFINITIONS = {
    "total_coliform": {"label": "Total Coliform", "type": "max", "safeMax": 0, "unit": "MPN/100mL", "domainMin": 0, "domainMax": 2000},
    "fecal_coliform": {"label": "Faecal Coliform", "type": "max", "safeMax": 0, "unit": "MPN/100mL", "domainMin": 0, "domainMax": 2000},
}

# Dataset parameter names (lowercase, punctuation collapsed to spaces) for each scale key.
SCALE_KEY_ALIASES = {
    "ph": ["ph"],
    "turbidity": ["turbidity"],
    "tds": ["tds"],
    "nitrate": ["no3 n", "nitrate"],
    "fluoride": ["fluoride"],
    "chloride": ["chloride"],
    "sulphate": ["sulphate", "so4"],
    "hardness": ["th as caco3", "hardness"],
    "alkalinity": ["total alkalinity as caco3", "p alkalinity"],
    "conductivity": ["conductivity"],
    "boron": ["boron b", "boron"],
    "do": ["do", "dissolved oxygen"],
    "ammonia": ["nh3 n", "free ammonia"],
    "bod": ["bod"],
    "phosphate": ["phosphate", "phosphate p"],
    "temperature": ["temperature"],
    "total_coliform": ["total coliform", "t coliform"],
    "fecal_coliform": ["faecal coliform", "fecal coliform"],
}
_SCALE_KEY_BY_ALIAS = {alias: key for key, aliases in SCALE_KEY_ALIASES.items() for alias in aliases}


# --- Parameter name helpers -------------------------------------------------------------

def parameter_variant(parameter: Any) -> str:
    """Return "max"/"min" when a parameter name ends in that tag, e.g. "pH (max)"."""
    match = re.search(r"\(([^)]*)\)\s*$", str(parameter or "").strip())
    variant = match.group(1).strip() if match else ""
    return variant if re.fullmatch(r"max|min", variant, re.I) else ""


def parameter_family(parameter: Any) -> str:
    """Strip a trailing "(max)"/"(min)" so variants of one parameter group together."""
    clean = str(parameter or "").strip()
    return re.sub(r"\s*\([^)]*\)\s*$", "", clean).strip() if parameter_variant(clean) else clean


def scale_key(parameter: Any) -> str:
    """Normalize a dataset parameter name to the key used by the safety scales."""
    clean = re.sub(r"[^a-z0-9]+", " ", str(parameter or "").lower()).strip()
    return _SCALE_KEY_BY_ALIAS.get(clean, re.sub(r"\s+", "_", clean))


def scale_definition(use_case: str, parameter: Any) -> dict[str, Any] | None:
    """The safety scale for a parameter under a use case, or None when none is configured."""
    key = scale_key(parameter)
    return PARAMETER_SCALE_DEFINITIONS.get(use_case, {}).get(key) or GLOBAL_PARAMETER_SCALE_DEFINITIONS.get(key)


def scale_status(definition: dict[str, Any], value: float | None) -> str:
    """"safe", "unsafe", or "unknown" for a missing/non-numeric value."""
    if value is None or not math.isfinite(value):
        return "unknown"
    if definition["type"] == "range":
        return "safe" if definition["safeMin"] <= value <= definition["safeMax"] else "unsafe"
    if definition["type"] == "min":
        return "safe" if value >= definition["safeMin"] else "unsafe"
    return "safe" if value <= definition["safeMax"] else "unsafe"


# --- Use-case rule sets -----------------------------------------------------------------

def _num(value: Any) -> str:
    """Format a value for a reason message: 7.0 -> "7", 7.25 -> "7.25"."""
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
        return str(int(value))
    return str(value)


def _result(use_case, core_reasons, extended_reasons, checked):
    fit_core = not core_reasons
    return {
        "use_case": use_case,
        "fit_core": fit_core,
        "fit_extended": fit_core and not extended_reasons,
        "core_reasons": core_reasons,
        "extended_reasons": extended_reasons,
        "checked_values": checked,
    }


def fit_for_human_consumption(pH=None, turbidity_ntu=None, tds_mg_l=None, nitrate_mg_l=None,
                              fluoride_mg_l=None, chloride_mg_l=None, sulphate_mg_l=None,
                              hardness_mg_l_as_caco3=None, alkalinity_mg_l_as_caco3=None,
                              total_coliform_mpn_100ml=None, e_coli_present=None, strict=True):
    """Drinking-water screening. ``strict`` uses the tighter turbidity and fluoride limits."""
    checked = dict(locals())
    core, extended = [], []
    turbidity_limit = 1.0 if strict else 5.0
    fluoride_limit = 1.0 if strict else 1.5

    if pH is not None and not 6.5 <= pH <= 8.5: core.append(f"pH {_num(pH)} outside 6.5-8.5")
    if turbidity_ntu is not None and turbidity_ntu > turbidity_limit: core.append(f"Turbidity {_num(turbidity_ntu)} NTU exceeds {_num(turbidity_limit)} NTU")
    if tds_mg_l is not None and tds_mg_l > 500: core.append(f"TDS {_num(tds_mg_l)} mg/L exceeds 500 mg/L desirable limit")
    if nitrate_mg_l is not None and nitrate_mg_l > 45: core.append(f"Nitrate {_num(nitrate_mg_l)} mg/L exceeds 45 mg/L")
    if fluoride_mg_l is not None and fluoride_mg_l > fluoride_limit: core.append(f"Fluoride {_num(fluoride_mg_l)} mg/L exceeds {_num(fluoride_limit)} mg/L")
    if total_coliform_mpn_100ml is not None and total_coliform_mpn_100ml > 0: core.append(f"Total coliform {_num(total_coliform_mpn_100ml)} MPN/100mL should be 0")
    if e_coli_present is True: core.append("E. coli detected")

    if chloride_mg_l is not None and chloride_mg_l > 250: extended.append(f"Chloride {_num(chloride_mg_l)} mg/L exceeds 250 mg/L desirable limit")
    if sulphate_mg_l is not None and sulphate_mg_l > 200: extended.append(f"Sulphate {_num(sulphate_mg_l)} mg/L exceeds 200 mg/L desirable limit")
    if hardness_mg_l_as_caco3 is not None and hardness_mg_l_as_caco3 > 200: extended.append(f"Hardness {_num(hardness_mg_l_as_caco3)} mg/L as CaCO3 exceeds 200 mg/L desirable limit")
    if alkalinity_mg_l_as_caco3 is not None and alkalinity_mg_l_as_caco3 > 200: extended.append(f"Alkalinity {_num(alkalinity_mg_l_as_caco3)} mg/L as CaCO3 exceeds 200 mg/L desirable limit")

    return _result("human_consumption", core, extended, checked)


def fit_for_agriculture(pH=None, ec_us_cm=None, sar=None, boron_mg_l=None, chloride_mg_l=None,
                        nitrate_mg_l=None, bicarbonate_mg_l=None, carbonate_mg_l=None, rsc_meq_l=None):
    """Irrigation screening (salinity, sodicity, boron, alkalinity hazard)."""
    checked = dict(locals())
    core, extended = [], []

    if pH is not None and not 6.0 <= pH <= 8.5: core.append(f"pH {_num(pH)} outside 6.0-8.5")
    if ec_us_cm is not None and ec_us_cm > 2250: core.append(f"EC {_num(ec_us_cm)} µS/cm exceeds 2250 µS/cm")
    if sar is not None and sar > 26: core.append(f"SAR {_num(sar)} exceeds 26")
    if boron_mg_l is not None and boron_mg_l > 2.0: core.append(f"Boron {_num(boron_mg_l)} mg/L exceeds 2.0 mg/L")

    if chloride_mg_l is not None and chloride_mg_l > 140: extended.append(f"Chloride {_num(chloride_mg_l)} mg/L may be restrictive for chloride-sensitive crops")
    if nitrate_mg_l is not None and nitrate_mg_l > 30: extended.append(f"Nitrate {_num(nitrate_mg_l)} mg/L is high for irrigation screening")
    if rsc_meq_l is not None and rsc_meq_l > 2.5:
        extended.append(f"RSC {_num(rsc_meq_l)} meq/L exceeds 2.5 meq/L")
    else:
        if bicarbonate_mg_l is not None and bicarbonate_mg_l > 610: extended.append(f"Bicarbonate {_num(bicarbonate_mg_l)} mg/L is high and may create alkalinity hazard")
        if carbonate_mg_l is not None and carbonate_mg_l > 120: extended.append(f"Carbonate {_num(carbonate_mg_l)} mg/L is high and may create alkalinity hazard")

    return _result("agriculture", core, extended, checked)


def fit_for_aquatic_life(pH=None, dissolved_oxygen_mg_l=None, free_ammonia_mg_l_as_n=None, bod_mg_l=None,
                         nitrate_mg_l=None, phosphate_mg_l=None, turbidity_ntu=None, temperature_c=None):
    """Stream ecosystem health screening."""
    checked = dict(locals())
    core, extended = [], []

    if pH is not None and not 6.5 <= pH <= 8.5: core.append(f"pH {_num(pH)} outside 6.5-8.5")
    if dissolved_oxygen_mg_l is not None and dissolved_oxygen_mg_l < 4.0: core.append(f"DO {_num(dissolved_oxygen_mg_l)} mg/L below 4.0 mg/L")
    if free_ammonia_mg_l_as_n is not None and free_ammonia_mg_l_as_n > 1.2: core.append(f"Free ammonia {_num(free_ammonia_mg_l_as_n)} mg/L exceeds 1.2 mg/L")

    if bod_mg_l is not None and bod_mg_l > 3.0: extended.append(f"BOD {_num(bod_mg_l)} mg/L exceeds 3.0 mg/L")
    if nitrate_mg_l is not None and nitrate_mg_l > 10: extended.append(f"Nitrate {_num(nitrate_mg_l)} mg/L is high for stream ecology screening")
    if phosphate_mg_l is not None and phosphate_mg_l > 0.1: extended.append(f"Phosphate {_num(phosphate_mg_l)} mg/L may promote eutrophication")
    if turbidity_ntu is not None and turbidity_ntu > 25: extended.append(f"Turbidity {_num(turbidity_ntu)} NTU is high for healthy stream habitat")
    if temperature_c is not None and temperature_c > 32: extended.append(f"Temperature {_num(temperature_c)}°C is stressful for many stream organisms")

    return _result("aquatic_life", core, extended, checked)


def fit_for_bathing(pH=None, dissolved_oxygen_mg_l=None, bod_mg_l=None, total_coliform_mpn_100ml=None,
                    fecal_coliform_mpn_100ml=None, turbidity_ntu=None, e_coli_present=None):
    """Recreational / bathing screening. Faecal coliform takes precedence over total coliform."""
    checked = dict(locals())
    core, extended = [], []

    if pH is not None and not 6.5 <= pH <= 8.5: core.append(f"pH {_num(pH)} outside 6.5-8.5")
    if dissolved_oxygen_mg_l is not None and dissolved_oxygen_mg_l < 5.0: core.append(f"DO {_num(dissolved_oxygen_mg_l)} mg/L below 5.0 mg/L")
    if bod_mg_l is not None and bod_mg_l > 3.0: core.append(f"BOD {_num(bod_mg_l)} mg/L exceeds 3.0 mg/L")
    if fecal_coliform_mpn_100ml is not None:
        if fecal_coliform_mpn_100ml > 0: core.append(f"Fecal coliform {_num(fecal_coliform_mpn_100ml)} MPN/100mL should be 0")
    elif total_coliform_mpn_100ml is not None and total_coliform_mpn_100ml > 0:
        core.append(f"Total coliform {_num(total_coliform_mpn_100ml)} MPN/100mL should be 0")

    if turbidity_ntu is not None and turbidity_ntu > 10: extended.append(f"Turbidity {_num(turbidity_ntu)} NTU is high for safe/pleasant bathing")
    if e_coli_present is True: extended.append("E. coli detected")

    return _result("bathing", core, extended, checked)


RULES = {
    "human_consumption": fit_for_human_consumption,
    "agriculture": fit_for_agriculture,
    "aquatic_life": fit_for_aquatic_life,
    "bathing": fit_for_bathing,
}


def screen(use_case: str, values: dict[str, Any]) -> dict[str, Any]:
    """Run one use case's rules on a dict of screening inputs; unknown keys are ignored."""
    rule = RULES[use_case]
    accepted = rule.__code__.co_varnames[:rule.__code__.co_argcount]
    return rule(**{key: values[key] for key in accepted if key in values})


def suitability_status(use_case: str, result: dict[str, Any]) -> str:
    """Collapse a screening result into "safe", "caution", "unsafe" or "unknown"."""
    if not any(result["checked_values"].get(key) is not None for key in CORE_KEYS_BY_USE_CASE[use_case]):
        return "unknown"
    if not result["fit_core"]:
        return "unsafe"
    return "safe" if result["fit_extended"] else "caution"


# --- Samples ----------------------------------------------------------------------------

def _coverage_label(key: str, parameter: str = "") -> str:
    label = INPUT_LABELS.get(key, key)
    return f"{label} via {parameter}" if parameter else label


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _match(records: list[dict[str, Any]], aliases: list[str]) -> dict[str, Any] | None:
    """Best numeric record for any alias, preferring plain readings over "(max)"/"(min)" ones."""
    wanted = {alias.lower() for alias in aliases}
    if not wanted:
        return None
    candidates = [record for record in records
                  if parameter_family(record.get("parameter")).lower() in wanted and _is_number(record.get("numericValue"))]
    # Stable sorts, least significant key first: file name descending, then variant.
    candidates.sort(key=lambda record: str(record.get("fileName", "")), reverse=True)
    candidates.sort(key=lambda record: (bool(parameter_variant(record["parameter"])), parameter_variant(record["parameter"]).lower()))
    return candidates[0] if candidates else None


def extract_screening_inputs(records: list[dict[str, Any]], use_case: str) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Pull one use case's inputs from a sample's records.

    ``records`` are dashboard records (``parameter``, ``numericValue``, ``fileName``) from a
    single station and sample date. Returns the input values and a coverage report listing
    which inputs were confirmed, only available as a proxy, or missing.
    """
    values: dict[str, Any] = dict.fromkeys(INPUT_LABELS)
    coverage: dict[str, list[str]] = {"confirmed": [], "proxy": [], "missing": []}
    for spec in SCREENING_PARAMETER_SPECS[use_case]:
        confirmed = _match(records, spec.get("confirmed", []))
        if confirmed:
            values[spec["key"]] = confirmed["numericValue"]
            coverage["confirmed"].append(_coverage_label(spec["key"], confirmed["parameter"]))
            continue
        proxy = _match(records, spec.get("proxy", []))
        if proxy:
            coverage["proxy"].append(_coverage_label(spec["key"], proxy["parameter"]))
            continue
        coverage["missing"].append(_coverage_label(spec["key"]))
    return values, coverage


def evaluate_sample(records: list[dict[str, Any]], use_case: str) -> dict[str, Any]:
    """Screen one station sample: status, display label, reasons and input coverage."""
    values, coverage = extract_screening_inputs(records, use_case)
    result = screen(use_case, values)
    status = suitability_status(use_case, result)
    return {
        "status": status,
        "label": STATUS_LABELS[status],
        "reasons": result["core_reasons"] + result["extended_reasons"],
        "coverage": coverage,
    }


def sample_key(record: dict[str, Any]) -> str:
    """Identifies a sample within a station: its source file and date sort key."""
    return f"{record.get('fileName', '')}|{record.get('sortKey', '')}"


def group_samples(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Group dashboard records as {station: {sample key: records}}."""
    stations: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for record in records:
        stations.setdefault(record["locationGroup"], {}).setdefault(sample_key(record), []).append(record)
    return stations


def screen_stations(records: Iterable[dict[str, Any]], use_case: str, *, year: int | None = None,
                    month: int | None = None) -> list[dict[str, Any]]:
    """Screen each station's latest sample, optionally limited to a year and/or month (1-12).

    This is the same selection the dashboard makes for its year/month filters.
    """
    results = []
    for station, samples in group_samples(records).items():
        matching = [sample for sample in samples.values()
                    if (year is None or sample[0]["year"] == year) and (month is None or sample[0]["monthIndex"] == month)]
        if not matching:
            results.append({"location": station, "sample": None, "status": "unknown", "label": STATUS_LABELS["unknown"],
                            "reasons": ["No sample matches the requested period."], "coverage": None})
            continue
        latest = max(matching, key=lambda sample: (sample[0]["sortKey"], sample[0]["fileName"]))
        results.append({"location": station, "sample": latest[0]["dateLabel"], **evaluate_sample(latest, use_case)})
    return results


def build_quality_payload(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Everything the dashboard needs for suitability and safety scales.

    ``samples`` is {station: {sample key: {use case: evaluation}}} covering every sample, so
    the browser only chooses which sample matches the active filters.
    """
    records = list(records)
    # The dashboard's parameter tabs use families ("DO"), records may carry variants ("DO (min)").
    parameters = {str(record.get("parameter", "")) for record in records}
    parameters |= {parameter_family(parameter) for parameter in parameters}
    return {
        "useCases": USE_CASES,
        "statusLabels": STATUS_LABELS,
        "scales": PARAMETER_SCALE_DEFINITIONS,
        "globalScales": GLOBAL_PARAMETER_SCALE_DEFINITIONS,
        "scaleKeys": {parameter: scale_key(parameter) for parameter in sorted(parameters)},
        "samples": {
            station: {key: {use_case: evaluate_sample(sample, use_case) for use_case in USE_CASE_KEYS}
                      for key, sample in samples.items()}
            for station, samples in group_samples(records).items()
        },
    }
