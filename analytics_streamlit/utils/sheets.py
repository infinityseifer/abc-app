import gspread
import pandas as pd
from google.oauth2.service_account import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def get_ws(sheet_name: str, tab: str, secrets: dict):
    # Copy secrets into a mutable dict
    sa_info = dict(secrets["gcp_service_account"])

    # If the key uses literal "\n", convert to real newlines
    if isinstance(sa_info.get("private_key", ""), str) and "\\n" in sa_info["private_key"]:
        sa_info["private_key"] = sa_info["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(sa_info, scopes=SCOPES)
    gc = gspread.authorize(creds)
    sh = gc.open(sheet_name)
    return sh.worksheet(tab)

def load_table(sheet_name: str, tab: str, secrets: dict) -> pd.DataFrame:
    ws = get_ws(sheet_name, tab, secrets)
    return pd.DataFrame(ws.get_all_records())
