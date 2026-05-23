"""
Non-sponsored (discretionary) report parsing.

Extracts expense summaries and transaction details from non-sponsored
project PDFs (e.g., JHU Non-Sponsored PI Transaction Report).
"""

import re
from decimal import Decimal, InvalidOperation

import pdfplumber


def parse_expense_summary(page):
    """
    Parses the 'Expenditures' summary table from Page 1.

    """
    summary = []
    # Find the table by looking for a known header
    tables = page.extract_tables()

    # Based on , the table we want starts with 'Expenditures'
    expense_table = None
    for table in tables:
        if table and table[0][0] == "Expenditures":
            expense_table = table
            break

    if not expense_table:
        print("Could not find expense summary table on page.")
        return []

    # Get header (row 0) and data rows (row 1+)
    header = expense_table[0]
    data_rows = expense_table[1:]

    # Clean header names for use as keys
    # ['Expenditures', 'Budget', 'January 2025', 'Total Spent', ...]
    clean_header = [h.replace("\n", " ").strip() for h in header]

    for row in data_rows:
        # Stop at the final "Year-to-Date" row, we'll use it for verification
        if row[0] == "Year-to-Date Expenditures":
            continue

        category = row[0]
        if not category:
            continue

        entry = {
            clean_header[0]: category,  # Category
            clean_header[2]: clean_text_to_decimal(row[2]),  # January 2025
            clean_header[3]: clean_text_to_decimal(row[3]),  # Total Spent
            clean_header[5]: clean_text_to_decimal(row[5]),  # Total Spent & Committed
            clean_header[6]: clean_text_to_decimal(row[6]),  # Budget Balance
        }
        summary.append(entry)

    return summary


def parse_expense_transactions(page):
    """
    Parses the detailed 'Non Sponsored PI Transaction Report' from Page 2
    by extracting text and using regular expressions.
    """
    text = page.extract_text()
    transactions = []
    current_category = None

    lines = text.split("\n")
    for line in lines:
        # Update the current category when a category line is found
        if "Other Expenses" in line and "Total" not in line:
            current_category = "Other Expenses"
        elif "Travel Foreign" in line and "Total" not in line:
            current_category = "Travel Foreign"

        # Regex to find lines that end with a date and an amount
        match = re.search(r"(\d{2}/\d{2}/\d{4})\s+([\d,]+\.\d{2})$", line)
        if not match:
            continue

        # Skip total lines
        if line.strip().startswith("Total"):
            continue

        date = match.group(1)
        amount = match.group(2)

        # The string before the date contains description, vendor, and optional ref doc
        pre_date_str = line[: match.start()].strip()

        parts = pre_date_str.split()

        ref_doc = None
        if parts and parts[-1].isdigit() and len(parts[-1]) == 10:
            ref_doc = parts.pop()

        remaining_str = " ".join(parts)

        # Regex to find the vendor (2-3 capitalized words at the end of the string)
        vendor_match = re.search(r"\s((?:[A-Z][A-Z\.]*\s+){1,2}[A-Z][A-Z\.]*)$", remaining_str)

        if vendor_match:
            vendor = vendor_match.group(1).strip()
            description = remaining_str[: vendor_match.start()].strip()
        else:
            vendor = "Unknown"
            description = remaining_str

        # Clean up description from category
        if current_category and description.startswith(current_category):
            description = description[len(current_category) :].strip()

        transactions.append(
            {
                "category": current_category,
                "description": description,
                "vendor": vendor,
                "date": date,
                "amount": clean_text_to_decimal(amount),
                "ref_doc": ref_doc,
            }
        )

    return transactions


def clean_text_to_decimal(text):
    """
    Converts a currency string (e.g., "1,325.88" or "(9,034.52)") to a Decimal.
    Returns None if text is empty.
    """
    if not text or not text.strip():
        return None

    # Remove commas, parentheses (for negative), and whitespace
    cleaned_text = text.strip().replace(",", "").replace("(", "-").replace(")", "")

    if not cleaned_text:
        return None

    try:
        return Decimal(cleaned_text)
    except InvalidOperation:
        print(f"Warning: Could not convert '{text}' to Decimal.")
        return None


def main(pdf_file_path: str = "report.pdf"):
    """
    Main function to open the PDF and run the parsers.
    """
    import pprint as pp

    all_expenses: dict[str, list[dict[str, str | None]]] = {"summary": [], "transactions": []}

    try:
        with pdfplumber.open(pdf_file_path) as pdf:
            # Page 1 (index 0) has the summary
            if len(pdf.pages) > 0:
                page_1 = pdf.pages[0]
                all_expenses["summary"] = parse_expense_summary(page_1)

            # Page 2 (index 1) has the transactions
            if len(pdf.pages) > 1:
                page_2 = pdf.pages[1]
                all_expenses["transactions"] = parse_expense_transactions(page_2)

        print(f"--- Successfully scraped expenses from {pdf_file_path} ---")
        pp.pprint(all_expenses)  # noqa: T203

    except FileNotFoundError:
        print(f"Error: The file '{pdf_file_path}' was not found.")
    except Exception as e:
        print(f"An error occurred: {e}")


if __name__ == "__main__":
    main()
