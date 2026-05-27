#!/usr/bin/env python3
"""
GUSO Contract Processor
=======================

This script processes GUSO (Déclaration Unique et Simplifiée) contracts by:
- Extracting key information from PDF files
- Renaming files with a standardized format (YYYYMMDD - Employer - Hours.pdf)
- Generating a CSV summary of all contracts
- Calculating total working hours

Supports both old (v1) and new (v2) GUSO format contracts.

Usage:
    python rename-guso.py <year_folder> [options]

Examples:
    python rename-guso.py 2023
    python rename-guso.py 2023 --dry-run
    python rename-guso.py 2023 --backup
    python rename-guso.py 2023 --backup --output summary.csv
"""

import os
import re
import sys
import csv
import shutil
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Error: PyMuPDF is not installed. Install it with: pip install PyMuPDF")
    sys.exit(1)


# =============================================================================
# Configuration and Constants
# =============================================================================

# PDF Coordinates for data extraction (v2 format)
# Coordinates refined from the guso-sum project (config.yaml) for better precision
# and additional fields (employer_name, guso_to_pay).
V2_COORDS = {
    'title': fitz.Rect(122, 2, 460, 20),
    'employer_name': fitz.Rect(74.7268295288086, 156.9058380126953, 200, 167.8948211669922),
    'secu': fitz.Rect(385, 250.08998107910156, 500, 266.8900146484375),
    'begin_date': fitz.Rect(99, 364, 139, 375),
    'end_date': fitz.Rect(192, 364, 232, 375),
    'event': fitz.Rect(117, 484, 270, 495),
    'place': fitz.Rect(382, 484, 460, 495),
    'salary_brut_euros': fitz.Rect(154, 503, 167, 514),
    'salary_brut_cents': fitz.Rect(176, 504, 185, 515),
    'salary_net_euros': fitz.Rect(238, 624, 252, 635),
    'salary_net_cents': fitz.Rect(266, 605, 275, 616),
    'guso_to_pay_euros': fitz.Rect(518, 624, 533, 635),
    'guso_to_pay_cents': fitz.Rect(540, 624, 551, 635),
    # 'Emploi occupé' value sits at ~[76, 402.78, 142.88, 413.70]; cap at x=290
    # to stay well left of the 'Date et heure d'embauche :' field at x=314.64
    'job_title': fitz.Rect(75, 402, 290, 414),
    'hours': fitz.Rect(150, 420, 170, 440),
    # Alternative hours position observed in newer GUSO documents (guso-sum reference)
    'hours_alt': fitz.Rect(224, 807, 230, 814),
}

# PDF Coordinates for data extraction (v1 format)
V1_COORDS = {
    'salary_box': fitz.Rect(500, 450, 595, 680),
    'date_box': fitz.Rect(90, 542, 340, 545),
    'place': fitz.Rect(125.49600219726562, 492, 230, 507.0252685546875),
    'event': fitz.Rect(125, 485, 233, 490),
    'secu': fitz.Rect(190.40597534179688, 250.08998107910156, 400, 266.8900146484375),
}

DEFAULT_HOURS_V1 = 8

# When hours cannot be extracted from a v2 contract, it is almost certainly an
# artist GUSO (paid au cachet, no hours field). The CCT convention treats one
# cachet as the equivalent of 12 working hours for intermittent rights.
DEFAULT_HOURS_V2_ARTIST = 12


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class ContractData:
    """Data extracted from a GUSO contract."""
    original_filename: str
    new_filename: str
    format_version: str  # 'v1' or 'v2'
    begin_date: str
    end_date: str
    place: str
    event: str
    employer_name: str
    job_title: str  # 'Emploi occupé' — e.g. "Musicien", "Régisseur"
    hours: int
    salary_brut: float
    salary_net: float
    salary_charges: float  # brut - net (employee charges retenues)
    guso_to_pay: float  # total cost (brut + employer charges) paid to GUSO
    secu: str
    status: str = 'success'  # 'success', 'skipped', 'error'
    error_message: str = ''

    def to_dict(self) -> Dict:
        """Convert to dictionary for CSV export."""
        return asdict(self)


# =============================================================================
# Logging Setup
# =============================================================================

def setup_logging(log_level: str = 'INFO', log_file: Optional[str] = None) -> None:
    """
    Configure logging for the application.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional path to log file
    """
    handlers = [logging.StreamHandler()]

    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers,
        force=True
    )


# =============================================================================
# PDF Processing Functions
# =============================================================================

def list_pdf_files(folder_path: str) -> List[str]:
    """
    List all PDF files in a directory.

    Args:
        folder_path: Path to the directory

    Returns:
        List of PDF filenames
    """
    try:
        return [f for f in os.listdir(folder_path) if f.lower().endswith('.pdf')]
    except Exception as e:
        logging.error(f"Error listing PDF files in {folder_path}: {e}")
        return []


def is_new_guso_format(page: fitz.Page) -> bool:
    """
    Detect if the contract uses the new GUSO format (v2).

    Args:
        page: First page of the PDF document

    Returns:
        True if new format, False otherwise
    """
    try:
        title_text = page.get_textbox(V2_COORDS['title']).strip()
        is_v2 = title_text == "Déclaration unique et simplifiée"
        logging.debug(f"Format detection: {'v2' if is_v2 else 'v1'}")
        return is_v2
    except Exception as e:
        logging.warning(f"Error detecting format: {e}. Assuming v1 format.")
        return False


def _parse_euros_cents(page: fitz.Page, euros_rect: fitz.Rect, cents_rect: fitz.Rect) -> float:
    """
    Parse a euro/cents amount split across two text boxes.

    Args:
        page: PDF page
        euros_rect: Bounding box for the euros part
        cents_rect: Bounding box for the cents part

    Returns:
        The parsed amount as a float, or 0.0 if both parts are empty.
    """
    euros = page.get_textbox(euros_rect).replace(" ", "").replace("\n", "").strip()
    cents = page.get_textbox(cents_rect).replace(" ", "").replace("\n", "").strip()
    if not euros and not cents:
        return 0.0
    try:
        return float(f"{euros or '0'}.{cents or '0'}")
    except ValueError:
        return 0.0


def _normalize_place(place: str) -> str:
    """Normalize known place name variants (mirrors guso-sum behavior)."""
    place = place.strip()
    if place == "AKSHELTER" or place.startswith("AK"):
        return "AK SHELTER"
    return place


# Labels that precede the hours value in V2 contracts (variations across form versions)
_HOURS_LABELS = (
    "Nombre d'heures travaillées",
    "Nombre d'heures",
    "Heures travaillées",
)


def _parse_hours_number(text: str) -> Optional[int]:
    """Extract the first numeric value from a text snippet."""
    m = re.search(r"\d+(?:[,.]\d+)?", text)
    if not m:
        return None
    try:
        return int(float(m.group(0).replace(",", ".")))
    except ValueError:
        return None


def _extract_hours_v2(page: fitz.Page) -> Optional[int]:
    """
    Try multiple strategies to extract the number of hours from a v2 contract.

    Order: (1) primary fixed position, (2) alternate fixed position from guso-sum,
    (3) label search ("Nombre d'heures…") with value taken from a band to the right,
    (4) full-text regex looking for "<N> heures".
    """
    # Strategy 1 & 2: fixed positions
    for key in ('hours', 'hours_alt'):
        text = page.get_textbox(V2_COORDS[key]).strip()
        hours = _parse_hours_number(text)
        if hours is not None:
            logging.debug(f"Hours found via fixed position '{key}': {hours}")
            return hours

    # Strategy 3: locate a label and read the value just to the right of it
    for label in _HOURS_LABELS:
        rects = page.search_for(label)
        if not rects:
            continue
        for label_rect in rects:
            # Search a horizontal band right of the label, plus a small band below
            for value_rect in (
                fitz.Rect(label_rect.x1, label_rect.y0 - 2, label_rect.x1 + 120, label_rect.y1 + 2),
                fitz.Rect(label_rect.x0, label_rect.y1, label_rect.x1 + 120, label_rect.y1 + 18),
            ):
                text = page.get_textbox(value_rect).strip()
                hours = _parse_hours_number(text)
                if hours is not None:
                    logging.debug(f"Hours found via label '{label}': {hours}")
                    return hours

    # Strategy 4: regex on the full page text
    full_text = page.get_text()
    m = re.search(r"(\d+(?:[,.]\d+)?)\s*(?:heures|H\b)", full_text, re.IGNORECASE)
    if m:
        try:
            hours = int(float(m.group(1).replace(",", ".")))
            logging.debug(f"Hours found via full-text regex: {hours}")
            return hours
        except ValueError:
            pass

    return None


def _extract_job_title_v2(page: fitz.Page) -> str:
    """Extract 'Emploi occupé' from a v2 contract using the fixed value rect."""
    text = page.get_textbox(V2_COORDS['job_title']).replace("\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def extract_v2_data(page: fitz.Page) -> Dict:
    """
    Extract contract data from new format (v2) PDF.

    Args:
        page: First page of the PDF document

    Returns:
        Dictionary with extracted data

    Raises:
        ValueError: If required data cannot be extracted
    """
    try:
        data = {}

        # Extract salary information (brut, net, GUSO charge)
        data['salary_brut'] = _parse_euros_cents(
            page, V2_COORDS['salary_brut_euros'], V2_COORDS['salary_brut_cents']
        )
        data['salary_net'] = _parse_euros_cents(
            page, V2_COORDS['salary_net_euros'], V2_COORDS['salary_net_cents']
        )
        data['guso_to_pay'] = _parse_euros_cents(
            page, V2_COORDS['guso_to_pay_euros'], V2_COORDS['guso_to_pay_cents']
        )

        # Extract dates
        data['begin_date'] = page.get_textbox(V2_COORDS['begin_date']).strip()
        data['end_date'] = page.get_textbox(V2_COORDS['end_date']).strip()

        # Extract location, event, employer
        data['place'] = _normalize_place(page.get_textbox(V2_COORDS['place']))
        data['event'] = page.get_textbox(V2_COORDS['event']).strip()
        employer = page.get_textbox(V2_COORDS['employer_name']).replace("\n", " ")
        # Strip "Article L. 7121-7-1 du code du travail" if it bleeds into the rect
        employer = re.sub(r"Article\s+L\.\s*[\d\-]+\s*du\s+code\s+du(?:\s+travail)?",
                          "", employer, flags=re.IGNORECASE)
        data['employer_name'] = re.sub(r"\s+", " ", employer).strip()

        # Extract job title ("Emploi occupé") via label search
        data['job_title'] = _extract_job_title_v2(page)

        # Extract hours using multi-strategy fallback (position + label search + regex).
        # If still not found, assume it's an artist GUSO (paid au cachet) and apply
        # the conventional 1 cachet = 12H equivalence used for intermittent rights.
        hours = _extract_hours_v2(page)
        if hours is None:
            job = data.get('job_title') or "<unknown>"
            logging.warning(
                f"Hours field not found (Emploi occupé: {job!r}) — assuming artist "
                f"GUSO, defaulting to {DEFAULT_HOURS_V2_ARTIST}H (1 cachet = "
                f"{DEFAULT_HOURS_V2_ARTIST}H)"
            )
            hours = DEFAULT_HOURS_V2_ARTIST
        data['hours'] = hours

        # Extract social security number
        data['secu'] = page.get_textbox(V2_COORDS['secu']).replace("\n", "").strip()

        # Validate essential fields
        if not data['begin_date'] or not data['place']:
            raise ValueError("Missing essential data (date or place)")

        return data

    except Exception as e:
        raise ValueError(f"Failed to extract v2 data: {e}")


def extract_v1_data(page: fitz.Page) -> Dict:
    """
    Extract contract data from old format (v1) PDF.

    Args:
        page: First page of the PDF document

    Returns:
        Dictionary with extracted data

    Raises:
        ValueError: If required data cannot be extracted
    """
    try:
        data = {}

        # Extract salary information
        text_box_salary = page.get_textbox(V1_COORDS['salary_box']).split('\n ')
        text_box_salary_clean = [s.replace(" ", "") for s in text_box_salary]

        if len(text_box_salary_clean) < 10:
            raise ValueError("Salary box doesn't contain enough data")

        # Parse salaries (stored as cents, e.g., "12345" = 123.45€)
        salary_net_str = text_box_salary_clean[9]
        if len(salary_net_str) >= 2:
            data['salary_net'] = float(salary_net_str[:-2] + "." + salary_net_str[-2:])
        else:
            data['salary_net'] = 0.0

        salary_brut_str = text_box_salary_clean[1]
        if len(salary_brut_str) >= 2:
            data['salary_brut'] = float(salary_brut_str[:-2] + "." + salary_brut_str[-2:])
        else:
            data['salary_brut'] = 0.0

        # Extract dates
        date_lines = page.get_textbox(V1_COORDS['date_box']).split('\n')
        if len(date_lines) < 8:
            raise ValueError("Date box doesn't contain enough lines")

        begin_date_str = date_lines[6].replace("  ", "/").replace("//", "/").replace(" ", "")
        parsed_date = datetime.strptime(begin_date_str, "%d/%m/%y")
        data['begin_date'] = parsed_date.strftime("%d/%m/%Y")

        end_date_str = date_lines[7].replace("  ", "/").replace("//", "/").replace(" ", "")
        parsed_end_date = datetime.strptime(end_date_str, "%d/%m/%y")
        data['end_date'] = parsed_end_date.strftime("%d/%m/%Y")

        # Extract location and event
        data['place'] = _normalize_place(page.get_textbox(V1_COORDS['place']))
        data['event'] = page.get_textbox(V1_COORDS['event']).strip()

        # Extract social security number
        data['secu'] = page.get_textbox(V1_COORDS['secu']).replace(" ", "").replace("\n", "").strip()

        # Fields not present in v1 format
        data['employer_name'] = ''
        data['job_title'] = ''
        data['guso_to_pay'] = 0.0

        # Default hours for v1 format (not always present in the document)
        data['hours'] = DEFAULT_HOURS_V1

        # Validate essential fields
        if not data['begin_date'] or not data['place']:
            raise ValueError("Missing essential data (date or place)")

        return data

    except Exception as e:
        raise ValueError(f"Failed to extract v1 data: {e}")


def generate_new_filename(begin_date: str, label: str, hours: int) -> str:
    """
    Generate standardized filename for a contract.

    Args:
        begin_date: Date in DD/MM/YYYY format
        label: Employer name (v2) or place (v1 fallback)
        hours: Number of hours

    Returns:
        Standardized filename (YYYYMMDD - Employer - HoursH.pdf)

    Raises:
        ValueError: If date format is invalid
    """
    try:
        # Parse and reformat date
        date_parts = begin_date.split("/")
        if len(date_parts) != 3:
            raise ValueError(f"Invalid date format: {begin_date}")

        day, month, year = date_parts

        # Clean up label (remove path separators that could break filename)
        clean_label = label.replace("/", "-").replace("\\", "-").strip()
        if not clean_label:
            raise ValueError("Empty employer/place label")

        # Generate filename
        new_filename = f"{year}{month}{day} - {clean_label} - {hours}H.pdf"

        return new_filename

    except Exception as e:
        raise ValueError(f"Failed to generate filename: {e}")


def is_already_renamed(filename: str) -> bool:
    """
    Check if a file has already been renamed to the new format.

    A renamed file matches "YYYYMMDD - <label> - <N>H.pdf". Files mangled by a
    previous buggy run (label starts with "Article L.") are NOT considered
    renamed, so re-running the script repairs them.

    Args:
        filename: Name of the file

    Returns:
        True if already renamed, False otherwise
    """
    if not re.match(r"^\d{8} - ", filename):
        return False
    parts = filename.split(" - ", 2)
    if len(parts) >= 2 and re.match(r"^Article\s+L\.", parts[1], re.IGNORECASE):
        return False
    return True


def extract_hours_from_renamed_file(filename: str) -> Optional[int]:
    """
    Extract hours from an already renamed file.

    Args:
        filename: Renamed filename (YYYYMMDD - Location - HoursH.pdf)

    Returns:
        Number of hours, or None if parsing fails
    """
    try:
        # Split by " - " and get the last part
        parts = filename.split(" - ")
        if len(parts) >= 3:
            # Last part should be like "8H.pdf"
            hours_part = parts[-1].split("H")[0].strip()
            return int(hours_part)
    except (ValueError, IndexError):
        logging.warning(f"Could not extract hours from filename: {filename}")

    return None


def process_pdf_contract(
    pdf_path: str,
    contracts_folder: str,
    dry_run: bool = False,
    backup: bool = False,
    no_cache: bool = False
) -> ContractData:
    """
    Process a single PDF contract: extract data and rename file.

    Args:
        pdf_path: Full path to the PDF file
        contracts_folder: Path to the contracts directory
        dry_run: If True, don't actually rename files
        backup: If True, create backup before renaming
        no_cache: If True, re-process files even if they look already renamed

    Returns:
        ContractData object with extraction results
    """
    filename = os.path.basename(pdf_path)

    # Check if already renamed (unless --no-cache forces re-processing)
    if not no_cache and is_already_renamed(filename):
        logging.info(f"Skipping already renamed file: {filename}")
        hours = extract_hours_from_renamed_file(filename)

        # Try to extract the middle label from filename (employer under the new
        # convention; place for files renamed by older versions of this script)
        try:
            parts = filename.split(" - ")
            label = parts[1] if len(parts) >= 3 else "Unknown"
        except:
            label = "Unknown"

        return ContractData(
            original_filename=filename,
            new_filename=filename,
            format_version='unknown',
            begin_date='',
            end_date='',
            place='',
            event='',
            employer_name=label,
            job_title='',
            hours=hours or 0,
            salary_brut=0.0,
            salary_net=0.0,
            salary_charges=0.0,
            guso_to_pay=0.0,
            secu='',
            status='skipped'
        )

    logging.info(f"Processing: {filename}")

    try:
        # Open PDF
        with fitz.open(pdf_path) as doc:
            if len(doc) == 0:
                raise ValueError("PDF has no pages")

            page = doc[0]

            # Check if PDF has text
            pdf_text = page.get_text()
            if not pdf_text or pdf_text.strip() == '':
                raise ValueError("PDF contains no text (might be scanned image)")

            # Detect format and extract data
            if is_new_guso_format(page):
                format_version = 'v2'
                extracted_data = extract_v2_data(page)
            else:
                format_version = 'v1'
                extracted_data = extract_v1_data(page)

            # Generate new filename — prefer employer_name (v2); fall back to place (v1)
            filename_label = extracted_data.get('employer_name') or extracted_data['place']
            new_filename = generate_new_filename(
                extracted_data['begin_date'],
                filename_label,
                extracted_data['hours']
            )

            # Rename file (unless dry-run)
            if not dry_run:
                new_path = os.path.join(contracts_folder, new_filename)

                # Create backup if requested
                if backup:
                    backup_folder = os.path.join(contracts_folder, 'backup')
                    os.makedirs(backup_folder, exist_ok=True)
                    backup_path = os.path.join(backup_folder, filename)
                    shutil.copy2(pdf_path, backup_path)
                    logging.debug(f"Backup created: {backup_path}")

                # Rename the file
                os.rename(pdf_path, new_path)
                logging.info(f"Renamed: {filename} -> {new_filename}")
            else:
                logging.info(f"[DRY-RUN] Would rename: {filename} -> {new_filename}")

            # Compute derived values
            salary_brut = extracted_data['salary_brut']
            salary_net = extracted_data['salary_net']
            salary_charges = round(salary_brut - salary_net, 2) if salary_brut and salary_net else 0.0

            # Create ContractData object
            return ContractData(
                original_filename=filename,
                new_filename=new_filename,
                format_version=format_version,
                begin_date=extracted_data['begin_date'],
                end_date=extracted_data['end_date'],
                place=extracted_data['place'],
                event=extracted_data['event'],
                employer_name=extracted_data.get('employer_name', ''),
                job_title=extracted_data.get('job_title', ''),
                hours=extracted_data['hours'],
                salary_brut=salary_brut,
                salary_net=salary_net,
                salary_charges=salary_charges,
                guso_to_pay=extracted_data.get('guso_to_pay', 0.0),
                secu=extracted_data['secu'],
                status='success'
            )

    except Exception as e:
        error_msg = f"Error processing {filename}: {e}"
        logging.error(error_msg)

        return ContractData(
            original_filename=filename,
            new_filename='',
            format_version='unknown',
            begin_date='',
            end_date='',
            place='',
            event='',
            employer_name='',
            job_title='',
            hours=0,
            salary_brut=0.0,
            salary_net=0.0,
            salary_charges=0.0,
            guso_to_pay=0.0,
            secu='',
            status='error',
            error_message=str(e)
        )


# =============================================================================
# Export and Reporting Functions
# =============================================================================

def export_to_csv(contracts: List[ContractData], output_path: str) -> None:
    """
    Export contract data to CSV file.

    Args:
        contracts: List of ContractData objects
        output_path: Path to output CSV file
    """
    try:
        if not contracts:
            logging.warning("No contracts to export")
            return

        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'status', 'original_filename', 'new_filename', 'format_version',
                'begin_date', 'end_date', 'place', 'event', 'employer_name',
                'job_title', 'hours', 'salary_brut', 'salary_net',
                'salary_charges', 'guso_to_pay', 'secu', 'error_message'
            ]

            writer = csv.DictWriter(csvfile, fieldnames=fieldnames, extrasaction='ignore')
            writer.writeheader()

            for contract in contracts:
                writer.writerow(contract.to_dict())

        logging.info(f"CSV report saved: {output_path}")

    except Exception as e:
        logging.error(f"Failed to export CSV: {e}")


def print_summary(contracts: List[ContractData]) -> None:
    """
    Print summary statistics to console.

    Args:
        contracts: List of processed contracts
    """
    total_contracts = len(contracts)
    successful = sum(1 for c in contracts if c.status == 'success')
    skipped = sum(1 for c in contracts if c.status == 'skipped')
    errors = sum(1 for c in contracts if c.status == 'error')

    total_hours = sum(c.hours for c in contracts)
    no_shelter_hours = sum(c.hours for c in contracts if 'SHELTER' not in c.place.upper())

    total_salary_brut = sum(c.salary_brut for c in contracts if c.salary_brut > 0)
    total_salary_net = sum(c.salary_net for c in contracts if c.salary_net > 0)
    total_charges = sum(c.salary_charges for c in contracts if c.salary_charges > 0)
    total_guso_to_pay = sum(c.guso_to_pay for c in contracts if c.guso_to_pay > 0)

    # Per-employer breakdown (V2 only — employer_name is empty on V1)
    employers: Dict[str, Dict[str, float]] = {}
    for c in contracts:
        if not c.employer_name:
            continue
        bucket = employers.setdefault(
            c.employer_name,
            {'count': 0, 'hours': 0, 'brut': 0.0, 'net': 0.0, 'guso_to_pay': 0.0},
        )
        bucket['count'] += 1
        bucket['hours'] += c.hours
        bucket['brut'] += c.salary_brut
        bucket['net'] += c.salary_net
        bucket['guso_to_pay'] += c.guso_to_pay

    print("\n" + "=" * 70)
    print("📊 PROCESSING SUMMARY")
    print("=" * 70)
    print(f"Total contracts:          {total_contracts}")
    print(f"  ✓ Successfully processed: {successful}")
    print(f"  ⊘ Skipped (already done): {skipped}")
    print(f"  ✗ Errors:                 {errors}")
    print("-" * 70)
    print(f"Total hours:              {total_hours}H")
    print(f"Total hours (no SHELTER): {no_shelter_hours}H")
    print("-" * 70)
    print(f"Total salary (brut):      {total_salary_brut:.2f}€")
    print(f"Total salary (net):       {total_salary_net:.2f}€")
    print(f"Total charges (brut-net): {total_charges:.2f}€")
    print(f"Total paid to GUSO:       {total_guso_to_pay:.2f}€")

    if employers:
        print("-" * 70)
        print("By employer:")
        for name, b in sorted(employers.items()):
            print(
                f"  - {name:<30} {b['count']:>3} contracts | "
                f"{b['hours']:>4}H | net {b['net']:>9.2f}€ | "
                f"GUSO {b['guso_to_pay']:>9.2f}€"
            )

    print("=" * 70 + "\n")

    if errors > 0:
        print("\n⚠️  Errors occurred:")
        for contract in contracts:
            if contract.status == 'error':
                print(f"  - {contract.original_filename}: {contract.error_message}")
        print()


# =============================================================================
# Main Processing Function
# =============================================================================

def process_contracts(
    year_folder: str,
    dry_run: bool = False,
    backup: bool = False,
    output_csv: Optional[str] = None,
    log_level: str = 'INFO',
    no_cache: bool = False
) -> List[ContractData]:
    """
    Process all contracts in a year folder.

    Args:
        year_folder: Path to the folder containing PDF contracts
        dry_run: If True, preview changes without renaming
        backup: If True, create backups before renaming
        output_csv: Optional path for CSV summary output
        log_level: Logging level
        no_cache: If True, re-process files even if they look already renamed

    Returns:
        List of ContractData objects
    """
    # Validate folder
    if not os.path.isdir(year_folder):
        logging.error(f"The folder '{year_folder}' does not exist.")
        sys.exit(1)

    # List PDF files
    pdf_files = list_pdf_files(year_folder)

    if not pdf_files:
        logging.warning(f"No PDF files found in '{year_folder}'")
        return []

    logging.info(f"Found {len(pdf_files)} PDF files in '{year_folder}'")

    if dry_run:
        print("\n🔍 DRY-RUN MODE: No files will be modified\n")

    if backup:
        print("\n💾 BACKUP MODE: Original files will be backed up\n")

    if no_cache:
        print("\n🔄 NO-CACHE MODE: Already-renamed files will be re-processed\n")

    # Process each contract
    contracts = []
    for pdf_file in pdf_files:
        pdf_path = os.path.join(year_folder, pdf_file)
        contract_data = process_pdf_contract(pdf_path, year_folder, dry_run, backup, no_cache)
        contracts.append(contract_data)

    # Export to CSV if requested
    if output_csv:
        export_to_csv(contracts, output_csv)

    # Print summary
    print_summary(contracts)

    return contracts


# =============================================================================
# CLI Interface
# =============================================================================

def parse_arguments() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description='Process GUSO contracts: extract data, rename files, generate summary',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s 2023                              Process contracts in folder '2023'
  %(prog)s 2023 --dry-run                    Preview changes without modifying files
  %(prog)s 2023 --backup                     Create backups before renaming
  %(prog)s 2023 --output summary.csv         Export results to CSV
  %(prog)s 2023 --backup --output 2023.csv   Backup + CSV export
  %(prog)s 2023 --log-level DEBUG            Enable detailed logging
        """
    )

    parser.add_argument(
        'year_folder',
        help='Path to the folder containing PDF contracts (e.g., "2023"), or path to a single PDF when using --inspect'
    )

    parser.add_argument(
        '--inspect',
        action='store_true',
        help='Dump text blocks + positions for a single PDF (use to find coordinates of new fields)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without actually renaming files'
    )

    parser.add_argument(
        '--backup',
        action='store_true',
        help='Create backup copies of original files before renaming'
    )

    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='Re-process files even if they already look renamed (YYYYMMDD - ... - NH.pdf)'
    )

    parser.add_argument(
        '--output', '-o',
        metavar='CSV_FILE',
        help='Export contract data to CSV file (e.g., "summary.csv")'
    )

    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        default='INFO',
        help='Set logging level (default: INFO)'
    )

    parser.add_argument(
        '--log-file',
        metavar='FILE',
        help='Write logs to file in addition to console'
    )

    return parser.parse_args()


def inspect_pdf(pdf_path: str) -> None:
    """
    Dump every text span of the first page with its bounding box.

    Useful when fixed coordinates no longer match a new form layout: run
    `--inspect file.pdf` and grep for the value (e.g. the hours number) to
    find the (x0, y0, x1, y1) rectangle to add to V2_COORDS.
    """
    if not os.path.isfile(pdf_path):
        logging.error(f"File not found: {pdf_path}")
        sys.exit(1)

    with fitz.open(pdf_path) as doc:
        page = doc[0]
        print(f"\n=== Inspecting {pdf_path} (page 1, size {page.rect}) ===\n")
        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:  # 0 = text
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    x0, y0, x1, y1 = span["bbox"]
                    print(f"  [{x0:7.2f}, {y0:7.2f}, {x1:7.2f}, {y1:7.2f}]  {text!r}")
        print()


def main() -> None:
    """Main entry point."""
    args = parse_arguments()

    # Setup logging
    setup_logging(args.log_level, args.log_file)

    # Inspection mode: dump text + positions and exit
    if args.inspect:
        inspect_pdf(args.year_folder)
        return

    # Process contracts
    try:
        process_contracts(
            year_folder=args.year_folder,
            dry_run=args.dry_run,
            backup=args.backup,
            output_csv=args.output,
            log_level=args.log_level,
            no_cache=args.no_cache
        )
    except KeyboardInterrupt:
        print("\n\n⚠️  Operation cancelled by user")
        sys.exit(130)
    except Exception as e:
        logging.error(f"Unexpected error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
