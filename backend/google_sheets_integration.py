import os
import json
import gspread
from google.oauth2.service_account import Credentials
from datetime import date


def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    if os.getenv("GOOGLE_CREDENTIALS"):
        creds_dict = json.loads(os.getenv("GOOGLE_CREDENTIALS"))
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)

    client = gspread.authorize(creds)
    return client.open("Stock Trajectory").sheet1


def update_spreadsheet(results):
    sheet = get_sheet()
    today = date.today().strftime("%d-%m-%Y")

    all_values = sheet.get_all_values()

    # First run — initialize the sheet structure
    if not all_values or all_values[0] == []:
        print("Initializing sheet structure...")
        initial_headers = [
            "Stock",
            "Stock Name",
            f"SS_{today}",
            f"M_{today}",
            f"FS_{today}",
            f"Price_{today}",
        ]
        sheet.append_row(initial_headers)

        for result in results:
            row = [
                result["ticker"],
                result.get("company_name", ""),
                round(result["avg_sentiment"], 3),
                result["mentions"],
                round(result["final_score"], 3),
                result.get("price", 0),
            ]
            sheet.append_row(row)

        print(f"Sheet initialized with {len(results)} stocks for {today}")
        return

    header_row = all_values[0]

    # Check if today already exists
    if f"SS_{today}" in header_row:
        print(f"Data for {today} already exists, skipping...")
        return

    # Find where each metric group starts
    # Structure: Stock | Name | SS_d1 | SS_d2 | M_d1 | M_d2 | FS_d1 | FS_d2 | Price_d1 | Price_d2

    # Find insertion points for each group
    ss_cols = [i for i, h in enumerate(header_row) if h.startswith("SS_")]
    m_cols = [i for i, h in enumerate(header_row) if h.startswith("M_")]
    fs_cols = [i for i, h in enumerate(header_row) if h.startswith("FS_")]
    price_cols = [i for i, h in enumerate(header_row) if h.startswith("Price_")]

    # New column positions (0-indexed, convert to 1-indexed for gspread)
    new_ss_col = max(ss_cols) + 2  # after last SS column
    new_m_col = max(m_cols) + 3  # after last M column (shifted by 1 new SS)
    new_fs_col = max(fs_cols) + 4  # after last FS column (shifted by 2 new cols)
    new_price_col = (
        max(price_cols) + 5
    )  # after last Price column (shifted by 3 new cols)

    # Insert new header columns at correct positions
    # We need to shift existing columns right to make room
    # Easiest approach — rebuild entire header and all rows

    new_header = []
    new_all_rows = [[] for _ in range(len(all_values))]

    for col_idx, header in enumerate(header_row):
        # Add existing column to all rows
        for row_idx, row in enumerate(all_values):
            value = row[col_idx] if col_idx < len(row) else ""
            new_all_rows[row_idx].append(value)

        # After last SS column — insert new SS column
        if header.startswith("SS_") and (col_idx == max(ss_cols)):
            new_all_rows[0].append(f"SS_{today}")
            for row_idx in range(1, len(all_values)):
                new_all_rows[row_idx].append("")  # empty for now

        # After last M column — insert new M column
        elif header.startswith("M_") and (col_idx == max(m_cols)):
            new_all_rows[0].append(f"M_{today}")
            for row_idx in range(1, len(all_values)):
                new_all_rows[row_idx].append("")

        # After last FS column — insert new FS column
        elif header.startswith("FS_") and (col_idx == max(fs_cols)):
            new_all_rows[0].append(f"FS_{today}")
            for row_idx in range(1, len(all_values)):
                new_all_rows[row_idx].append("")

        # After last Price column — insert new Price column
        elif header.startswith("Price_") and (col_idx == max(price_cols)):
            new_all_rows[0].append(f"Price_{today}")
            for row_idx in range(1, len(all_values)):
                new_all_rows[row_idx].append("")

    # Build ticker → row index map from new structure
    new_header = new_all_rows[0]
    existing_tickers = {}
    for i, row in enumerate(new_all_rows[1:], start=1):
        if row and row[0]:
            existing_tickers[row[0]] = i

    # Fill in today's values for each result
    new_ss_col_idx = new_header.index(f"SS_{today}")
    new_m_col_idx = new_header.index(f"M_{today}")
    new_fs_col_idx = new_header.index(f"FS_{today}")
    new_price_col_idx = new_header.index(f"Price_{today}")

    for result in results:
        ticker = result["ticker"]

        if ticker in existing_tickers:
            row_idx = existing_tickers[ticker]
            new_all_rows[row_idx][new_ss_col_idx] = round(result["avg_sentiment"], 3)
            new_all_rows[row_idx][new_m_col_idx] = result["mentions"]
            new_all_rows[row_idx][new_fs_col_idx] = round(result["final_score"], 3)
            new_all_rows[row_idx][new_price_col_idx] = result.get("price", 0)
        else:
            # New ticker — create new row with empty values
            new_row = [""] * len(new_header)
            new_row[0] = ticker
            new_row[1] = result.get("company_name", "")
            new_row[new_ss_col_idx] = round(result["avg_sentiment"], 3)
            new_row[new_m_col_idx] = result["mentions"]
            new_row[new_fs_col_idx] = round(result["final_score"], 3)
            new_row[new_price_col_idx] = result.get("price", 0)
            new_all_rows.append(new_row)

    # Write everything back to sheet in one batch call
    # (much faster than individual cell updates)
    sheet.clear()
    sheet.update("A1", new_all_rows)

    print(f"Spreadsheet updated for {today}")
    print(f"Structure: SS | M | FS | Price columns added for {today}")
