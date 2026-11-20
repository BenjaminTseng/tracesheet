"""Seeds two realistic California multi-PDF client matters for immediate testing."""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import List

import pymupdf

from app.compilers.bankruptcy.service import BankruptcyCaseService


def _write_client_pdf(path: Path, lines: List[str]) -> None:
    """Generates a clean digital client PDF with real coordinates via PyMuPDF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    y = 64
    for ln in lines:
        page.insert_text((56, y), ln, fontsize=10.5, fontname="helv")
        y += 17
    doc.save(str(path))
    doc.close()


def seed_bankruptcy_sample_cases(service: BankruptcyCaseService) -> None:
    """Seeds `bk_ch7_cacb_martinez` and `bk_ch13_caeb_chen` if not already initialized."""
    # -----------------------------------------------------------------
    # Case 1: Los Angeles Chapter 7 (CACB) — Active Contradictions & Emerging Questions
    # -----------------------------------------------------------------
    m1 = "bk_ch7_cacb_martinez"
    if not (service.matters_root / m1 / "bankruptcy_case.json").exists():
        m1_raw = service.ingestor.create_matter(m1) / "inputs" / "raw"
        _write_client_pdf(
            m1_raw / "01_intake_martinez.pdf",
            [
                "Debtor Profile & Intake Summary",
                "Debtor Name: Elena Martinez",
                "SSN: 442-81-9012",
                "Street Address: 410 Wilshire Blvd Apt 4B",
                "City/State/Zip: Los Angeles, CA 90010",
                "County of Residence: Los Angeles",
                "Household Size: 1",
                "CA Domicile Days: 2400",
            ],
        )
        for m in range(5, 11):
            pay_day = f"2026-{m:02d}-28"
            ytd = 5200 * m
            _write_client_pdf(
                m1_raw / f"02_paystub_{m:02d}_2026.pdf",
                [
                    "ADP Earnings Statement",
                    "Employer: Metro Logistics Inc.",
                    f"Pay Date: {pay_day}",
                    "Gross Pay: $5,200.00",
                    "Net Pay: $3,900.00",
                    "Tax Withheld: $1,050.00",
                    f"YTD Gross: ${ytd:,.2f}",
                    "Direct Deposit Account No: 998877664829",
                ],
            )
        _write_client_pdf(
            m1_raw / "03_chase_stmt_oct_2026.pdf",
            [
                "Chase Checking Bank Statement",
                "Institution: Chase Bank",
                "Account No: 998877664829",
                "Period Start: 2026-10-01",
                "Period End: 2026-10-31",
                "Beginning Balance: $1,900.00",
                "Ending Balance: $2,450.00",
                "Total Deposits: $5,700.00",
                "Payroll Deposits: $3,900.00",
                "TX 2026-10-12 DEBIT $340.00 SYNCHRONY BANK ACH PAYMENT",
                "TX 2026-10-19 CREDIT $1,800.00 ZELLE TRANSFER FROM R. GOMEZ",
            ],
        )
        _write_client_pdf(
            m1_raw / "04_toyota_auto_loan.pdf",
            [
                "Auto Finance Loan Statement",
                "Lender: Toyota Financial Services",
                "Creditor Address: PO Box 5855, Carol Stream, IL 60197",
                "Principal Balance: $14,200.00",
                "Monthly Payment: $410.00",
            ],
        )
        _write_client_pdf(
            m1_raw / "05_chase_card.pdf",
            [
                "Credit Card Statement",
                "Creditor: Chase Card Services",
                "Creditor Address: PO Box 15298, Wilmington, DE 19850",
                "Balance Due: $11,800.00",
            ],
        )
        _write_client_pdf(
            m1_raw / "06_form_1040_2025.pdf",
            [
                "Form 1040 Individual Income Tax Return",
                "Tax Year: 2025",
                "Filing Status: single",
                "Dependents: 0",
                "Adjusted Gross Income: $62,400.00",
                "Total Tax: $7,480.00",
                "Refund Due: $850.00",
                "Schedule B Institutions: Chase Bank",
            ],
        )
        _write_client_pdf(
            m1_raw / "07_budget_schedule_ij.pdf",
            [
                "Monthly Budget Worksheet (Schedule I/J)",
                "Monthly Gross Income: $5,200.00",
                "Rent/Mortgage: $2,200.00",
                "Utilities: $260.00",
                "Food/Housekeeping: $520.00",
                "Auto Fuel/Insurance: $180.00",
                "Clothing/Personal: $110.00",
                "Budget Dependents: 0",
            ],
        )
        service.extract_matter(
            m1,
            chapter="7",
            district="CACB",
            expected_filing_date=datetime.date(2026, 11, 16),
        )

    # -----------------------------------------------------------------
    # Case 2: Sacramento Chapter 13 (CAEB) — Clean Homeowner + Business Guaranty
    # -----------------------------------------------------------------
    m2 = "bk_ch13_caeb_chen"
    if not (service.matters_root / m2 / "bankruptcy_case.json").exists():
        m2_raw = service.ingestor.create_matter(m2) / "inputs" / "raw"
        _write_client_pdf(
            m2_raw / "01_intake_chen.pdf",
            [
                "Debtor Profile & Intake Summary",
                "Debtor Name: Marcus Chen",
                "SSN: 718-33-5509",
                "Street Address: 882 Oak Meadow Ln",
                "City/State/Zip: Sacramento, CA 95814",
                "County of Residence: Sacramento",
                "Household Size: 2",
                "CA Domicile Days: 3100",
            ],
        )
        for m in range(5, 11):
            _write_client_pdf(
                m2_raw / f"02_paystub_{m:02d}_2026.pdf",
                [
                    "Paystub Earnings Statement",
                    "Employer: Sierra Civil Engineering",
                    f"Pay Date: 2026-{m:02d}-28",
                    "Gross Pay: $9,100.00",
                    "Net Pay: $6,650.00",
                    "Tax Withheld: $2,050.00",
                    f"YTD Gross: ${9100 * m:,.2f}",
                    "Direct Deposit Account No: 551122337744",
                ],
            )
        _write_client_pdf(
            m2_raw / "03_home_appraisal.pdf",
            [
                "Residential Property Appraisal & Asset Schedule",
                "Asset ID: home_sac_1",
                "Category: real_property",
                "Description: 882 Oak Meadow Ln, Sacramento, CA 95814",
                "Fair Market Value: $540,000.00",
                "Acquisition Date: 2018-06-15",
            ],
        )
        _write_client_pdf(
            m2_raw / "04_mortgage_caliber.pdf",
            [
                "Mortgage Statement",
                "Lender: Caliber Home Loans",
                "Creditor Address: PO Box 24610, Oklahoma City, OK 73124",
                "Principal Balance: $210,000.00",
                "Monthly Payment: $1,850.00",
                "Arrears Due: $18,000.00",
                "Collateral Ref: home_sac_1",
            ],
        )
        _write_client_pdf(
            m2_raw / "05_sba_guaranty.pdf",
            [
                "Unsecured Claim Notice",
                "Creditor: U.S. Small Business Administration",
                "Creditor Address: 2 North 20th St, Birmingham, AL 35203",
                "Balance Due: $420,000.00",
                "Business Debt Pct: 1.0",
            ],
        )
        _write_client_pdf(
            m2_raw / "06_bofa_checking.pdf",
            [
                "Bank of America Bank Statement",
                "Institution: Bank of America",
                "Account No: 551122337744",
                "Period Start: 2026-10-01",
                "Period End: 2026-10-31",
                "Beginning Balance: $1,800.00",
                "Ending Balance: $1,950.00",
                "Total Deposits: $6,650.00",
                "Payroll Deposits: $6,650.00",
            ],
        )
        _write_client_pdf(
            m2_raw / "07_form_1040_2025.pdf",
            [
                "Form 1040 Individual Income Tax Return",
                "Tax Year: 2025",
                "Filing Status: single",
                "Dependents: 1",
                "Adjusted Gross Income: $109,200.00",
                "Total Tax: $19,800.00",
                "Schedule B Institutions: Bank of America",
            ],
        )
        _write_client_pdf(
            m2_raw / "08_budget_schedule_ij.pdf",
            [
                "Monthly Budget Worksheet (Schedule I/J)",
                "Monthly Gross Income: $9,100.00",
                "Utilities: $380.00",
                "Food/Housekeeping: $780.00",
                "Clothing/Personal: $150.00",
                "Budget Dependents: 1",
            ],
        )
        service.extract_matter(
            m2,
            chapter="13",
            district="CAEB",
            expected_filing_date=datetime.date(2026, 11, 16),
        )
