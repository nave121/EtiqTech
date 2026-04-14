import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from bs4 import BeautifulSoup, Tag

try:
    from .avma_matrix import normalize_method, normalize_species
except ImportError:
    from avma_matrix import normalize_method, normalize_species

# Import the schema to ensure we match structure (optional, but good practice)
# from .schema import IACUC_SCHEMA_V2

def _clean_text(text: str) -> str:
    """Clean whitespace and normalize text."""
    if not text:
        return ""
    return " ".join(text.strip().split())


_USDA_PAIN_CATEGORY_RE = re.compile(
    r"\b(?:USDA\s*)?(?:category|cat\.?)?\s*([BCDE])\b",
    re.IGNORECASE,
)


def _parse_pain_category_structured(raw_text: str) -> Dict[str, Optional[str]]:
    """Preserve raw text and normalize explicit USDA B/C/D/E categories when present."""
    raw = _clean_text(raw_text)
    parsed = None
    if raw:
        match = _USDA_PAIN_CATEGORY_RE.search(raw)
        if match:
            parsed = match.group(1).upper()
    return {"raw": raw, "parsed": parsed}


def _structured_species(raw: str) -> str:
    """Return canonical species key when it can be resolved safely."""
    return normalize_species(raw) or ""


def _structured_method(raw: str) -> str:
    """Return canonical euthanasia method key when it can be resolved safely."""
    return normalize_method(raw) or ""


def _extract_pain_category(text: str) -> str:
    """Extract explicit USDA B/C/D/E pain category text without guessing."""
    if not text:
        return ""
    cleaned = _clean_text(text)
    matchers = [
        r"(?:pain\s*category|category|usda|קטגוריה(?:\s+של\s+כאב)?)[^A-Za-z0-9]{0,10}([BCDE])\b",
        r"^\s*([BCDE])\s*$",
    ]
    for pattern in matchers:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return ""


def _first_present(row: Dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key, "")
        if value:
            return _clean_text(value)
    return ""


def _flatten_values(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten_values(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten_values(item) for item in value)
    return str(value)


def _normalize_anesthesia_drug_row(row: Dict[str, str]) -> Optional[Dict[str, str]]:
    """Normalize structured anesthesia drug table rows when required fields exist."""
    agent = _first_present(row, "Agent", "agent", "שם החומר")
    dose = _first_present(row, "Dose", "dose", "מינון")
    route = _first_present(row, "Route", "route", "מסלול", "דרך מתן")
    frequency = _first_present(row, "Frequency", "frequency", "תדירות")
    if not (agent and dose and route and frequency):
        return None
    return {
        "agent": agent,
        "dose": dose,
        "route": route,
        "frequency": frequency,
        "rationale": _first_present(row, "Rationale", "rationale", "נימוק"),
        "induction": _first_present(row, "Induction", "induction"),
        "maintenance": _first_present(row, "Maintenance", "maintenance"),
        "monitoring": _first_present(row, "Monitoring", "monitoring"),
        "source_text": " | ".join(
            _clean_text(value) for value in row.values() if _clean_text(value)
        ),
    }


_RENDERED_BOOL_KEYS = {
    "used",
    "breeding_with_litter",
    "fully_recovered",
    "vet_consulted",
    "field_study",
    "wildlife",
    "protected_species",
    "wildlife_pathogen_handling",
}
_RENDERED_INT_KEYS = {"animals_per_enclosure", "sessions_per_animal"}
_RENDERED_FLOAT_KEYS = {"cage_floor_area_cm2", "max_duration_minutes"}


def _parse_rendered_scalar(key: str, value: str) -> Any:
    """Coerce simple rendered key/value strings back to stable scalar types."""
    cleaned = _clean_text(value)
    lowered = cleaned.lower()
    if key in _RENDERED_BOOL_KEYS:
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    if key in _RENDERED_INT_KEYS:
        try:
            return int(cleaned)
        except ValueError:
            return cleaned
    if key in _RENDERED_FLOAT_KEYS:
        try:
            return float(cleaned)
        except ValueError:
            return cleaned
    return cleaned


def _parse_rendered_kv_block(block: Tag) -> Dict[str, Any]:
    """Parse renderer-produced key/value mini-blocks back into dicts."""
    parsed: Dict[str, Any] = {}
    for div in block.find_all("div"):
        text = _clean_text(div.get_text())
        if ":" not in text:
            continue
        key, value = text.split(":", 1)
        key = key.strip()
        parsed[key] = _parse_rendered_scalar(key, value)
    return parsed

def _parse_key_value_table(table: Tag) -> Dict[str, str]:
    """Parse a vertical table (Label | Value) into a dict.

    Only processes direct-child <tr> elements to avoid contamination from
    nested tables (e.g. anesthesia drug tables inside a rationale cell).
    """
    data = {}
    tbody = table.find("tbody", recursive=False) or table
    rows = tbody.find_all("tr", recursive=False)
    for row in rows:
        cells = row.find_all("td", recursive=False)
        i = 0
        while i < len(cells):
            c = cells[i]
            if i + 1 < len(cells):
                key = _clean_text(c.get_text())
                val = _clean_text(cells[i+1].get_text())
                if key:
                    data[key] = val
                i += 2
            else:
                i += 1
    return data

def _parse_kv_table_with_tags(table: Tag) -> Dict[str, Tag]:
    """Like _parse_key_value_table but returns value *Tags* (not strings).

    Useful when a value cell may contain a nested table that needs
    separate parsing (e.g. Council-format anesthesia drug tables).
    """
    data: Dict[str, Tag] = {}
    tbody = table.find("tbody", recursive=False) or table
    rows = tbody.find_all("tr", recursive=False)
    for row in rows:
        cells = row.find_all("td", recursive=False)
        i = 0
        while i < len(cells):
            c = cells[i]
            if i + 1 < len(cells):
                key = _clean_text(c.get_text())
                if key:
                    data[key] = cells[i + 1]
                i += 2
            else:
                i += 1
    return data


def _parse_horizontal_table(table: Tag) -> List[Dict[str, str]]:
    """Parse a horizontal table (Header row | Data rows)."""
    data = []
    rows = table.find_all("tr")
    if not rows:
        return data

    # Find the header row (first row with TH or just first row)
    header_row = rows[0]
    headers = [_clean_text(c.get_text()) for c in header_row.find_all(["th", "td"])]

    # Data
    for row in rows[1:]:
        cells = row.find_all("td")
        row_data = {}
        # If empty row or not enough cells, skip or partial fill
        if not cells: continue
        
        for i, cell in enumerate(cells):
            if i < len(headers):
                row_data[headers[i]] = _clean_text(cell.get_text())
        if row_data:
            data.append(row_data)
    return data

def parse_html(html_content: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html_content, "html.parser")
    instance = {}

    # --- 1. Header ---
    header_div = soup.find("div", class_="header")
    instance["header"] = {
        "protocol_id": "",
        "institution": "",
        "subcommittee": "",
        "export_version": "2.0.0" # Default
    }
    if header_div:
        for div in header_div.find_all("div"):
            txt = div.get_text()
            if "בקשת ניסוי מס" in txt:
                span = div.find("span")
                if span:
                    instance["header"]["protocol_id"] = _clean_text(span.get_text())
            elif "שם המוסד" in txt:
                span = div.find("span")
                if span:
                    instance["header"]["institution"] = _clean_text(span.get_text())

    # --- 2. Research ---
    research = {}
    # Regex for loose matching
    res_header = soup.find("div", class_="sub-header", string=re.compile(r"^\s*המחקר\s*$"))
    if res_header:
        res_table = res_header.find_next("div", class_="table vertical").find("table")
        if res_table:
            res_data = _parse_key_value_table(res_table)
            
            research["title_he"] = res_data.get("נושא המחקר בעברית", "")
            research["title_en"] = res_data.get("נושא המחקר באנגלית", "")
            research["is_continuation"] = (res_data.get("האם זה מחקר המשך?") == "המשך")
            research["continuation_reason"] = res_data.get("סיבה למחקר המשך", "")
            research["prior_protocol_id"] = res_data.get("ציין את מס' הבקשה הקודם", "")
            research["third_party_service"] = (res_data.get("המחקר הוא מחקר שרות עבור מוסד צד ג?") == "כן")
            
            if research["third_party_service"]:
                instance["third_party"] = {
                    "sponsor_org": res_data.get("שם המוסד המזמין", ""),
                    "ordering_investigator_name": res_data.get("שם החוקר המזמין", ""),
                    "sponsor_approver_name": res_data.get("שם המאשר במוסד המזמין", ""),
                    "declaration_url": res_data.get("קישור לצרופת הצהרת צד ג'", "")
                }

            # Term
            term_str = res_data.get("תוקף האישור המבוקש (שנים)", "")
            match = re.search(r"(\d+)", term_str)
            research["approval_term_years"] = int(match.group(1)) if match else 4
            
            # Sites
            sites_str = res_data.get("אתר ביצוע המחקר", "")
            research["sites"] = [{"name": s.strip(), "steps": ["כל השלבים"]} for s in sites_str.split(",") if s.strip()]

    # Defaults if not found
    if "title_he" not in research: research["title_he"] = ""
    if "title_en" not in research: research["title_en"] = ""
    
    # Request type logic (inference)
    research["request_type"] = "regular"
    if "פיילוט" in research["title_he"] or "Pilot" in research["title_en"]:
        research["request_type"] = "pilot"
    elif research.get("is_continuation"):
        # Could be continuation, but request_type field is enum regular|pilot|etc.
        pass 
        
    # --- 2b. Research Details (פרטי המחקר) — Council format ---
    purpose_header = soup.find("div", class_="sub-header", string=re.compile(r"פרטי המחקר"))
    if purpose_header:
        purpose_div = purpose_header.find_next("div", class_="table")
        if purpose_div and purpose_div.find("table"):
            purpose_data = _parse_key_value_table(purpose_div.find("table"))
            for k, v in purpose_data.items():
                if "מטרה ראשית" in k:
                    research["primary_purpose"] = v
                if "מטרה משנית" in k:
                    research["secondary_purpose"] = v

    instance["research"] = research

    # --- 3. PI ---
    pi = {}
    pi_header = soup.find("div", class_="sub-header", string=re.compile(r"^\s*החוקר הראשי\s*$"))
    if pi_header:
        pi_table = pi_header.find_next("div", class_="table vertical").find("table")
        if pi_table:
            pi_data = _parse_key_value_table(pi_table)
            
            pi["id_type"] = "TZ" if "ת.ז." in pi_data.get("סוג זהוי", "") else "passport"
            pi["id_number"] = pi_data.get("מספר זהוי", "")
            pi["last_name_he"] = pi_data.get("שם משפחה בעברית", "")
            pi["first_name_he"] = pi_data.get("שם פרטי בעברית", "")
            pi["last_name_en"] = pi_data.get("שם משפחה באנגלית", "")
            pi["first_name_en"] = pi_data.get("שם פרטי באנגלית", "")
            pi["email"] = pi_data.get("דואר אלקטרוני", "")
            pi["phone_primary"] = pi_data.get("טלפון נייד", "")
            pi["phone_secondary"] = pi_data.get("טלפון נוסף", "")
            pi["institutional_cert_no"] = pi_data.get("מס' הסמכה במוסד המחקר", "")
            pi["faculty"] = pi_data.get("פקולטה", "")
            pi["department"] = pi_data.get("מחלקה", "")
        
        # Training
        pi_training = []
        train_header = soup.find("div", class_="table-header", string=re.compile(r"^\s*הכשרות החוקר\s*$"))
        if train_header:
            train_table = train_header.find_next("div", class_="table horizontal").find("table")
            if train_table:
                train_rows = _parse_horizontal_table(train_table)
                for row in train_rows:
                    pi_training.append({
                        "cert_no": row.get("מס' תעודה", ""),
                        "issuer": row.get("מוסד נותן התעודה", ""),
                        "animal_scope": row.get('סוג בע"ח', ""),
                        "date": row.get("תאריך תעודה", "")
                    })
        pi["training"] = pi_training
    
    instance["pi"] = pi

    # --- 4. Participants ---
    participants = []
    part_header = soup.find("div", class_="sub-header", string=re.compile(r"^\s*משתתפים במחקר\s*"))
    if part_header:
        # Iterate through siblings until next sub-header
        curr = part_header.find_next_sibling()
        while curr and not (curr.name == "div" and "sub-header" in curr.get("class", [])):
            if curr.name == "div" and "table-header" in curr.get("class", []) and "משתתף מס" in curr.get_text():
                # New participant
                p_data = {}
                p_table = curr.find_next_sibling("div", class_="table horizontal").find("table")
                if p_table:
                    p_rows = _parse_horizontal_table(p_table)
                    if p_rows:
                        row = p_rows[0]
                        p_data["family_name"] = row.get("שם משפחה", "")
                        p_data["given_name"] = row.get("שם פרטי", "")
                        p_data["national_id_or_passport"] = row.get("מספר ת.ז / דרכון", "")
                        
                        role_he = row.get("קשר למחקר", "")
                        if "עובד עם" in role_he: p_data["role"] = "performs_procedures"
                        elif "חוקר ראשי" in role_he: p_data["role"] = "PI"
                        elif "משתתף" in role_he: p_data["role"] = "participant"
                        else: p_data["role"] = "participant" # Default
                        
                        p_data["certified"] = (row.get("מוסמך") == "כן")
                
                # Training
                p_train = []
                # Look ahead for training table. It usually follows immediately or after a gap.
                # Scan siblings until next "משתתף מס" or end of section
                scanner = curr.find_next_sibling()
                while scanner and not (scanner.name == "div" and "sub-header" in scanner.get("class", [])):
                    if scanner.name == "div" and "table-header" in scanner.get("class", []) and "משתתף מס" in scanner.get_text():
                        break # Found next participant
                    
                    if scanner.name == "div" and "table-header" in scanner.get("class", []) and "הכשרות" in scanner.get_text():
                         t_table = scanner.find_next_sibling("div", class_="table horizontal").find("table")
                         if t_table:
                             t_rows = _parse_horizontal_table(t_table)
                             for tr in t_rows:
                                 p_train.append({
                                     "cert_no": tr.get("מס' תעודה", ""),
                                     "issuer": tr.get("מוסד נותן תעודה", ""),
                                     "animal_scope": tr.get('סוג בע"ח', ""),
                                     "date": "" 
                                 })
                         break # Training found, stop scanning for this participant
                    scanner = scanner.find_next_sibling()

                p_data["training"] = p_train
                participants.append(p_data)
            
            curr = curr.find_next_sibling()
            
    instance["participants"] = participants
    
    # --- 5. Animals Total ---
    animals_total = []
    at_header = soup.find("div", class_="sub-header", string=re.compile(r"בעלי\s*ה?חיים\s*ה?דרושים"))
    if at_header:
        at_table = at_header.find_next("div", class_="table horizontal").find("table")
        if at_table:
            at_rows = _parse_horizontal_table(at_table)
            for row in at_rows:
                species_raw = row.get("בעל חיים", row.get("מין", ""))
                animals_total.append({
                    "species": species_raw,
                    "species_standard": row.get("מין מובנה", "") or _structured_species(species_raw),
                    "strain": row.get("זן/קווים", ""),
                    "genetic_status": row.get("סטטוס גנטי", ""),
                    "sex": row.get("זוויג", "both"), # Default if missing
                    "age": row.get("גיל", ""),
                    "n_total": int(row.get("כמות", 0)) if row.get("כמות") else 0,
                    "source": row.get("מקור", "")
                })
    instance["animals_total"] = animals_total

    # --- 6. Summaries & Justification ---
    n_just = {"method": "literature", "details": "", "attachments": []}
    nj_header = soup.find("div", class_="sub-header", string=re.compile("נימוק למספר בעלי החיים"))
    if nj_header:
        div = nj_header.find_next("div", class_="table").find("div")
        if div:
            txt = _clean_text(div.get_text())
            if ":" in txt:
                method, details = txt.split(":", 1)
                if method.lower() in ["power", "literature", "eda"]:
                    n_just["method"] = method.lower()
                    n_just["details"] = details.strip()
                else:
                    n_just["details"] = txt
            else:
                n_just["details"] = txt
    instance["n_justification"] = n_just
    
    summaries = {}
    # Scientific Abstract — matches both "תקציר מדעי" and Council "תקציר המחקר ומטרת השימוש"
    sci_header = soup.find("div", class_="sub-header", string=re.compile(r"(תקציר מדעי|תקציר המחקר)"))
    if sci_header:
        next_div = sci_header.find_next_sibling("div", class_="table")
        if next_div:
            if "vertical" in next_div.get("class", []):
                # It's a KV table (Council / Bad-example style)
                if next_div.find("table"):
                    data = _parse_key_value_table(next_div.find("table"))
                    # Council format has 6 sub-questions; extract all and concatenate
                    _summary_keys = [
                        "מהו הנושא המדעי אותו אתם חוקרים",
                        "מהו הרקע הרלוונטי למחקר",
                        "מהי השאלה הספציפית שתחקר בבקשה והרציונל המדעי לה",
                        "מהו השימוש המוצע בבעלי החיים ומדוע הוא מתאים לענות על השאלה שתחקר",
                        "מהו התוצר החזוי של מחקר זה",
                        "נמק את סיבת השימוש בבעלי חיים לצורך המחקר",
                    ]
                    parts = []
                    for sk in _summary_keys:
                        val = data.get(sk, "")
                        if val:
                            parts.append(val)
                    summaries["scientific_en_≤300w"] = " ".join(parts)
                    # Also store individual sub-questions for richer LLM context
                    summaries["_sub_questions"] = {
                        "topic": data.get(_summary_keys[0], ""),
                        "background": data.get(_summary_keys[1], ""),
                        "specific_question": data.get(_summary_keys[2], ""),
                        "proposed_animal_use": data.get(_summary_keys[3], ""),
                        "expected_outcome": data.get(_summary_keys[4], ""),
                        "animal_use_justification": data.get(_summary_keys[5], ""),
                    }
            else:
                # It's a text block (Demo style)
                summaries["scientific_en_≤300w"] = _clean_text(next_div.get_text())
    
    # Lay Summary
    lay_header = soup.find("div", class_="sub-header", string=re.compile("תקציר לקהל הרחב"))
    if lay_header:
        summaries["lay_he_≤150w"] = _clean_text(lay_header.find_next("div", class_="table").find("div").get_text())
    
    instance["summaries"] = summaries

    # --- 7. Alternatives ---
    alts = {"engines": [], "date": "", "queries": [], "conclusion": ""}
    alt_header = soup.find("div", class_="sub-header", string=re.compile("חיפוש חלופות"))
    if alt_header:
        curr = alt_header.find_next_sibling("div", class_="table")
        while curr:
            table = curr.find("table")
            if table:
                data = _parse_key_value_table(table)
                # Council format: "אופן חיפוש חלופות" → engines
                search_method = data.get("אופן חיפוש חלופות", "")
                if search_method:
                    alts["engines"] = [e.strip() for e in search_method.split(",") if e.strip()]
                if "פרוט אופן חיפוש אחר" in data and data["פרוט אופן חיפוש אחר"]:
                    alts["queries"].append(data["פרוט אופן חיפוש אחר"])
                if "תוצאות חיפוש החלופות" in data:
                    alts["conclusion"] = data["תוצאות חיפוש החלופות"]
                # "נבדקו חלופות?" boolean
                checked = data.get("נבדקו חלופות?", "")
                if checked:
                    alts["alternatives_checked"] = (checked == "כן")
            else:
                txt = _clean_text(curr.get_text())
                if txt.startswith("מנועים:"):
                    alts["engines"] = [x.strip() for x in txt.replace("מנועים:", "").split(",")]
                elif txt.startswith("תאריך:"):
                    alts["date"] = txt.replace("תאריך:", "").strip()
                elif txt.startswith("שאילתות:"):
                    alts["queries"] = [x.strip() for x in txt.replace("שאילתות:", "").split(";")]
                elif txt.startswith("מסקנה:"):
                    alts["conclusion"] = txt.replace("מסקנה:", "").strip()

            nxt = curr.find_next_sibling()
            if not nxt or (nxt.name == "div" and "sub-header" in nxt.get("class", [])) or nxt.name == "p":
                break
            curr = nxt
    instance["alternatives_search"] = alts

    # --- 7b. Preliminary experiments (ניסויים מקדימים) ---
    prelim_header = soup.find("div", class_="sub-header", string=re.compile(r"ניסויים מקדימים"))
    if prelim_header:
        prelim_div = prelim_header.find_next_sibling("div", class_="table")
        if prelim_div and prelim_div.find("table"):
            prelim_data = _parse_key_value_table(prelim_div.find("table"))
            prelim = {}
            for k, v in prelim_data.items():
                if "האם היו שלבים" in k:
                    prelim["had_alternative_methods"] = (v == "כן")
                if "פרוט הניסויים" in k:
                    prelim["details"] = v
            if prelim:
                alts["preliminary_experiments"] = prelim

    # --- 8. Experiments ---
    experiments = []
    
    # Detect experiment sections
    # Type A: sub-header "Experiment X" (Demo)
    # Type B: sub-header "Experiments in Research" then tables (Bad Example)
    
    exp_headers_a = soup.find_all("div", class_="sub-header", string=re.compile(r"ניסוי \d+"))
    exp_headers_b = soup.find_all("div", class_="sub-header", string=re.compile(r"\s*ניסויים במחקר\s*"))
    
    def parse_single_experiment(start_node, label):
        exp = {"label": label}
        
        # Determine if we are in Type A or Type B context
        # In Type A, start_node is the "Experiment X" header. The data follows.
        # In Type B, start_node is the TABLE containing "Experiment X".
        
        main_table = None
        if start_node.name == "div" and "table" in start_node.get("class", []):
            main_table = start_node.find("table")
        else:
            # Demo style: Animals table is horizontal immediately following
            next_div = start_node.find_next_sibling("div", class_="table horizontal")
            if next_div: main_table = next_div.find("table")

        if not main_table: return exp

        # Try parsing as key-value (Vertical / Bad Example style)
        data = _parse_key_value_table(main_table)

        # Experiment-level research question (Council main table)
        for k, v in data.items():
            if "שאלת המחקר" in k:
                exp["question"] = v
                break

        # 1. Animals
        if "חיות בניסוי" in str(main_table): # Rough check
             # In Bad Example, "Animals" is a nested table inside the value
             # Find the row with key "חיות בניסוי"
             tds = main_table.find_all("td")
             for i, td in enumerate(tds):
                 if "חיות בניסוי" in td.get_text():
                     # Find ALL nested tables
                     nested_tables = tds[i+1].find_all("table")
                     
                     # If multiple tables, aggregate them
                     if nested_tables:
                         aggregated = {
                             "species": set(), "strain": set(), "sex": set(),
                             "n": 0, "source": set(), "supplier": set(),
                             "age_val": 0.0, "age_unit": "",
                             "weight_val": 0.0, "weight_unit": "",
                             "genetic_status": set()
                         }
                         animal_groups = []

                         for nt in nested_tables:
                             a_data = _parse_key_value_table(nt)
                             if a_data.get("בעל חיים"): aggregated["species"].add(a_data["בעל חיים"])
                             if a_data.get("זן"): aggregated["strain"].add(a_data["זן"])
                             if a_data.get("מין"): aggregated["sex"].add(a_data["מין"])
                             if a_data.get("מקור בע\"ח"): aggregated["source"].add(a_data["מקור בע\"ח"])
                             if a_data.get("מקור אחר"): aggregated["supplier"].add(a_data["מקור אחר"])
                             if a_data.get("עבר שינוי גנטי"): aggregated["genetic_status"].add(a_data["עבר שינוי גנטי"])

                             n_val = int(a_data.get("כמות", 0)) if a_data.get("כמות") else 0
                             aggregated["n"] += n_val
                             aggregated["age_val"] = float(a_data.get("גיל", 0) or 0)
                             aggregated["age_unit"] = a_data.get("תקופת גיל", "")
                             if a_data.get("משקל"):
                                 aggregated["weight_val"] = float(a_data.get("משקל", 0) or 0)
                                 aggregated["weight_unit"] = a_data.get("מידת משקל", "")

                             # Per-group breakdown
                             group = {
                                 "species": a_data.get("בעל חיים", ""),
                                 "strain": a_data.get("זן", ""),
                                 "sex": a_data.get("מין", ""),
                                 "n": n_val,
                                 "age": {"value": float(a_data.get("גיל", 0) or 0), "unit": a_data.get("תקופת גיל", "")},
                                 "genetic_modification": a_data.get("עבר שינוי גנטי", ""),
                                 "source": a_data.get("מקור בע\"ח", ""),
                                 "supplier": a_data.get("מקור אחר", ""),
                             }
                             if a_data.get("משקל"):
                                 group["weight"] = {"value": float(a_data["משקל"]), "unit": a_data.get("מידת משקל", "")}
                             animal_groups.append(group)

                         exp["animals"] = {
                            "species": ", ".join(sorted(aggregated["species"])),
                            "species_standard": _structured_species(", ".join(sorted(aggregated["species"]))),
                            "strain": ", ".join(sorted(aggregated["strain"])),
                            "sex": ", ".join(sorted(aggregated["sex"])),
                            "n": aggregated["n"],
                            "age": {"value": aggregated["age_val"], "unit": aggregated["age_unit"]},
                            "source": ", ".join(sorted(aggregated["source"])),
                            "supplier": ", ".join(sorted(aggregated["supplier"])),
                            "genetic_status": ", ".join(sorted(aggregated["genetic_status"]))
                         }
                         if aggregated["weight_val"]:
                             exp["animals"]["weight"] = {"value": aggregated["weight_val"], "unit": aggregated["weight_unit"]}
                         if len(animal_groups) > 1:
                             exp["animals"]["groups"] = animal_groups
                     break
        
        # If no animals found yet, check if main_table IS the animals table (Demo style)
        if "animals" not in exp:
            # Check headers
            rows = _parse_horizontal_table(main_table)
            if rows and ("מין" in rows[0] or "Species" in rows[0]):
                r = rows[0]
                species_raw = r.get("מין")
                exp["animals"] = {
                    "species": species_raw,
                    "species_standard": r.get("מין מובנה", "") or r.get("Species standard", "") or _structured_species(species_raw),
                    "strain": r.get("זן/קווים"),
                    "genetic_status": r.get("סטטוס גנטי"),
                    "sex": r.get("זוויג"),
                    "n": int(r.get("כמות", 0)),
                    "source": r.get("מקור"),
                    "age": {"value": 0, "unit": ""} 
                }
                age_str = r.get("גיל", "")
                am = re.match(r"(\d+(\.\d+)?)\s*(weeks|days|months)", age_str, re.I)
                if am:
                    exp["animals"]["age"] = {"value": float(am.group(1)), "unit": am.group(3).lower()}

        # 2. Housing
        # In Bad Example, it's in `data`
        if "אופן החזקת בע\"ח" in data:
             exp["housing"] = {
                "group_housed": (data.get("אופן החזקת בע\"ח") == "קבוצה"),
                "enrichment": data.get("מהי ההעשרה שתינתן לבעה\"ח, ובמידה וחורגת מהמקובל, נא לנמק", "standard"),
                "single_housing_reason": "",
                "single_housing_duration_days": float(data.get("משך זמן החזקת חיה בודדת (במידה ונדרש)", 0) or 0)
            }
        else:
            # Demo style: Next horizontal table
            curr = start_node.find_next_sibling("div", class_="table horizontal")
            # If we parsed animals from the first horizontal table, we need the NEXT one
            # This logic is tricky because both are just "table horizontal" divs.
            # In demo: SubHeader -> Table(Animals) -> Table(Housing)
            
            # Let's look ahead
            sib = start_node.find_next_sibling()
            while sib:
                if "sub-header" in sib.get("class", []): break
                if "table" in sib.get("class", []) and "horizontal" in sib.get("class", []):
                    t = sib.find("table")
                    h_rows = _parse_horizontal_table(t)
                    if h_rows and "שיכון" in h_rows[0]:
                        r = h_rows[0]
                        exp["housing"] = {
                            "group_housed": (r.get("שיכון") == "קבוצתי"),
                            "enrichment": r.get("העשרה", "standard"),
                            "single_housing_reason": r.get("סיבת שיכון בודד", ""),
                            "single_housing_duration_days": float(r.get("משך שיכון בודד (ימים)", 0) or 0)
                        }
                        break
                sib = sib.find_next_sibling()

        # 3. Rationale, Timeline, etc.
        # Scan remaining siblings
        curr = start_node.find_next_sibling()
        while curr:
            if curr.name == "div" and "sub-header" in curr.get("class", []): break
            
            # Bad Example: Vertical table with Rationale/Timeline/Severity
            if curr.name == "div" and "table" in curr.get("class", []):
                # Check if this is a new experiment block (Bad Example case)
                t = curr.find("table")
                if t and "ניסוי" in t.get_text() and label not in t.get_text(): 
                    # It's a different experiment, stop scanning
                    # But wait, 'label' is "Experiment X". The text might be "ניסוי Y".
                    # We should rely on finding the specific "Experiment" row structure
                    # colspan=4 row with text "Experiment Y"
                    tr = t.find("tr")
                    if tr:
                        td = tr.find("td")
                        if td and "ניסוי" in td.get_text() and "colspan" in td.attrs:
                             break

            # Headers (Demo) or just content
            txt = curr.get_text()
            
            if "נימוק לבחירת" in txt or "נימוקים לבחירה" in txt:
                # Vertical table with rationale, severity, monitoring, etc.
                next_div = curr if "table" in curr.get("class", []) else curr.find_next_sibling("div", class_="table")
                if next_div and next_div.find("table"):
                    rationale_table = next_div.find("table")
                    r_data = _parse_key_value_table(rationale_table)
                    r_tags = _parse_kv_table_with_tags(rationale_table)
                    exp["rationale_species_strain_sex"] = r_data.get("הנימוק לבחירת סוג, זן ומין בעל החיים", "")

                    # Experiment-level research question (Council format)
                    for k, v in r_data.items():
                        if "שאלת המחקר" in k or "שאלה הספציפית" in k:
                            exp["question"] = v
                            break

                    # Timeline
                    for k, v in r_data.items():
                        if "תיאור מהלך הניסוי" in k:
                            exp["procedure_timeline"] = [{"day_or_timepoint": "All", "step": v}]
                            break

                    # Analgesia (Council format)
                    for k, v in r_data.items():
                        if "האם נעשה שימוש במשככי כאבים" in k:
                            exp["analgesia_used"] = (v == "כן")
                        if "סיבה לאי שימוש במשככי כאבים" in k:
                            exp["analgesia_justification_for_omission"] = v
                    # Parse analgesia drug table if present
                    for k, tag in r_tags.items():
                        if k == "משככי כאבים" and tag.find("table"):
                            analgesia_rows = _parse_horizontal_table(tag.find("table"))
                            analgesia_list = []
                            for ar in analgesia_rows:
                                analgesia_list.append({
                                    "agent": ar.get("שם החומר", ar.get("Agent", "")),
                                    "dose": ar.get("מינון", ar.get("Dose", "")),
                                    "route": ar.get("מסלול", ar.get("דרך מתן", ar.get("Route", ""))),
                                    "frequency": ar.get("משטר", ar.get("תדירות", ar.get("Frequency", ""))),
                                    "phase": "unknown",
                                })
                            if analgesia_list:
                                exp["analgesia"] = analgesia_list

                    # Anesthesia (Council format)
                    for k, v in r_data.items():
                        if "האם נעשה שימוש בחומרי הרדמה" in k:
                            exp["anesthesia_used"] = (v == "כן")
                    # Parse anesthesia drug table from nested table
                    # Council columns: שם החומר (agent), נימוק (rationale), משטר (regimen/dose), מינון (dose/timing)
                    for k, tag in r_tags.items():
                        if k == "חומרי הרדמה" and tag.find("table"):
                            anes_rows = _parse_horizontal_table(tag.find("table"))
                            anes_list = []
                            for ar in anes_rows:
                                agent = ar.get("שם החומר", ar.get("Agent", ""))
                                if not agent:
                                    continue
                                anes_list.append({
                                    "agent": agent,
                                    "dose": ar.get("משטר", ar.get("Dose", "")),
                                    "route": "",
                                    "frequency": ar.get("מינון", ar.get("Frequency", "")),
                                    "rationale": ar.get("נימוק", ar.get("Rationale", "")),
                                    "source_text": " | ".join(
                                        _clean_text(val) for val in ar.values() if _clean_text(val)
                                    ),
                                })
                            if anes_list:
                                exp["anesthesia_drugs"] = anes_list

                    # N justification per experiment
                    for k, v in r_data.items():
                        if "הנימוק למספר" in k and "בעלי" in k:
                            exp["n_justification_detail"] = v
                            break

                    # Regulatory requirement
                    for k, v in r_data.items():
                        if "צורך רגולטורי" in k:
                            exp["regulatory_requirement"] = (v == "כן")
                            break

                    # Prior experiment / reuse
                    for k, v in r_data.items():
                        if "נערך כבר ניסוי" in k:
                            exp["reuse_or_prior_procedures"] = {
                                "has_prior": (v == "כן"),
                                "prior_protocol_ids": [],
                            }
                        if "מס' הניסוי הקודם" in k and v:
                            if "reuse_or_prior_procedures" not in exp:
                                exp["reuse_or_prior_procedures"] = {"has_prior": True, "prior_protocol_ids": []}
                            exp["reuse_or_prior_procedures"]["prior_protocol_ids"] = [v]

                    # Severity/Monitoring/Euthanasia/Endpoints
                    for k, v in r_data.items():
                        if "דרגת כאב" in k:
                             pain_category = _parse_pain_category_structured(v)
                             exp["pain_category_structured"] = pain_category
                             match = re.search(r"\d", v)
                             exp["severity_level_1_to_5"] = int(match.group(0)) if match else 1
                             pain_category = _extract_pain_category(v)
                             if pain_category:
                                 exp["pain_category"] = pain_category
                        if "פירוט המעקב" in k:
                             exp["monitoring"] = {
                                 "initial_72h_daily": False,
                                 "ongoing_per_week": 1,
                                 "parameters": [v],
                                 "documentation": ""
                             }
                        if "שיטת המתה" in k:
                             exp["euthanasia"] = {
                                 "primary": v,
                                 "method_standard": _structured_method(v),
                                 "confirmation": "",
                                 "parameters": "",
                                 "conditions_text": "",
                             }
                        if "גורל בע''ח" in k:
                             exp["fate"] = v
                        if "תנאים כלליים להפסקת" in k:
                             if "humane_endpoints" not in exp: exp["humane_endpoints"] = {}
                             exp["humane_endpoints"]["general"] = [v]
                        if "תנאים ספציפיים" in k:
                             if "humane_endpoints" not in exp: exp["humane_endpoints"] = {}
                             exp["humane_endpoints"]["specific"] = [v]

                    # Skip past the rationale table div so demo-style parsers don't re-process it
                    if next_div != curr:
                        curr = next_div

            # Demo Timeline Table
            if "תיאור הניסוי ולו\"ז" in txt and "table-header" in curr.get("class", []):
                 t_table = curr.find_parent("div").find_next_sibling("div", class_="table horizontal").find("table")
                 if t_table:
                     t_rows = _parse_horizontal_table(t_table)
                     timeline = []
                     for r in t_rows:
                        timeline.append({
                            "day_or_timepoint": r.get("זמן/יום", ""),
                            "step": r.get("שלב", ""),
                            "route_or_site": r.get("מסלול/איבר", ""),
                            "volume_or_dose": r.get("נפח/מינון", ""),
                            "device_or_material": r.get("מכשור/חומר", "")
                        })
                     exp["procedure_timeline"] = timeline

            # Demo Severity/Monitoring Table (only if not already parsed from rationale KV)
            _already_has_severity = exp.get("pain_category_structured") is not None
            if curr.find("table") and "דרגת כאב וסבל" in txt and not _already_has_severity:
                 t = curr.find("table")
                 rows = _parse_horizontal_table(t)
                 if rows:
                     r = rows[0]
                     raw_pain_category = r.get("דרגת כאב וסבל", "")
                     exp["pain_category_structured"] = _parse_pain_category_structured(raw_pain_category)
                     match = re.search(r"\d", raw_pain_category)
                     exp["severity_level_1_to_5"] = int(match.group(0)) if match else 1
                     pain_category = (
                         r.get("קטגוריית כאב", "")
                         or r.get("Pain category", "")
                         or _extract_pain_category(" ".join(r.values()))
                     )
                     if pain_category:
                         exp["pain_category"] = pain_category
                     exp["monitoring"] = {
                         "initial_72h_daily": (r.get("ניטור 72ש ראשונות") == "כן"),
                         "ongoing_per_week": int(r.get("ניטור שבועי", 0)),
                         "parameters": [p.strip() for p in r.get("פרמטרים", "").split(",") if p.strip()],
                         "documentation": "Paper or electronic score sheets retained for audit."
                     }

            # Demo Euthanasia
            if "שיטת המתה" in txt:
                 t = curr.find("table")
                 rows = []
                 if t:
                     candidate_rows = _parse_horizontal_table(t)
                     if candidate_rows and any(
                         key in candidate_rows[0]
                         for key in ("ראשית", "שיטה מובנית", "Method standard", "פרמטרים", "אישור מוות")
                     ):
                         rows = candidate_rows
                 if not rows:
                     next_table_div = curr.find_next_sibling("div", class_="table horizontal")
                     t = next_table_div.find("table") if next_table_div else None
                     rows = _parse_horizontal_table(t) if t else []
                 if rows:
                         r = rows[0]
                         primary = r.get("ראשית", "")
                         method_standard = (
                             r.get("שיטה מובנית", "")
                             or r.get("Method standard", "")
                             or _structured_method(primary)
                         )
                         conditions_text = (
                             r.get("תנאים", "")
                             or r.get("Conditions", "")
                             or r.get("פרמטרים", "")
                         )
                         exp["euthanasia"] = {
                             "primary": primary,
                             "method_standard": method_standard,
                             "parameters": r.get("פרמטרים", ""),
                             "conditions_text": conditions_text,
                             "confirmation": r.get("אישור מוות", ""),
                         }

            if "Structured Anesthesia Drugs" in txt and "table-header" in curr.get("class", []):
                 t = curr.find_next_sibling("div", class_="table horizontal").find("table")
                 if t:
                     rows = _parse_horizontal_table(t)
                     structured_rows = []
                     for row in rows:
                         normalized = _normalize_anesthesia_drug_row(row)
                         if normalized:
                             structured_rows.append(normalized)
                     if structured_rows:
                         exp["anesthesia_drugs"] = structured_rows

            # Demo Fate
            if "מצב אחרי הניסוי" in txt:
                 content = curr.find_next_sibling("div", class_="table")
                 if content: exp["fate"] = _clean_text(content.get_text())

            # Specialty Blocks (renderer-produced text-based key-values)
            if "table-header" in curr.get("class", []):
                specialty_titles = {
                    "Stereotaxic / Implant": "stereotaxic_implant",
                    "Oncology": "oncology",
                    "Diabetes": "diabetes",
                    "Biosafety & Infectious Agents": "biosafety_infectious_agents",
                    "Nanomaterials": "nanomaterials",
                    "Ocular Procedures": "ocular_procedures",
                    "Housing Density": "housing_density",
                    "Restraint": "restraint",
                    "Reuse Review": "reuse_review",
                    "Field Study Permits": "field_study_permits",
                }
                for title, field_name in specialty_titles.items():
                    if title not in txt:
                        continue
                    next_div = curr.find_next_sibling("div", class_="table")
                    if next_div:
                        parsed_block = _parse_rendered_kv_block(next_div)
                        if parsed_block:
                            exp[field_name] = parsed_block
                    break

            curr = curr.find_next_sibling()

        animals = exp.get("animals") or {}
        if animals and not animals.get("species_standard"):
            species_standard = _structured_species(animals.get("species", ""))
            if species_standard:
                animals["species_standard"] = species_standard
        pain_category = exp.get("pain_category", "")
        if not pain_category:
            inferred_pain_category = _extract_pain_category(
                " ".join(
                    [
                        exp.get("label", ""),
                        exp.get("question", ""),
                        _flatten_values(exp.get("procedure_timeline", [])),
                    ]
                )
            )
            if inferred_pain_category:
                exp["pain_category"] = inferred_pain_category
        euthanasia = exp.get("euthanasia") or {}
        if euthanasia and not euthanasia.get("method_standard"):
            method_standard = _structured_method(euthanasia.get("primary", ""))
            if method_standard:
                euthanasia["method_standard"] = method_standard
        if euthanasia and "conditions_text" not in euthanasia:
            euthanasia["conditions_text"] = euthanasia.get("parameters", "")
        return exp

    # Execute Parsing Strategy
    if exp_headers_a:
        for eh in exp_headers_a:
            exp_idx = eh.get_text().replace("ניסוי", "").strip()
            experiments.append(parse_single_experiment(eh, f"Experiment {exp_idx}"))
    elif exp_headers_b:
        # Loop through siblings of the container header to find tables
        container = exp_headers_b[0]
        curr = container.find_next_sibling()
        while curr:
            if curr.name == "div" and "sub-header" in curr.get("class", []): break
            if curr.name == "div" and "table" in curr.get("class", []):
                t = curr.find("table")
                if t:
                    # Check first row for "Experiment X"
                    tr = t.find("tr")
                    if tr:
                        td = tr.find("td")
                        if td and "ניסוי" in td.get_text():
                            label = _clean_text(td.get_text())
                            experiments.append(parse_single_experiment(curr, label))
            curr = curr.find_next_sibling()

    instance["experiments"] = experiments

    # --- 8b. Backfill animals_total from experiment data ---
    # Only backfill when animals_total is truly sparse (Council 3-column format:
    # num, species, count — missing strain AND sex AND genetic_status).
    if experiments and instance.get("animals_total"):
        for at in instance["animals_total"]:
            is_sparse = not at.get("strain") and not at.get("genetic_status") and (not at.get("sex") or at.get("sex") == "both")
            if not is_sparse:
                continue
            exp_animals = [e.get("animals", {}) for e in experiments if e.get("animals")]
            if not exp_animals:
                continue
            if not at.get("strain"):
                strains = set()
                for ea in exp_animals:
                    s = ea.get("strain", "")
                    if s:
                        strains.add(s)
                if strains:
                    at["strain"] = ", ".join(sorted(strains))
            if not at.get("genetic_status"):
                gs = set()
                for ea in exp_animals:
                    s = ea.get("genetic_status", "")
                    if s:
                        gs.add(s)
                if gs:
                    at["genetic_status"] = ", ".join(sorted(gs))
            if not at.get("sex") or at.get("sex") == "both":
                sexes = set()
                for ea in exp_animals:
                    s = ea.get("sex", "")
                    if s:
                        sexes.add(s)
                if sexes and len(sexes) == 1:
                    at["sex"] = sexes.pop()
            if not at.get("source"):
                sources = set()
                for ea in exp_animals:
                    s = ea.get("source", "")
                    if s:
                        sources.add(s)
                if sources:
                    at["source"] = ", ".join(sorted(sources))
            if not at.get("supplier"):
                suppliers = set()
                for ea in exp_animals:
                    s = ea.get("supplier", "")
                    if s:
                        suppliers.add(s)
                if suppliers:
                    at["supplier"] = ", ".join(sorted(suppliers))

    # --- 8c. Backfill n_justification from experiment data ---
    if not instance["n_justification"]["details"]:
        exp_details = [e.get("n_justification_detail", "") for e in experiments if e.get("n_justification_detail")]
        if exp_details:
            instance["n_justification"]["details"] = " ".join(exp_details)

    # --- 9. Postmortem ---
    pm = {"used": False}
    pm_header = soup.find("div", class_="sub-header", string=re.compile("עיבוד לאחר המתה"))
    if pm_header:
        curr = pm_header.find_next_sibling("div", class_="table")
        pm["used"] = True
        while curr and not (curr.name == "div" and "sub-header" in curr.get("class", [])):
             txt = _clean_text(curr.get_text())
             if "Perfusion:" in txt: pm["perfusion"] = txt.split(":", 1)[1].strip()
             if "Fixation:" in txt: pm["fixation"] = txt.split(":", 1)[1].strip()
             if "Technique:" in txt: pm["clearing_or_special_technique"] = txt.split(":", 1)[1].strip()
             if "Safety:" in txt: pm["chemical_safety_notes"] = txt.split(":", 1)[1].strip()
             curr = curr.find_next_sibling()
    instance["postmortem_processing"] = pm

    # --- 10. PI Declaration ---
    pi_decl = {"affirmations": []} 
    decl_header = soup.find("div", class_="sub-header", string=re.compile(r"(הצהרת החוקר|הצהרת החוקר הראשי)"))
    if decl_header:
        # Bad example has a table here
        next_div = decl_header.find_next_sibling("div", class_="table")
        if next_div and next_div.find("table"):
            data = _parse_key_value_table(next_div.find("table"))
            pi_decl["name"] = data.get("שם החוקר", "")
            pi_decl["date"] = data.get("תאריך הצהרה", "")
        else:
            # Demo style text blocks
            curr = decl_header.find_next_sibling("div", class_="table")
            while curr and not (curr.name == "div" and "sub-header" in curr.get("class", [])):
                txt = _clean_text(curr.get_text())
                if txt.startswith("שם:"): pi_decl["name"] = txt.replace("שם:", "").strip()
                if txt.startswith("תאריך:"): pi_decl["date"] = txt.replace("תאריך:", "").strip()
                curr = curr.find_next_sibling()
    instance["pi_declaration"] = pi_decl
    
    # --- 11. Chair Statement ---
    chair = {}
    ch_header = soup.find("div", class_="sub-header", string=re.compile('החלטת יו"ר'))
    if ch_header:
        curr = ch_header.find_next_sibling("div", class_="table")
        while curr:
            txt = _clean_text(curr.get_text())
            if txt.startswith("החלטה:"): chair["decision"] = txt.replace("החלטה:", "").strip()
            if txt.startswith("הערות:"): chair["comments"] = txt.replace("הערות:", "").strip()
            curr = curr.find_next_sibling()
    instance["chair_statement"] = chair
    
    # Missing fields that need defaults to pass schema if not found
    if "third_party" not in instance: instance["third_party"] = {}
    if "colony_block" not in instance: instance["colony_block"] = {}
    if "is_colony" not in instance: instance["is_colony"] = False

    return instance

def main():
    if len(sys.argv) < 2:
        print("Usage: python html_to_json.py <input_html> [output_json]")
        sys.exit(1)
    
    in_path = Path(sys.argv[1])
    html_content = in_path.read_text(encoding="utf-8")
    
    instance = parse_html(html_content)
    
    if len(sys.argv) > 2:
        out_path = Path(sys.argv[2])
        out_path.write_text(json.dumps(instance, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"Wrote {out_path}")
    else:
        print(json.dumps(instance, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
