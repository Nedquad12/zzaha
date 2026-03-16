# stock_holdings.py
import os
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, MessageHandler,
    filters, ContextTypes
)
from admin.auth import is_authorized_user, is_vip_user, check_public_group_access
from admin.admin_command import active_admins

FILE_PATH = "/home/ec2-user/database/hold/stockholding.xlsx"

class HoldingsManager:
    def __init__(self):
        self.df = self._load_data()

    def _load_data(self):
        df = pd.read_excel(FILE_PATH, sheet_name='Table 1')
        df = df.iloc[:, [0,1,2,3,4,5,7,8,9,10,11,12]]
        df.columns = [
            'DATE', 'SHARE_CODE', 'ISSUER_NAME', 'INVESTOR_NAME',
            'INVESTOR_TYPE', 'LOCAL_FOREIGN', 'NATIONALITY', 'DOMICILE',
            'HOLDINGS_SCRIPLESS', 'HOLDINGS_SCRIP', 'TOTAL_HOLDING_SHARES', 'PERCENTAGE'
        ]
        for col in ['HOLDINGS_SCRIPLESS', 'HOLDINGS_SCRIP', 'TOTAL_HOLDING_SHARES', 'PERCENTAGE']:
            df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        df['INVESTOR_NAME'] = df['INVESTOR_NAME'].astype(str).str.strip()
        return df.dropna(subset=['SHARE_CODE'])

    def search_by_ticker(self, ticker: str):
        ticker = str(ticker).upper().strip()
        filtered = self.df[self.df['SHARE_CODE'] == ticker].copy()
        if filtered.empty:
            return None
        filtered = filtered.sort_values('PERCENTAGE', ascending=False)
        company = filtered.iloc[0]['ISSUER_NAME']
        img_path = self._generate_combined_image(filtered, ticker, company)
        return img_path

    def search_by_investor(self, name: str):
        name = str(name).strip()
        if not name:
            return []
        
        matched = self.df[self.df['INVESTOR_NAME'].str.contains(name, case=False, na=False)].copy()
        if matched.empty:
            return []
        
        stock_list = []
        for code in matched['SHARE_CODE'].unique():
            stock_df = self.df[self.df['SHARE_CODE'] == code].copy()
            stock_df = stock_df.sort_values('PERCENTAGE', ascending=False)
            
            owner_row = matched[matched['SHARE_CODE'] == code].iloc[0]
            owner_perc = owner_row['PERCENTAGE']
            
            company = stock_df.iloc[0]['ISSUER_NAME']
            
            img_path = self._generate_combined_image(stock_df, code, company)
            
            caption = f"👤 {name} ⭐ ({owner_perc:.2f}%) di {code} - {company}"
            
            stock_list.append((owner_perc, caption, img_path))
        
        stock_list.sort(key=lambda x: x[0], reverse=True)
        return [(cap, img) for _, cap, img in stock_list]

    def _format_text(self, df, title: str, highlight_name=None):
        lines = ["```", title, ""]
        header = "Investor Name                  | Type | L/F | Domicile       | Scripless      | Scrip     | Total Shares    | %"
        lines.append(header)
        lines.append("-" * 110)
        
        for _, row in df.iterrows():
            inv_name = str(row['INVESTOR_NAME'])
            marker = "⭐ " if highlight_name and highlight_name.lower() in inv_name.lower() else "   "
            display_name = (marker + inv_name)[:28].ljust(30)
            
            itype = str(row['INVESTOR_TYPE']).ljust(6)
            lf = str(row.get('LOCAL_FOREIGN') or '').ljust(5)
            dom = str(row.get('DOMICILE') or row.get('NATIONALITY') or '')[:14].ljust(15)
            scripless = f"{int(row['HOLDINGS_SCRIPLESS']):,}".rjust(13)
            scrip = f"{int(row['HOLDINGS_SCRIP']):,}".rjust(10)
            total = f"{int(row['TOTAL_HOLDING_SHARES']):,}".rjust(14)
            perc = f"{row['PERCENTAGE']:.2f}".rjust(5)
            
            line = f"{display_name} | {itype} | {lf} | {dom} | {scripless} | {scrip} | {total} | {perc}"
            lines.append(line)
        lines.append("```")
        return "\n".join(lines)

    def _generate_combined_image(self, df: pd.DataFrame, ticker: str, company_name: str):
        if len(df) == 0:
            return None

        if len(df) > 7:
            top = df.nlargest(7, 'PERCENTAGE')
            sizes = top['PERCENTAGE'].tolist()
            labels = [str(n)[:22] for n in top['INVESTOR_NAME']]
            remainder = 100.0 - sum(sizes)
            if remainder > 0.09:
                labels.append('Lainnya')
                sizes.append(remainder)
        else:
            sizes = df['PERCENTAGE'].tolist()
            labels = [str(n)[:22] for n in df['INVESTOR_NAME']]
            remainder = 100.0 - sum(sizes)
            if remainder > 0.09:
                labels.append('Lainnya')
                sizes.append(remainder)

        legend_labels = [f"{lab} {sz:.2f}%" for lab, sz in zip(labels, sizes)]

        fig = plt.figure(figsize=(21, 13.5))
        gs = fig.add_gridspec(1, 2, width_ratios=[1.45, 0.55], wspace=0.04)

        fig.suptitle(f"KEPEMILIKAN SAHAM UTAMA\n{ticker} ({company_name})", 
                     fontsize=17, fontweight='bold', y=0.96)

        ax_table = fig.add_subplot(gs[0])
        ax_table.axis('off')

        headers = ['Investor Name', 'Type', 'L/F', 'Domicile', 'Scripless', 'Scrip', 'Total Shares', '%']
        table_data = []
        max_rows = 17

        for _, row in df.head(max_rows).iterrows():
            inv_name = str(row['INVESTOR_NAME'])[:34]
            itype = str(row['INVESTOR_TYPE'])[:5]
            lf = str(row.get('LOCAL_FOREIGN', ''))[:4]
            dom = str(row.get('DOMICILE') or row.get('NATIONALITY', ''))[:11]
            scripless = f"{int(row['HOLDINGS_SCRIPLESS']):,}"
            scrip = f"{int(row['HOLDINGS_SCRIP']):,}"
            total = f"{int(row['TOTAL_HOLDING_SHARES']):,}"
            perc = f"{row['PERCENTAGE']:.2f}"

            table_data.append([inv_name, itype, lf, dom, scripless, scrip, total, perc])

        if len(df) > max_rows:
            rem_perc = df.iloc[max_rows:]['PERCENTAGE'].sum()
            if rem_perc > 0.1:
                table_data.append(['Lainnya...', '', '', '', '', '', '', f"{rem_perc:.2f}"])

        full_table = [headers] + table_data
        col_widths = [0.39, 0.06, 0.05, 0.10, 0.11, 0.085, 0.135, 0.07]

        table = ax_table.table(cellText=full_table, colWidths=col_widths,
                               bbox=[0.01, 0.02, 0.98, 0.96],
                               cellLoc='left', edges='closed')

        table.auto_set_font_size(False)
        table.set_fontsize(9.1)
        table.scale(1.02, 1.72)

        for j in range(len(headers)):
            cell = table[0, j]
            cell.set_facecolor('#2C3E50')
            cell.set_text_props(color='white', weight='bold', ha='center')

        ax_pie = fig.add_subplot(gs[1])
        wedges, _ = ax_pie.pie(sizes, startangle=90, counterclock=False)
        centre_circle = plt.Circle((0, 0), 0.68, fc='white')
        ax_pie.add_artist(centre_circle)

        ax_pie.legend(wedges, legend_labels, title="Allocation",
                      loc="center left", bbox_to_anchor=(1.05, 0.5),
                      fontsize=10, title_fontsize=12.5)

        ax_pie.set_title("Allocation", fontsize=14, pad=15)
        ax_pie.axis('equal')

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        img_path = f"/tmp/combined_{ticker}_{ts}.png"
        plt.savefig(img_path, dpi=235, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return img_path


# ================== GLOBAL INSTANCE ==================
holdings = HoldingsManager()


# ================== HANDLERS ==================
async def cmd_sh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # ── Auth guard ──
    if not await check_public_group_access(update, active_admins):
       return
    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke bot ini.")
        return

    keyboard = [
        [InlineKeyboardButton("🔍 Berdasarkan Ticker (SHARE_CODE)", callback_data="mode_ticker")],
        [InlineKeyboardButton("👤 Berdasarkan Nama Pemilik", callback_data="mode_investor")]
    ]
    await update.message.reply_text("🔎 Pilih mode pencarian:", reply_markup=InlineKeyboardMarkup(keyboard))

async def callback_mode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ── Auth guard ──
    uid = query.from_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await query.edit_message_text("⛔ Kamu tidak punya akses ke bot ini.")
        return

    mode = query.data.split("_")[1]
    context.user_data["search_mode"] = mode

    if mode == "ticker":
        await query.edit_message_text("📌 Masukkan Ticker (contoh: AADI, ADRO, VKTR):")
    else:
        await query.edit_message_text("📌 Masukkan Nama Pemilik (contoh: Adaro, Lo Kheng Hong, Sandiaga):")

async def handle_search_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "search_mode" not in context.user_data:
        return

    # ── Auth guard ──
    uid = update.effective_user.id
    if not (is_authorized_user(uid) or is_vip_user(uid)):
        await update.message.reply_text("⛔ Kamu tidak punya akses ke bot ini.")
        context.user_data.pop("search_mode", None)
        return

    mode = context.user_data.pop("search_mode")
    user_input = update.message.text.strip()

    if mode == "ticker":
        img_path = holdings.search_by_ticker(user_input)
        if img_path is None:
            await update.message.reply_text(f"❌ Ticker **{user_input}** tidak ditemukan.")
            return
        with open(img_path, 'rb') as photo:
            await update.message.reply_photo(photo, caption=f"📊 Top Shareholders {user_input}")
        os.remove(img_path)

    else:  # investor
        results = holdings.search_by_investor(user_input)
        if not results:
            await update.message.reply_text(f"❌ Tidak ditemukan pemilik dengan nama **{user_input}**.")
            return
        await update.message.reply_text(f"✅ Ditemukan **{len(results)}** saham untuk **{user_input}**")
        for caption, img_path in results:
            with open(img_path, 'rb') as photo:
                await update.message.reply_photo(photo, caption=caption)
            os.remove(img_path)
