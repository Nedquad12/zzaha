import pandas as pd
import logging
import os
import json
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

NUMERIC_COLS = [
    'Sebelumnya', 'Open Price', 'First Trade', 'Tertinggi', 'Terendah',
    'Penutupan', 'Selisih', 'Volume', 'Nilai', 'Frekuensi',
    'Index Individual', 'Offer', 'Offer Volume', 'Bid', 'Bid Volume',
    'Listed Shares', 'Tradeble Shares', 'Weight For Index',
    'Foreign Sell', 'Foreign Buy', 'Non Regular Volume',
    'Non Regular Value', 'Non Regular Frequency',
]


def get_file_date_from_name(filename):
    """Extract date from filename format ddmmyy.xlsx"""
    try:
        date_str = filename.replace('.xlsx', '').replace('.xls', '')
        if len(date_str) == 6:
            day   = int(date_str[:2])
            month = int(date_str[2:4])
            year  = 2000 + int(date_str[4:6])
            return datetime(year, month, day)
    except ValueError as e:
        logger.warning(f"Cannot parse date from filename {filename}: {e}")
    return None


def get_excel_files(directory):
    """Return all excel files in directory sorted by date (newest first)."""
    files = []
    for filename in os.listdir(directory):
        if filename.endswith(('.xlsx', '.xls')):
            file_date = get_file_date_from_name(filename)
            if file_date:
                files.append({
                    'filename': filename,
                    'date': file_date,
                    'path': os.path.join(directory, filename),
                })
    files.sort(key=lambda x: x['date'], reverse=True)
    return files


def read_excel_data(file_path):
    """Read xlsx and return cleaned DataFrame using actual header row."""
    try:
        df = pd.read_excel(file_path, header=0)
        logger.info(f"File {file_path}: {df.shape[0]} rows, {df.shape[1]} cols")

        if 'Kode Saham' not in df.columns:
            logger.error(f"Kolom 'Kode Saham' tidak ditemukan di {file_path}")
            return None

        df = df.dropna(subset=['Kode Saham'])
        df['Kode Saham'] = df['Kode Saham'].astype(str).str.strip().str.upper()

        for col in NUMERIC_COLS:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

        if 'Foreign Buy' in df.columns and 'Foreign Sell' in df.columns:
            df['Foreign Net'] = df['Foreign Buy'] - df['Foreign Sell']
        else:
            df['Foreign Net'] = 0

        logger.info(f"Berhasil baca {len(df)} baris dari {file_path}")
        return df

    except Exception as e:
        logger.error(f"Error membaca {file_path}: {e}")
        return None


def get_stock_sector_data(stock_code, sector_directory="/home/ec2-user/database/namesektor"):
    """Return sector info dict for a given stock code, or (None, error_msg)."""
    if not os.path.exists(sector_directory):
        return None, "Direktori sektor tidak ditemukan"

    sector_files = [f for f in os.listdir(sector_directory) if f.endswith(('.xlsx', '.xls'))]
    if not sector_files:
        return None, "Tidak ada file sektor ditemukan"

    for sector_file in sector_files:
        sector_name = sector_file.replace('.xlsx', '').replace('.xls', '')
        file_path   = os.path.join(sector_directory, sector_file)
        try:
            df = pd.read_excel(file_path, header=None)
            if df.shape[1] < 6:
                continue

            sector_df = pd.DataFrame({
                'kode':               df.iloc[:, 1],
                'tanggal_pencatatan': df.iloc[:, 3],
                'papan_pencatatan':   df.iloc[:, 5],
            }).dropna(subset=['kode'])

            sector_df['kode'] = sector_df['kode'].astype(str).str.strip().str.upper()
            match = sector_df[sector_df['kode'] == stock_code.upper()]

            if not match.empty:
                row = match.iloc[0]
                return {
                    'stock_code':         stock_code,
                    'sector':             sector_name,
                    'tanggal_pencatatan': row['tanggal_pencatatan'],
                    'papan_pencatatan':   row['papan_pencatatan'],
                }, None

        except Exception as e:
            logger.warning(f"Error reading sector file {sector_file}: {e}")
            continue

    return None, f"Saham {stock_code} tidak ditemukan di data sektor"


def excel_to_json(file_info, output_dir):
    """
    Convert a single xlsx file to a JSON file.
    Returns the output JSON path on success, None on failure.
    """
    df = read_excel_data(file_info['path'])
    if df is None:
        return None

    date_str   = file_info['date'].strftime('%d%m%y')
    json_path  = os.path.join(output_dir, f"{date_str}.json")

    records = df.to_dict(orient='records')

    # Make datetime / Timestamp objects JSON-serialisable
    def default_serialiser(obj):
        if isinstance(obj, (datetime, pd.Timestamp)):
            return obj.isoformat()
        raise TypeError(f"Type {type(obj)} not serialisable")

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False, indent=2, default=default_serialiser)

    logger.info(f"Saved {len(records)} records → {json_path}")
    return json_path
