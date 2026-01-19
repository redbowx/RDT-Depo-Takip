import sys
import os
import traceback
import multiprocessing
from pathlib import Path

# --- ERKEN LOGLAMA ---
def log_debug(msg):
    # Loglama devre dışı bırakıldı
    pass

log_debug("--- PROGRAM BASLIYOR (OPTIMIZED v3) ---")

# --- TURKCE KARAKTER YARDIMCISI ---
def tr_lower(text):
    if text is None: return ""
    return str(text).replace("I", "ı").replace("İ", "i").lower()

def tr_sort(text):
    if not isinstance(text, str): return text
    mapping = str.maketrans("çğıiöşüÇĞİIÖŞÜ", "cgilosuCGIIOSU")
    return text.translate(mapping).lower()

# Kritik Kutuphaneler (Hızlı Import)
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import customtkinter as ctk
from datetime import datetime
import shutil
import sqlite3
import itertools
import importlib.util
import os

# Resim kütüphaneleri sadece ihtiyaç olduğunda yüklenecek şekilde global tanımlandı
Image = None
ImageTk = None
DateEntry = None

try:
    from PIL import Image, ImageTk
except: pass

try:
    from tkcalendar import DateEntry
except: pass

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


# --- AYARLAR ---
APP_NAME_DEFAULT = "RDT PRO"
FOLDER_NAME = "RDT_Pro_Data"
DB_NAME = "rdt_pro.db"

if getattr(sys, 'frozen', False):
    # Exe ise exe'nin oldugu klasor
    BASE_DIR = Path(sys.executable).parent
    ROOT_DIR = BASE_DIR / FOLDER_NAME
else:
    # Script ise dosyanin oldugu klasor
    BASE_DIR = Path(__file__).parent
    ROOT_DIR = BASE_DIR / FOLDER_NAME

DB_PATH = ROOT_DIR / DB_NAME
REPORT_DIR = ROOT_DIR / "Raporlar"

# --- VERİTABANI ---
class DatabaseManager:
    def __init__(self):
        self.init_db()

    def get_conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.create_function("TR_LOWER", 1, tr_lower)
        return conn

    def init_db(self):
        try:
            for p in [ROOT_DIR, REPORT_DIR, ROOT_DIR / "Urun_Resimleri"]:
                p.mkdir(parents=True, exist_ok=True)
        except: pass

        with self.get_conn() as conn:
            c = conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS materials (id INTEGER PRIMARY KEY, name TEXT, stock REAL, unit TEXT, track_critical INTEGER DEFAULT 1)")
            try: c.execute("SELECT image_path FROM materials LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE materials ADD COLUMN image_path TEXT")
                except: pass

            c.execute("CREATE TABLE IF NOT EXISTS teams (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS transactions (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, type TEXT, material_id INTEGER, receiver TEXT, quantity REAL, description TEXT)")
            
            try: c.execute("SELECT receiver FROM transactions LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE transactions ADD COLUMN receiver TEXT")
                except: pass

            try: c.execute("SELECT is_unlimited FROM materials LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE materials ADD COLUMN is_unlimited INTEGER DEFAULT 0")
                except: pass

            try: c.execute("SELECT unit_price FROM transactions LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE transactions ADD COLUMN unit_price REAL DEFAULT 0")
                except: pass

            try: c.execute("SELECT status FROM transactions LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE transactions ADD COLUMN status TEXT DEFAULT 'APPROVED'")
                except: pass

            try: c.execute("SELECT average_cost FROM materials LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE materials ADD COLUMN average_cost REAL DEFAULT 0")
                except: pass

            # MODUL: SKT TAKIP
            try: c.execute("SELECT track_expiry FROM materials LIMIT 1")
            except:
                try: c.execute("ALTER TABLE materials ADD COLUMN track_expiry INTEGER DEFAULT 0")
                except: pass
            
            try: c.execute("SELECT expiry_date FROM transactions LIMIT 1")
            except:
                try: c.execute("ALTER TABLE transactions ADD COLUMN expiry_date TEXT")
                except: pass

            c.execute("CREATE TABLE IF NOT EXISTS suppliers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, phone TEXT, info TEXT, email TEXT)")
            
            try: c.execute("SELECT email FROM suppliers LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE suppliers ADD COLUMN email TEXT")
                except: pass

            try: c.execute("SELECT rating FROM suppliers LIMIT 1")
            except: 
                try: c.execute("ALTER TABLE suppliers ADD COLUMN rating INTEGER DEFAULT 0")
                except: pass

            c.execute("CREATE TABLE IF NOT EXISTS undo_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, timestamp TEXT)")

            c.execute("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS stock_units (name TEXT PRIMARY KEY)")
            for u in ['Adet', 'Kg', 'Koli', 'Paket', 'Metre', 'Litre']:
                c.execute("INSERT OR IGNORE INTO stock_units (name) VALUES (?)", (u,))
                
            c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (APP_NAME_DEFAULT, APP_NAME_DEFAULT))
            c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", ('sort_col', 'Malzeme Adı'))
            c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", ('sort_reverse', '0'))
            c.execute("INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", ('expiry_warning_days', '30'))
            
            # --- PERFORMANS ICIN INDEXLER ---
            c.execute("CREATE INDEX IF NOT EXISTS idx_mat_name ON materials(name)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(date)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_trans_type ON transactions(type)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_trans_mat_id ON transactions(material_id)")
            
            # --- MODUL: DEPO LOKASYON YONETIMI ---
            # 1. Ayarlar (Hangi seviyeler aktif?)
            c.execute("CREATE TABLE IF NOT EXISTS location_settings (level_type TEXT PRIMARY KEY, is_active INTEGER)")
            # Varsayilan: Sadece RAF ve BOLUM aktif olsun
            c.execute("INSERT OR IGNORE INTO location_settings (level_type, is_active) VALUES ('KAT', 0)")
            c.execute("INSERT OR IGNORE INTO location_settings (level_type, is_active) VALUES ('BOLGE', 0)")
            c.execute("INSERT OR IGNORE INTO location_settings (level_type, is_active) VALUES ('RAF', 1)")
            c.execute("INSERT OR IGNORE INTO location_settings (level_type, is_active) VALUES ('BOLUM', 1)") # Bolum her zaman zorunludur

            # 2. Hiyerarsi Agaci (Kat 1, A Blogu, Raf 5...)
            c.execute("""CREATE TABLE IF NOT EXISTS location_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_id INTEGER,
                level_type TEXT,
                name TEXT,
                active INTEGER DEFAULT 1
            )""")

            # 3. Fiziksel Lokasyonlar (Son Nokta / Goz)
            c.execute("""CREATE TABLE IF NOT EXISTS locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id INTEGER,
                capacity REAL DEFAULT 0,
                current_load REAL DEFAULT 0,
                active INTEGER DEFAULT 1
            )""")

            # 4. Urun-Lokasyon Iliskisi (Stok Dagilimi)
            c.execute("""CREATE TABLE IF NOT EXISTS product_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                location_id INTEGER,
                quantity REAL,
                entry_date TEXT
            )""")
            
            c.execute("CREATE INDEX IF NOT EXISTS idx_prod_loc_pid ON product_locations(product_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_prod_loc_lid ON product_locations(location_id)")

            conn.commit()

    def get_setting(self, key):
        with self.get_conn() as conn:
            res = conn.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
            return res[0] if res else ""

    def update_setting(self, key, value):
        with self.get_conn() as conn:
            conn.execute("INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)", (key, str(value)))
            conn.commit()

    def reindex_materials(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            mats = c.execute("SELECT name, stock, unit, track_critical, id, average_cost FROM materials ORDER BY id").fetchall()
            c.execute("DELETE FROM materials"); c.execute("DELETE FROM sqlite_sequence WHERE name='materials'")
            id_map = {}
            for i, m in enumerate(mats, 1):
                # m[5] is average_cost
                c.execute("INSERT INTO materials (id, name, stock, unit, track_critical, average_cost) VALUES (?,?,?,?,?,?)", (i, m[0], m[1], m[2], m[3], m[5]))
                id_map[m[4]] = i
            for old_id, new_id in id_map.items():
                c.execute("UPDATE transactions SET material_id = ? WHERE material_id = ?", (new_id, old_id))
            conn.commit()

    def reindex_suppliers(self):
        with self.get_conn() as conn:
            c = conn.cursor()
            rows = c.execute("SELECT name, phone, info, email, id FROM suppliers ORDER BY id").fetchall()
            c.execute("DELETE FROM suppliers"); c.execute("DELETE FROM sqlite_sequence WHERE name='suppliers'")
            for i, r in enumerate(rows, 1):
                # r[3] is email
                c.execute("INSERT INTO suppliers (id, name, phone, info, email) VALUES (?,?,?,?,?)", (i, r[0], r[1], r[2], r[3]))
            conn.commit()

# --- PDF OLUŞTURUCU ---
class PDFGenerator:
    @staticmethod
    def create_custody_report(receiver, team_name, items, date_str):
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfbase import pdfmetrics
            from reportlab.pdfbase.ttfonts import TTFont
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
            from reportlab.lib import colors
            from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

            def get_font():
                try:
                    font_path = os.path.join(os.environ['WINDIR'], 'Fonts', 'arial.ttf')
                    if os.path.exists(font_path):
                        pdfmetrics.registerFont(TTFont('Arial', font_path))
                        return 'Arial'
                except: pass
                return 'Helvetica'
            
            pdf_font = get_font()
            filename = f"Tutanak_{date_str.replace('.', '')}_{receiver.replace(' ', '_')}.pdf"
            path = REPORT_DIR / filename
            
            doc = SimpleDocTemplate(str(path), pagesize=A4)
            styles = getSampleStyleSheet()
            
            style_title = ParagraphStyle('TitleTR', parent=styles['Heading1'], fontName=pdf_font, alignment=1, fontSize=16, spaceAfter=20)
            style_body = ParagraphStyle('BodyTR', parent=styles['Normal'], fontName=pdf_font, fontSize=11, leading=14, spaceAfter=10)
            style_date = ParagraphStyle('DateTR', parent=styles['Normal'], fontName=pdf_font, alignment=2, fontSize=11)

            elements = []
            elements.append(Paragraph(date_str, style_date))
            elements.append(Spacer(1, 10))
            elements.append(Paragraph("MALZEME TESLİM TUTANAĞI", style_title))
            elements.append(Spacer(1, 20))
            
            if team_name and team_name != "Personel":
                hitap = f"Sayın {receiver} / {team_name}'ne;"
            else:
                hitap = f"Sayın {receiver};"
                
            elements.append(Paragraph(hitap, style_body))
            elements.append(Paragraph("<b>KONU:</b> Malzeme Teslimi Hk.", style_body))
            elements.append(Spacer(1, 10))
            
            text = f"Aşağıda cinsi ve miktarı belirtilen malzemeler, tam ve eksiksiz olarak Fen İşleri Müdürlüğü deposundan, {receiver} tarafına teslim edilmiştir."
            elements.append(Paragraph(text, style_body))
            elements.append(Spacer(1, 20))
            
            table_data = [["Malzeme Adı", "Miktar", "Birim"]]
            for item in items:
                table_data.append([item[0], str(item[1]), item[2]])
                
            t = Table(table_data, colWidths=[300, 80, 80])
            t.setStyle(TableStyle([
                ('FONTNAME', (0,0), (-1,-1), pdf_font),
                ('BACKGROUND', (0,0), (-1,0), colors.lightgrey),
                ('TEXTCOLOR', (0,0), (-1,0), colors.black),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('ALIGN', (0,1), (0,-1), 'LEFT'),
                ('GRID', (0,0), (-1,-1), 1, colors.black),
                ('BOX', (0,0), (-1,-1), 1, colors.black),
                ('PADDING', (0,0), (-1,-1), 6),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 30))
            
            elements.append(Paragraph("İşbu tutanak, malzemelerin eksiksiz teslim edildiğini belgelemek amacıyla düzenlenmiştir.", style_body))
            elements.append(Spacer(1, 50))
            
            sig_data = [
                ["TESLİM ALAN", "TESLİM EDEN"],
                [receiver, "Ünal BAŞARAN"],
                ["(İmza)", "(İmza)"]
            ]
            sig_table = Table(sig_data, colWidths=[200, 200])
            sig_table.setStyle(TableStyle([
                ('FONTNAME', (0,0), (-1,-1), pdf_font),
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('FONTSIZE', (0,0), (-1,0), 11),
                ('FONTSIZE', (0,1), (-1,1), 11),
                ('TOPPADDING', (0,2), (-1,2), 30),
            ]))
            elements.append(sig_table)
            
            doc.build(elements)
            return str(path)
        except Exception as e:
            raise Exception(f"PDF Hatası: {e}")

# --- OZEL DIYALOGLAR (BIR DAHA GOSTERME) ---
def ask_yesno_optout(parent, title, message, setting_key, db):
    # Eger ayar zaten "1" ise direkt True don
    if db.get_setting(setting_key) == "1":
        return True

    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.geometry("350x220")
    dialog.attributes("-topmost", True)
    
    # Pencereyi merkeze al
    parent_x = parent.winfo_x()
    parent_y = parent.winfo_y()
    parent_w = parent.winfo_width()
    parent_h = parent.winfo_height()
    dialog.geometry(f"+{parent_x + (parent_w//2) - 175}+{parent_y + (parent_h//2) - 110}")

    ctk.CTkLabel(dialog, text=message, wraplength=300, font=("Segoe UI", 13)).pack(pady=20, padx=20)
    
    var_dont_ask = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(dialog, text="Bir daha sorma (Otomatik Evet)", variable=var_dont_ask).pack(pady=10)

    result = {"val": False}

    def on_yes():
        result["val"] = True
        if var_dont_ask.get():
            db.update_setting(setting_key, "1")
        dialog.destroy()

    def on_no():
        result["val"] = False
        dialog.destroy()

    btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
    btn_frame.pack(pady=10)
    ctk.CTkButton(btn_frame, text="EVET", command=on_yes, width=80, fg_color="#27ae60").pack(side="left", padx=10)
    ctk.CTkButton(btn_frame, text="HAYIR", command=on_no, width=80, fg_color="#c0392b").pack(side="left", padx=10)

    dialog.transient(parent)
    dialog.grab_set()
    parent.wait_window(dialog)
    return result["val"]

def show_info_optout(parent, title, message, setting_key, db):
    if db.get_setting(setting_key) == "1": return

    dialog = ctk.CTkToplevel(parent)
    dialog.title(title)
    dialog.geometry("350x200")
    dialog.attributes("-topmost", True)
    
    parent_x = parent.winfo_x(); parent_y = parent.winfo_y()
    dialog.geometry(f"+{parent_x + 100}+{parent_y + 100}")

    ctk.CTkLabel(dialog, text=message, wraplength=300).pack(pady=20, padx=20)
    var_dont_show = ctk.BooleanVar(value=False)
    ctk.CTkCheckBox(dialog, text="Bir daha gösterme", variable=var_dont_show).pack(pady=5)

    def on_ok():
        if var_dont_show.get(): db.update_setting(setting_key, "1")
        dialog.destroy()

    ctk.CTkButton(dialog, text="TAMAM", command=on_ok, width=100).pack(pady=15)
    dialog.transient(parent); dialog.grab_set(); parent.wait_window(dialog)

# --- ARAYÜZ ---
class FIDTApp(ctk.CTk if ctk else tk.Tk):
    def __init__(self):
        super().__init__()
        try:
            # Windows'ta görev çubuğu ikonunun doğru görünmesi için ID tanımla
            if os.name == 'nt':
                import ctypes
                myappid = 'rdtsoft.rdtpro.v1'
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
        except: pass

        try:
            self.db = DatabaseManager()
            self.undo_stack = [] 
            if ctk: ctk.set_appearance_mode("Dark")
            
            style = ttk.Style()
            try: style.theme_use("clam")
            except: pass
            
            # Pencere Başlığı
            self.title("RDT Pro")
            
            # İkon Ayarla (logo.ico)
            try:
                icon_path = BASE_DIR / "logo.ico"
                if icon_path.exists():
                    self.iconbitmap(str(icon_path))
            except: pass
                
            # Ekrani ortala (Dikeyde biraz yukarida)
            w, h = 1700, 980
            sw = self.winfo_screenwidth()
            sh = self.winfo_screenheight()
            x = (sw - w) // 2
            y = ((sh - h) // 2) - 60 # Biraz daha yukari
            if y < 0: y = 0
            self.geometry(f"{w}x{h}+{x}+{y}")
            self.minsize(1300, 900)
            
            self.grid_columnconfigure(1, weight=1); self.grid_rowconfigure(0, weight=1)
            
            self.anim_colors = self.gen_gradient()
            self.color_cycle = itertools.cycle(self.anim_colors)
            self.current_tree = None
            self.nav_buttons = {}
            self.current_page_key = "dashboard"
            self.undone_log = [] # Geri alinan islemlerin kaydi
            self.redo_stack = [] # Yinele islemleri
            self.loaded_modules = {} # Yuklenen (aktif) moduller
            self.available_modules = [] # Bulunan tum modul dosyalari (yonetim icin)
            self.search_job = None # Arama optimizasyonu icin zamanlayici
            self.nav_buttons = {} # Buton referanslari
            self.cached_fig = None # Dashboard grafigi onbellek
            
            # MENU TANIMLARI (Key, Title, Icon/Emoji)
            self.menu_definitions = [
                ("dashboard", "📊  DASHBOARD"),
                ("stock", "📦  Stok Listesi"),
                ("checkout", "📤  Malzeme Çıkışı"),
                ("entry", "📥  Malzeme Girişi"),
                ("history", "📜  İşlem Geçmişi"),
                ("report", "📈  Rapor Al"),
                ("purchase", "💰  Satın Alma")
            ]
            
            # DB'den gecmis loglari yukle
            with self.db.get_conn() as conn:
                logs = conn.execute("SELECT message FROM undo_logs ORDER BY id ASC").fetchall()
                self.undone_log = [l[0] for l in logs]

            # Arayuzu gecikmeli yukle (Donmayi engeller)
            self.after(200, self.init_ui_safe)
            self.after(3000, self.auto_backup)
        except Exception as e:
            messagebox.showerror("Kritik Hata", f"Başlatma hatası: {e}")

    def push_undo(self, name, undo_func, redo_func):
        """Yeni bir islem yapildiginda undo stack'e ekler ve redo stack'i temizler."""
        self.undo_stack.append((name, undo_func, redo_func))
        self.redo_stack.clear()

    def init_ui_safe(self):
        try:
            self.init_ui()
            self.animate()
        except Exception as e:
            log_debug(f"UI Yukleme Hatasi: {e}")
            messagebox.showerror("Arayüz Hatası", f"Arayüz yüklenirken hata oluştu:\n{e}")

    def undo_last_action(self):
        if not self.undo_stack:
            messagebox.showinfo("Bilgi", "Geri alınacak işlem yok.")
            return
        
        name, undo_func, redo_func = self.undo_stack.pop()
        try:
            undo_func()
            self.redo_stack.append((name, undo_func, redo_func)) # Redo stack'e tasi
            
            log_entry = f"[{datetime.now().strftime('%H:%M')}] Geri Alındı: {name}"
            self.undone_log.append(log_entry)
            
            # DB'ye kaydet
            with self.db.get_conn() as conn:
                conn.execute("INSERT INTO undo_logs (message, timestamp) VALUES (?,?)", (log_entry, datetime.now().isoformat()))
                # Sadece son 5 logu tut
                conn.execute("DELETE FROM undo_logs WHERE id NOT IN (SELECT id FROM undo_logs ORDER BY id DESC LIMIT 5)")
                conn.commit()
            
            show_info_optout(self, "Bilgi", f"Geri alındı:\n{name}", "opt_undo_success", self.db)
            self.show_page(self.current_page_key)
        except Exception as e:
            messagebox.showerror("Hata", f"Geri alma hatası: {e}")

    def redo_last_action(self):
        if not self.redo_stack:
            messagebox.showinfo("Bilgi", "Yinelenecek işlem yok.")
            return
        
        name, undo_func, redo_func = self.redo_stack.pop()
        try:
            redo_func()
            self.undo_stack.append((name, undo_func, redo_func)) # Undo stack'e geri koy
            
            log_entry = f"[{datetime.now().strftime('%H:%M')}] Yenilendi: {name}"
            self.undone_log.append(log_entry)
            
            # DB'ye kaydet
            with self.db.get_conn() as conn:
                conn.execute("INSERT INTO undo_logs (message, timestamp) VALUES (?,?)", (log_entry, datetime.now().isoformat()))
                conn.execute("DELETE FROM undo_logs WHERE id NOT IN (SELECT id FROM undo_logs ORDER BY id DESC LIMIT 5)")
                conn.commit()
            
            show_info_optout(self, "Bilgi", f"Yinelendi:\n{name}", "opt_redo_success", self.db)
            self.show_page(self.current_page_key)
        except Exception as e:
            messagebox.showerror("Hata", f"Yineleme hatası: {e}")

    def auto_backup(self):
        try:
            backup_dir = ROOT_DIR / "Yedekler"
            backup_dir.mkdir(exist_ok=True)
            if os.path.exists(DB_PATH):
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = backup_dir / f"Yedek_{timestamp}.db"
                shutil.copy(DB_PATH, target)
                
                backups = sorted(list(backup_dir.glob("Yedek_*.db")))
                if len(backups) > 20:
                    for b in backups[:-20]:
                        try: os.remove(b)
                        except: pass
        except: pass

    def gen_gradient(self):
        cols = []
        for i in range(0, 91, 10): cols.append(f'#ff{i:02x}00')
        for i in range(90, 0, -10): cols.append(f'#ff{i:02x}00')
        return cols

    def animate(self):
        if self.current_tree:
            try:
                c = next(self.color_cycle)
                self.current_tree.tag_configure("critical", foreground=c)
            except: pass
        self.after(70, self.animate)

    def show_toast(self, message):
        """Animasyonlu ve sure cubuklu toast bildirim."""
        toast = ctk.CTkFrame(self, fg_color="#333333", corner_radius=15, border_width=1, border_color="gray50", width=300, height=60)
        toast.place(relx=0.5, rely=-0.1, anchor="n") # Ekran disindan basla
        
        lbl = ctk.CTkLabel(toast, text=message, font=("Segoe UI", 13), text_color="white")
        lbl.place(relx=0.5, rely=0.4, anchor="center")
        
        # Sure Cubugu
        progress = ctk.CTkProgressBar(toast, width=260, height=4, progress_color="#3498db", fg_color="gray30")
        progress.place(relx=0.5, rely=0.85, anchor="center")
        progress.set(1.0)
        
        # Animasyon Degiskenleri
        start_y = -0.1
        target_y = 0.05
        steps = 20
        duration = 2000 # ms
        interval = 20 # ms (animasyon akiciligi)
        step_y = (target_y - start_y) / steps
        
        def slide_down(current_step):
            if current_step < steps:
                new_y = start_y + (step_y * (current_step + 1))
                toast.place(rely=new_y)
                self.after(interval, lambda: slide_down(current_step + 1))
            else:
                self.after(10, update_progress) # Animasyon bitince cubugu baslat

        def update_progress(start_time=None):
            if start_time is None: start_time = datetime.now()
            
            elapsed = (datetime.now() - start_time).total_seconds() * 1000
            remaining = 1.0 - (elapsed / duration)
            
            if remaining > 0:
                progress.set(remaining)
                self.after(30, lambda: update_progress(start_time))
            else:
                toast.destroy()

        slide_down(0)

    def init_ui(self):
        self.sidebar = ctk.CTkFrame(self, width=240, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)
        self.sidebar.pack_propagate(False)
        
        # --- LOGO VE BANNER YÜKLEME ---
        banner_path = BASE_DIR / "banner.png"
        logo_text = self.db.get_setting('depot_name') or "RDT PRO"
        
        if banner_path.exists() and Image and ImageTk:
            try:
                pil_banner = Image.open(str(banner_path))
                # Sidebar genişliği yaklaşık 240px, banner için 200px genişlik ideal
                orig_w, orig_h = pil_banner.size
                ratio = 200 / orig_w
                new_h = int(orig_h * ratio)
                
                ctk_banner = ctk.CTkImage(light_image=pil_banner, dark_image=pil_banner, size=(200, new_h))
                self.banner_label = ctk.CTkLabel(self.sidebar, image=ctk_banner, text="")
                self.banner_label.pack(pady=(30, 10), padx=10)
                
                # Altına Ayarlanmış İsim (Metin Logo)
                self.logo_label = ctk.CTkLabel(self.sidebar, text=logo_text, font=("Arial Black", 14), wraplength=220)
                self.logo_label.pack(pady=(0, 20), padx=10)
            except:
                self.logo_label = ctk.CTkLabel(self.sidebar, text=logo_text, font=("Arial Black", 20), wraplength=220)
                self.logo_label.pack(pady=40, padx=10)
        else:
            self.logo_label = ctk.CTkLabel(self.sidebar, text=logo_text, font=("Arial Black", 20), wraplength=220)
            self.logo_label.pack(pady=40, padx=10)

        ctk.CTkFrame(self.sidebar, height=2, fg_color="gray30").pack(fill="x", padx=15, pady=(0, 20))

        # Butonlar icin container
        self.nav_container = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.nav_container.pack(fill="both", expand=True)
        
        # Dinamik Moduller Yukleniyor
        self.load_modules()
        
        # Menuyu Ciz
        self.refresh_sidebar()
        
        # Alt Kısım (Tema vb.)
        bottom_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        bottom_frame.pack(side="bottom", fill="x", pady=20, padx=5)
        
        # Geri Al / Yinele (Ustte)
        ur_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        ur_frame.pack(fill="x", pady=(0, 15))
        # width=20 vererek kuculmelerine izin veriyoruz, expand ile yayilacaklar
        self.btn_undo = ctk.CTkButton(ur_frame, text="↩", command=self.undo_last_action, fg_color="#ef5350", hover_color="#d32f2f", width=20, height=30, font=("Arial", 20, "bold"))
        self.btn_undo.pack(side="left", padx=2, fill="x", expand=True)
        self.btn_redo = ctk.CTkButton(ur_frame, text="↪", command=self.redo_last_action, fg_color="#9ccc65", hover_color="#7cb342", width=20, height=30, font=("Arial", 20, "bold"))
        self.btn_redo.pack(side="left", padx=2, fill="x", expand=True)
        
        # Ayarlar ve Tema (Yan Yana)
        settings_frame = ctk.CTkFrame(bottom_frame, fg_color="transparent")
        settings_frame.pack(fill="x")
        
        # Tema Secimi (Solda, Genis)
        self.theme_menu = ctk.CTkOptionMenu(settings_frame, values=["Dark", "Light"], command=self.change_theme, height=28, font=("Segoe UI", 11))
        self.theme_menu.pack(side="left", fill="x", expand=True, padx=(0, 5))
        
        # Ayarlar Butonu (Sagda, Kare)
        btn_settings = ctk.CTkButton(settings_frame, text="⚙️", command=lambda: self.show_page("settings"), width=28, height=28, fg_color="gray40", hover_color="gray60", font=("Arial", 16))
        btn_settings.pack(side="right")
        
        self.nav_buttons["settings"] = btn_settings # Aktiflik gostergesi icin
        
        self.container = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew", padx=20, pady=20)
        
        self.show_page("dashboard")

    def refresh_sidebar(self):
        # Mevcut butonlari temizle (Container icindekileri)
        for widget in self.nav_container.winfo_children():
            widget.destroy()
        
        # Settings butonunu koru
        settings_btn = self.nav_buttons.get("settings")
        self.nav_buttons.clear()
        if settings_btn: self.nav_buttons["settings"] = settings_btn
        
        # Wrapper referanslarini tutmak icin (animasyon icin)
        self.nav_wrappers = {}

        # 1. Standart Menuler
        for key, title in self.menu_definitions:
            if key in self.nav_buttons: continue 
            
            # Gorunurluk Kontrolu
            vis = self.db.get_setting(f"menu_vis_{key}")
            if vis == "0": continue
            
            cmd = lambda k=key: self.show_page(k)
            # Wrapper ve butonu kaydet
            wrapper, btn = self.add_nav(title, cmd, parent=self.nav_container)
            self.nav_buttons[key] = btn
            self.nav_wrappers[key] = wrapper

        # 2. Modul Menuleri
        for key, mod in self.loaded_modules.items():
            if key in self.nav_buttons: continue
            
            # Ozel: Bu moduller sol menude gorunmesin (Sadece ozellik katiyorlar)
            if key in ["supplier_quality", "expiry_date"]: continue

            vis = self.db.get_setting(f"menu_vis_{key}")
            if vis == "0": continue
            
            title = mod.info.get("title", key)
            cmd = lambda k=key: self.show_page(k)
            wrapper, btn = self.add_nav(title, cmd, parent=self.nav_container)
            self.nav_buttons[key] = btn
            self.nav_wrappers[key] = wrapper

    def add_nav(self, text, cmd, parent=None):
        if parent is None: parent = self.sidebar
        
        # Animasyon icin Wrapper Frame
        wrapper = ctk.CTkFrame(parent, fg_color="transparent", height=50)
        wrapper.pack(fill="x", pady=2)
        wrapper.pack_propagate(False) # Icindeki butonun boyutuna gore degil, kendi boyutunda kal
        
        btn = ctk.CTkButton(wrapper, text=text, command=cmd, height=50, anchor="w", font=("Segoe UI", 13, "bold"), fg_color="transparent", text_color=("gray10", "gray90"), hover_color=("gray70", "gray30"))
        btn.pack(fill="both", expand=True, padx=10)
        
        return wrapper, btn
        
    def animate_hide(self, wrapper):
        """Wrapper Frame'in yuksekligini azaltarak yok etme"""
        try:
            h = wrapper.winfo_height()
            if h > 2:
                h -= 4 # Hizli kuculme
                wrapper.configure(height=h)
                self.after(5, lambda: self.animate_hide(wrapper))
            else:
                wrapper.pack_forget()
                wrapper.destroy()
        except: pass

    def animate_show(self, wrapper, target_h=50, current_h=0):
        """Wrapper Frame'in yuksekligini artirarak gosterme"""
        try:
            if current_h < target_h:
                current_h += 4
                if current_h > target_h: current_h = target_h
                wrapper.configure(height=current_h)
                self.after(5, lambda: self.animate_show(wrapper, target_h, current_h))
            else:
                wrapper.configure(height=target_h)
        except: pass 

    def set_active_nav(self, key):
        # Settings butonu refresh_sidebar ile silinmez, ozel referansi vardir
        if key == "settings" and "settings" in self.nav_buttons:
             self.nav_buttons["settings"].configure(fg_color="gray60")
        elif "settings" in self.nav_buttons:
             self.nav_buttons["settings"].configure(fg_color="gray40")

        for k, b in self.nav_buttons.items():
            if k == "settings": continue # Ozel islem yapildi
            
            if k == key: b.configure(border_width=2, border_color="#3498db", fg_color=('#d1d1d1', '#34495e'))
            else: b.configure(border_width=0, fg_color="transparent")

    def change_theme(self, mode):
        ctk.set_appearance_mode(mode)
        
        # Grafik cache temizle (Yeni renklerle cizilmesi icin)
        self.cached_fig = None
        
        # Treeview stillerini guncelle
        bg = "#2b2b2b" if mode == "Dark" else "white"
        fg = "white" if mode == "Dark" else "black"
        style = ttk.Style()
        style.configure("Treeview", background=bg, foreground=fg, fieldbackground=bg)
        style.configure("Treeview.Heading", background="#34495e", foreground="white")
        
        # Eger Dashboard aciksa grafigi yenile (Renkler icin)
        if self.current_page_key == "dashboard":
            self.after(500, lambda: self.start_chart_thread(force=True)) if hasattr(self, 'start_chart_thread') else None

    def load_modules(self):
        """Modules klasorundeki alt klasorleri tarar ve main.py dosyasini yukler."""
        self.loaded_modules.clear()
        self.available_modules = []
        
        # Moduller ana dizinde aranir
        modules_dir = BASE_DIR / "modules"
        
        if not modules_dir.exists():
            try:
                modules_dir.mkdir(parents=True, exist_ok=True)
                log_debug(f"Modules klasoru olusturuldu: {modules_dir}")
            except Exception as e:
                log_debug(f"Modules klasoru olusturulamadi: {e}")

        # Alt klasorlerdeki main.py dosyalarini tara
        module_files = list(modules_dir.glob("*/main.py"))
        log_debug(f"Taranan klasor: {modules_dir}")
        log_debug(f"Bulunan moduller: {[f.parent.name for f in module_files]}")
        
        for file_path in module_files:
            try:
                # Modul ismi klasor adi olsun (benzersizlik icin)
                module_name = file_path.parent.name
                
                spec = importlib.util.spec_from_file_location(module_name, str(file_path))
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                
                # Modul standartlarina uygun mu? (info ve render objeleri var mi?)
                if hasattr(mod, "info") and hasattr(mod, "render"):
                    key = mod.info.get("key", module_name)
                    title = mod.info.get("title", key)
                    
                    self.available_modules.append({
                        "key": key,
                        "title": title,
                        "path": str(file_path),
                        "module_obj": mod
                    })
                    
                    # DB kontrolu
                    db_state = self.db.get_setting(f"mod_state_{key}")
                    is_active = (db_state != "0") 
                    
                    if is_active:
                        self.loaded_modules[key] = mod
                        # Butonu refresh_sidebar ekleyecek
                        log_debug(f"Modul yuklendi: {title}")
                    else:
                        log_debug(f"Modul pasif: {title}")
                else:
                    log_debug(f"Gecersiz modul yapisi: {module_name} (info veya render eksik)")
                        
            except Exception as e:
                print(f"!!! MODÜL YÜKLEME HATASI ({file_path.parent.name}): {e}")
                import traceback
                traceback.print_exc()
                log_debug(f"Modul yukleme hatasi ({file_path.parent.name}): {e}")

    def show_page(self, key):
        self.current_page_key = key
        self.set_active_nav(key)
        for w in self.container.winfo_children(): w.destroy()
        self.current_tree = None
        
        if key == "dashboard": self.render_dashboard()
        elif key == "stock": self.render_stock()
        elif key == "checkout": self.render_checkout()
        elif key == "entry": self.render_entry()
        elif key == "history": self.render_history()
        elif key == "report": self.render_report()
        elif key == "purchase": self.render_purchase()
        elif key == "settings": self.render_settings()
        elif key in self.loaded_modules:
            # Modul render fonksiyonunu cagir
            self.loaded_modules[key].render(self, self.container)
            
        self.update_idletasks()

    def render_dashboard(self):
        with self.db.get_conn() as conn:
            total_types = conn.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
            total_stock = conn.execute("SELECT SUM(stock) FROM materials WHERE is_unlimited=0").fetchone()[0] or 0
            critical_count = conn.execute("SELECT COUNT(*) FROM materials WHERE stock <= 3 AND track_critical=1 AND is_unlimited=0").fetchone()[0]

        top_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        top_frame.pack(fill="x", pady=(0, 15))
        top_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform="card")

        def create_card(parent, title, value, color, col):
            card = ctk.CTkFrame(parent, height=120, fg_color=color, corner_radius=15)
            card.grid(row=0, column=col, padx=10, sticky="ew")
            card.grid_propagate(False)
            ctk.CTkLabel(card, text=title, font=("Segoe UI", 16, "bold"), text_color="white").pack(pady=(20, 5))
            ctk.CTkLabel(card, text=str(value), font=("Segoe UI", 36, "bold"), text_color="white").pack()

        create_card(top_frame, "TOPLAM ÇEŞİT", total_types, "#2980b9", 0)
        create_card(top_frame, "TOPLAM STOK ADEDİ", f"{total_stock:g}", "#27ae60", 1)
        create_card(top_frame, "KRİTİK UYARI", critical_count, "#c0392b", 2)

        # FİLTRE PANELİ
        filter_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        filter_frame.pack(fill="x", pady=(0, 10), padx=10)

        date_frame = ctk.CTkFrame(filter_frame, fg_color="transparent")
        date_frame.pack(side="left")

        ctk.CTkLabel(date_frame, text="Başlangıç:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=(0, 5))
        
        start_date_widget = None
        end_date_widget = None
        
        if DateEntry is not None:
            style_args = {'width': 12, 'background': '#3498db', 'foreground': 'white', 'borderwidth': 2, 'date_pattern': 'dd.mm.yyyy'}
            start_date_widget = DateEntry(date_frame, **style_args)
            start_date_widget.pack(side="left", padx=5)
            
            ctk.CTkLabel(date_frame, text="Bitiş:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
            end_date_widget = DateEntry(date_frame, **style_args)
            end_date_widget.pack(side="left", padx=5)
            try:
                start_date_widget.set_date(datetime(datetime.now().year, 1, 1))
                end_date_widget.set_date(datetime.now())
            except: pass
        else:
            start_date_widget = ctk.CTkEntry(date_frame, width=100)
            start_date_widget.pack(side="left", padx=5)
            start_date_widget.insert(0, f"01.01.{datetime.now().year}")
            
            ctk.CTkLabel(date_frame, text="Bitiş:", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
            end_date_widget = ctk.CTkEntry(date_frame, width=100)
            end_date_widget.pack(side="left", padx=5)
            end_date_widget.insert(0, datetime.now().strftime("%d.%m.%Y"))

        var_all_time = tk.IntVar(value=0)
        
        def toggle_dates():
            state = "disabled" if var_all_time.get() == 1 else "normal"
            if DateEntry is not None:
                if var_all_time.get() == 1:
                    start_date_widget.configure(state="disabled")
                    end_date_widget.configure(state="disabled")
                else:
                    start_date_widget.configure(state="normal")
                    end_date_widget.configure(state="normal")
            else:
                start_date_widget.configure(state=state)
                end_date_widget.configure(state=state)

        chk_all_time = ctk.CTkCheckBox(filter_frame, text="Tüm Zamanlar", variable=var_all_time, command=toggle_dates, font=("Segoe UI", 12))
        chk_all_time.pack(side="left", padx=20)
        
        # --- ORTA BOLUM (GRAFIK + WIDGETS) ---
        middle_section = ctk.CTkFrame(self.container, fg_color="transparent")
        middle_section.pack(fill="both", expand=True, pady=10)
        middle_section.grid_columnconfigure(0, weight=2) # Grafik genis
        middle_section.grid_columnconfigure(1, weight=1) # Widget dar
        middle_section.grid_rowconfigure(0, weight=1)

        # GRAFIK ALANI (SOL)
        chart_frame = ctk.CTkFrame(middle_section, corner_radius=15, fg_color=("white", "#2b2b2b"))
        chart_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        
        title_lbl = ctk.CTkLabel(chart_frame, text="EKİPLERE GÖRE KULLANIM DAĞILIMI", font=("Segoe UI", 18, "bold"))
        title_lbl.pack(pady=(15, 5))
        
        self.chart_canvas = None 
        self.lbl_loading = ctk.CTkLabel(chart_frame, text="Grafik Hazırlanıyor...", font=("Segoe UI", 14, "italic"), text_color="gray")
        self.lbl_loading.pack(pady=50)

        # WIDGET ALANI (SAG)
        widget_scroll = ctk.CTkScrollableFrame(middle_section, fg_color="transparent")
        widget_scroll.grid(row=0, column=1, sticky="nsew")

        def draw_chart_on_ui(fig):
            # Bu fonksiyon ana thread'de calisir
            try:
                self.lbl_loading.pack_forget()
                if self.chart_canvas:
                    try: self.chart_canvas.get_tk_widget().destroy()
                    except: pass
                
                if fig:
                    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
                    self.chart_canvas = FigureCanvasTkAgg(fig, master=chart_frame)
                    self.chart_canvas.draw()
                    self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=20, pady=10)
                else:
                    ctk.CTkLabel(chart_frame, text="Veri bulunamadı.", font=("Segoe UI", 14, "italic")).pack(pady=50)
            except Exception as e:
                log_debug(f"Grafik Cizim Hatasi: {e}")

        def prepare_chart_data():
            # Bu fonksiyon arka planda (thread) calisir
            import sqlite3
            from matplotlib.figure import Figure
            
            try:
                # Thread icinde kendi baglantimizi acmaliyiz
                t_conn = sqlite3.connect(DB_PATH)
                pie_data = {}
                
                # UI elemanlarina erisim thread-safe degildir, degerleri parametre olarak almak daha dogruydu
                # ama okuma islemi genelde sorun cikarmaz. Yine de dikkatli olalim.
                # Burada UI'dan veri okumak yerine varsayilanlari veya cached degerleri kullanmak lazim.
                # Ancak basitlik adina kisa sureli UI erisimi riskini aliyoruz veya degerleri
                # thread baslatilmadan once alip gondermeliyiz.
                # Threading yapisini asagiya tasiyorum.
                pass
            except: pass

        def start_chart_thread(force=False):
            # Eger zorlama yoksa ve cache varsa, cache kullan
            if not force and self.cached_fig:
                draw_chart_on_ui(self.cached_fig)
                return

            # UI degerlerini ana thread'de al
            is_all = var_all_time.get() == 1
            s_str = start_date_widget.get()
            e_str = end_date_widget.get()
            
            def thread_target():
                try:
                    import sqlite3
                    from matplotlib.figure import Figure
                    
                    pie_data = {}
                    t_conn = sqlite3.connect(DB_PATH)
                    cursor = t_conn.cursor()
                    
                    raw_data = cursor.execute("SELECT receiver, date FROM transactions WHERE type='ÇIKIŞ'").fetchall()
                    t_conn.close()

                    dt_start = None
                    dt_end = None
                    if not is_all:
                        try:
                            dt_start = datetime.strptime(s_str, "%d.%m.%Y")
                            dt_end = datetime.strptime(e_str, "%d.%m.%Y")
                            dt_end = dt_end.replace(hour=23, minute=59, second=59)
                        except: pass

                    for rcv, date_str in raw_data:
                        try:
                            valid = False
                            if is_all:
                                valid = True
                            elif dt_start and dt_end:
                                dt_current = datetime.strptime(date_str, "%d.%m.%Y")
                                if dt_start <= dt_current <= dt_end:
                                    valid = True
                            
                            if valid:
                                rcv = rcv.strip()
                                pie_data[rcv] = pie_data.get(rcv, 0) + 1
                        except: continue
                    
                    if pie_data:
                        labels = list(pie_data.keys())
                        sizes = list(pie_data.values())
                        
                        # Figur olusturma (Matplotlib)
                        fig = Figure(figsize=(5, 5), dpi=100, facecolor="#2b2b2b")
                        ax = fig.add_subplot(111)
                        
                        # Renkler (Tema bagimsiz sabit koyu tema icin ayarliyorum)
                        text_color = "white"
                        bg_color = "#2b2b2b"
                        fig.patch.set_facecolor(bg_color)
                        
                        colors = ['#3498db', '#e74c3c', '#2ecc71', '#f1c40f', '#9b59b6', '#e67e22', '#1abc9c', '#34495e']
                        wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90, 
                                                          colors=colors[:len(labels)],
                                                          textprops=dict(color=text_color))
                        ax.axis('equal')
                        
                        # Cache'e kaydet
                        self.cached_fig = fig
                        
                        # Cizimi ana thread'e gonder
                        self.after(0, lambda: draw_chart_on_ui(fig))
                    else:
                        self.cached_fig = None
                        self.after(0, lambda: draw_chart_on_ui(None))

                except Exception as e:
                    # Loglama kapali pass
                    pass
            
            import threading
            threading.Thread(target=thread_target, daemon=True).start()

        ctk.CTkButton(filter_frame, text="LİSTELE / YENİLE", command=lambda: start_chart_thread(force=True), width=120, height=30, fg_color="#e67e22", font=("Bold", 12)).pack(side="left", padx=10)
        
        # --- WIDGETLARI YUKLE (DİNAMİK ÖNCELİKLİ) ---
        # Belirli widgetların en üstte görünmesi için sıralama önceliği listesi
        priority_list = ["supplier_quality", "critical_stock", "expiry_date", "location_management"]
        
        # 1. Öncelikli modülleri ekle
        for key in priority_list:
            if key in self.loaded_modules:
                mod = self.loaded_modules[key]
                if hasattr(mod, "render_dashboard_widget"):
                    try:
                        w_frame = ctk.CTkFrame(widget_scroll, fg_color="transparent")
                        w_frame.pack(fill="x", pady=5)
                        mod.render_dashboard_widget(self, w_frame)
                    except: pass
        
        # 2. Listede olmayan diğer tüm modül widgetlarını ekle
        for key, mod in self.loaded_modules.items():
            if key not in priority_list and hasattr(mod, "render_dashboard_widget"):
                try:
                    w_frame = ctk.CTkFrame(widget_scroll, fg_color="transparent")
                    w_frame.pack(fill="x", pady=5)
                    mod.render_dashboard_widget(self, w_frame)
                except: pass

        # Arayuz acildiktan sonra grafigi yukle (Cache varsa hemen gelir)
        self.after(100, start_chart_thread)

    def render_stock(self):
        head = ctk.CTkFrame(self.container, height=60, fg_color="#34495e", corner_radius=10); head.pack(fill="x", pady=(0, 15))
        ctk.CTkLabel(head, text="📦 MEVCUT STOK", font=("Segoe UI", 20, "bold"), text_color="white").pack(side="left", padx=20, pady=15)
        
        tools = ctk.CTkFrame(self.container, fg_color="transparent"); tools.pack(fill="x", pady=5)
        ctk.CTkButton(tools, text="Excel Yükle", fg_color="#27ae60", width=100, command=self.import_action).pack(side="left", padx=5)
        ctk.CTkButton(tools, text="Tümünü Sil", fg_color="#c0392b", width=100, command=self.clear_db_action).pack(side="left", padx=5)
        
        # --- TOPLU İŞLEM DESTEĞİ ---
        self.bulk_mode = False
        self.selected_items = set() # material_id'leri tutar

        def run_bulk_delete():
            if not self.selected_items: return
            if not ask_yesno_optout(self, "Toplu Silme Onayı", 
                                    f"Seçilen {len(self.selected_items)} ürün ve tüm geçmiş hareketleri kalıcı olarak silinecek.\nDevam edilsin mi?", 
                                    "opt_bulk_del_confirm", self.db): 
                return
            
            with self.db.get_conn() as conn:
                try:
                    placeholders = ','.join(['?'] * len(self.selected_items))
                    s_ids = list(self.selected_items)
                    # Islemleri transaction ile yap
                    conn.execute("BEGIN TRANSACTION")
                    conn.execute(f"DELETE FROM transactions WHERE material_id IN ({placeholders})", s_ids)
                    conn.execute(f"DELETE FROM product_locations WHERE product_id IN ({placeholders})", s_ids)
                    conn.execute(f"DELETE FROM materials WHERE id IN ({placeholders})", s_ids)
                    conn.commit()
                    self.db.reindex_materials()
                    self.selected_items.clear()
                    toggle_bulk_mode() # Modu kapat
                    show_info_optout(self, "Başarılı", "Seçilen ürünler silindi.", "opt_bulk_del_info", self.db)
                except Exception as e:
                    conn.execute("ROLLBACK")
                    messagebox.showerror("Hata", f"Silme işlemi başarısız: {e}")

        def toggle_all_selection():
            # Mevcut view'daki tüm ID'leri al
            all_ids = []
            for item in self.current_tree.get_children():
                # ID kolonu indexi bulk mode'da 1, normalde 0. Ama load() sırasında vals'e göre bakarsak:
                # Bulk mode aktifse: vals = [chk, id, name, loc, stock, unit]
                v = self.current_tree.item(item, "values")
                if self.bulk_mode and len(v) > 1:
                    all_ids.append(int(v[1]))
            
            if not all_ids: return

            # Eğer hepsi seçiliyse bırak, değilse hepsini seç
            if all(mid in self.selected_items for mid in all_ids):
                for mid in all_ids: self.selected_items.discard(mid)
            else:
                for mid in all_ids: self.selected_items.add(mid)
            
            # Arayüzü güncellemek için tekrar load (veya sadece tree item update)
            # Daha temiz bir görünüm için load() çağıralım
            load(search_var.get())
            update_bulk_buttons()

        def update_bulk_buttons():
            count = len(self.selected_items)
            if self.bulk_mode:
                self.btn_execute_bulk.configure(text=f"⚡ DÜZENLE ({count})")
                self.btn_bulk_del.configure(text=f"🗑️ SİL ({count})")
                if count > 0:
                    self.btn_execute_bulk.pack(side="left", padx=5)
                    self.btn_bulk_del.pack(side="left", padx=5)
                else:
                    self.btn_execute_bulk.pack_forget()
                    self.btn_bulk_del.pack_forget()

        def toggle_bulk_mode():
            self.bulk_mode = not self.bulk_mode
            self.selected_items.clear()
            btn_bulk_toggle.configure(text="❌ SEÇİMİ KAPAT" if self.bulk_mode else "⚙️ TOPLU İŞLEMLER", 
                                      fg_color="#d35400" if self.bulk_mode else "#34495e")
            
            if self.bulk_mode:
                self.btn_all_sel.pack(side="left", padx=5)
            else:
                self.btn_all_sel.pack_forget()
                self.btn_execute_bulk.pack_forget()
                self.btn_bulk_del.pack_forget()
                
            load(search_var.get())

        if "bulk_actions" in self.loaded_modules:
            btn_bulk_toggle = ctk.CTkButton(tools, text="⚙️ TOPLU İŞLEMLER", fg_color="#34495e", width=120, command=toggle_bulk_mode)
            btn_bulk_toggle.pack(side="left", padx=5)
            
            self.btn_all_sel = ctk.CTkButton(tools, text="📝 TÜMÜNÜ SEÇ", fg_color="#7f8c8d", width=110, command=toggle_all_selection)
            
            self.btn_execute_bulk = ctk.CTkButton(tools, text="⚡ DÜZENLE (0)", fg_color="#27ae60", width=110, 
                                                 command=lambda: self.loaded_modules["bulk_actions"].open_bulk_edit_window(self, list(self.selected_items), load))
            
            self.btn_bulk_del = ctk.CTkButton(tools, text="🗑️ SİL (0)", fg_color="#c0392b", width=100, command=run_bulk_delete)

        ent_search = ctk.CTkEntry(tools, placeholder_text="🔍 Ürün Arayabilirsiniz...", width=250)
        ent_search.pack(side="right")
        
        card = ctk.CTkFrame(self.container, corner_radius=15); card.pack(fill="both", expand=True)
        
        # --- OPTIMIZED SEARCH (DEBOUNCE) ---
        def on_search_trigger(event=None):
            if hasattr(self, 'search_job') and self.search_job:
                self.after_cancel(self.search_job)
            q = ent_search.get()
            self.search_job = self.after(300, lambda: load(q))

        ent_search.bind("<KeyRelease>", on_search_trigger)

        # Dinamik Kolon Yapısı (SIFIRDAN TANIMLA)
        self.img_map = {}
        self.tooltip_win = None
        self.last_hovered_item = None

        def load(q=""):
            self.img_map.clear()
            is_loc_active = "location_management" in self.loaded_modules
            
            # Treeview'ı her load edildiğinde yeniden yapılandır (Kolon kaymasını önlemek için)
            for w in card.winfo_children(): w.destroy()
            
            cols = []
            if self.bulk_mode: cols.append("Seç")
            cols.extend(["ID", "Malzeme Adı"])
            if is_loc_active: cols.append("Konum")
            cols.extend(["Stok", "Birim"])
            
            self.current_tree = self.setup_treeview(card, tuple(cols))
            
            # Kolon Genişlikleri
            if self.bulk_mode: self.current_tree.column("Seç", width=50)
            self.current_tree.column("ID", width=60)
            self.current_tree.column("Malzeme Adı", width=400, anchor="w")
            if is_loc_active: self.current_tree.column("Konum", width=200, anchor="w")
            
            # Event Bindings
            self.current_tree.bind("<Button-1>", on_tree_click)
            self.current_tree.bind("<Button-3>", show_right_click_menu)
            self.current_tree.bind("<Double-1>", lambda e: self.open_edit_popup(self.current_tree.item(self.current_tree.selection()[0], "values")[1 if self.bulk_mode else 0], load))
            self.current_tree.bind("<Motion>", on_hover)
            self.current_tree.bind("<Leave>", on_leave)

            with self.db.get_conn() as conn:
                try:
                    if is_loc_active:
                        query = """
                            WITH RECURSIVE Path(id, name, parent_id, full_path) AS (
                                SELECT id, name, parent_id, name FROM location_nodes WHERE (parent_id IS NULL OR parent_id = 0)
                                UNION ALL
                                SELECT n.id, n.name, n.parent_id, p.full_path || ' > ' || n.name
                                FROM location_nodes n JOIN Path p ON n.parent_id = p.id
                            )
                            SELECT m.id, m.name, m.stock, m.unit, m.track_critical, m.image_path, m.is_unlimited,
                            (
                                SELECT p.full_path FROM Path p 
                                JOIN product_locations pl ON pl.location_id = (SELECT id FROM locations WHERE node_id = p.id)
                                WHERE pl.product_id = m.id LIMIT 1
                            ) as full_loc
                            FROM materials m 
                            WHERE TR_LOWER(m.name) LIKE TR_LOWER(?) 
                            ORDER BY m.name
                        """
                    else:
                        query = "SELECT id, name, stock, unit, track_critical, image_path, is_unlimited, '-' FROM materials WHERE TR_LOWER(name) LIKE TR_LOWER(?) ORDER BY name"
                    
                    mats = conn.execute(query, (f"%{q}%",)).fetchall()
                except Exception as e:
                     log_debug(f"SQL Hatası: {e}")
                     mats = conn.execute("SELECT id, name, stock, unit, track_critical, NULL, 0, '-' FROM materials WHERE TR_LOWER(name) LIKE TR_LOWER(?) ORDER BY name", (f"%{q}%",)).fetchall()

                for r in mats:
                    s = r[2] if r[2] is not None else 0
                    is_ul = r[6] if len(r) > 6 and r[6] == 1 else 0
                    disp_s = "∞" if is_ul else f"{s:g}"
                    tag = "critical" if (not is_ul and s <= 3 and r[4] == 1) else "normal"

                    vals = []
                    if self.bulk_mode:
                        vals.append("☑" if r[0] in self.selected_items else "☐")
                    
                    vals.extend([r[0], r[1]])
                    if is_loc_active: vals.append(r[7] if r[7] else "-")
                    vals.extend([disp_s, r[3]])

                    item_id = self.current_tree.insert("", "end", values=tuple(vals), tags=(tag,))
                    if r[5]: self.img_map[item_id] = r[5]
            
            self.apply_sorting(self.current_tree)

        def on_tree_click(event):
            if not self.bulk_mode: return
            item = self.current_tree.identify_row(event.y)
            if not item: return
            
            col = self.current_tree.identify_column(event.x)
            if col == "#1":
                m_id = int(self.current_tree.item(item, "values")[1])
                if m_id in self.selected_items: self.selected_items.remove(m_id)
                else: self.selected_items.add(m_id)
                
                curr_vals = list(self.current_tree.item(item, "values"))
                curr_vals[0] = "☑" if m_id in self.selected_items else "☐"
                self.current_tree.item(item, values=tuple(curr_vals))
                update_bulk_buttons()

        def on_hover(event):
            item = self.current_tree.identify_row(event.y)
            
            # Fare koordinatları
            x = event.x_root + 20
            y = event.y_root + 20

            # Eğer öğe değiştiyse (veya yeni bir resimli öğeye gelindiyse)
            if item != self.last_hovered_item:
                self.last_hovered_item = item
                
                # Eski pencereyi kapat
                if self.tooltip_win:
                    self.tooltip_win.destroy()
                    self.tooltip_win = None
                    
                if item in self.img_map:
                    path = self.img_map[item]
                    if os.path.exists(path) and Image and ImageTk:
                        try:
                            pil_img = Image.open(path)
                            pil_img.thumbnail((200, 200))
                            tk_img = ImageTk.PhotoImage(pil_img)
                            
                            self.tooltip_win = tk.Toplevel(self)
                            self.tooltip_win.wm_overrideredirect(True)
                            self.tooltip_win.wm_geometry(f"+{x}+{y}")
                            self.tooltip_win.attributes('-topmost', True)
                            
                            lbl = tk.Label(self.tooltip_win, image=tk_img, bg="white", borderwidth=2, relief="solid")
                            lbl.image = tk_img 
                            lbl.pack()
                        except:
                            if self.tooltip_win:
                                self.tooltip_win.destroy()
                                self.tooltip_win = None
            else:
                # Öğe aynıysa sadece konumu güncelle (Takip etme özelliği)
                if self.tooltip_win:
                    self.tooltip_win.wm_geometry(f"+{x}+{y}")

        def on_leave(event):
            if self.tooltip_win:
                self.tooltip_win.destroy()
                self.tooltip_win = None
            self.last_hovered_item = None

        # --- SAĞ TIK MENÜSÜ ---
        self.stock_context_menu = tk.Menu(self, tearoff=0, bg="#2b2b2b", fg="white", font=("Segoe UI", 10))
        
        def show_right_click_menu(event):
            item = self.current_tree.identify_row(event.y)
            if not item: return
            
            self.current_tree.selection_set(item)
            self.stock_context_menu.delete(0, "end")
            
            # Eğer ürünün resmi varsa "Resmi Büyüt" seçeneğini ekle
            if item in self.img_map:
                path = self.img_map[item]
                self.stock_context_menu.add_command(label="🔍 Resmi Büyüt", command=lambda: self.show_full_image(path))
                self.stock_context_menu.add_separator()
            
            self.stock_context_menu.add_command(label="✏️ Düzenle", command=lambda: self.open_edit_popup(self.current_tree.item(item, "values")[1 if self.bulk_mode else 0], load))
            self.stock_context_menu.post(event.x_root, event.y_root)

        load()

    def render_checkout(self):
        try:
            with self.db.get_conn() as conn: 
                try: conn.execute("SELECT receiver FROM transactions LIMIT 1")
                except: conn.execute("ALTER TABLE transactions ADD COLUMN receiver TEXT"); conn.commit()

            for widget in self.container.winfo_children(): widget.destroy()

            with self.db.get_conn() as conn:
                teams = [r[0] for r in conn.execute("SELECT DISTINCT name FROM teams ORDER BY name").fetchall()]
                try:
                    mats_raw = conn.execute("SELECT id, name, stock, unit, is_unlimited FROM materials ORDER BY name").fetchall()
                except:
                    mats_raw = conn.execute("SELECT id, name, stock, unit, 0 FROM materials ORDER BY name").fetchall()
                    
                self.stock_map = {m[0]: {'name': m[1], 'stock': float(m[2]), 'unit': m[3], 'is_unlimited': (m[4]==1)} for m in mats_raw}
                
                m_display = []
                for m in mats_raw:
                    stk_str = "∞" if m[4]==1 else f"{float(m[2]):g}"
                    m_display.append(f"{m[1]} | Stok: {stk_str}")

            self.checkout_cart = []

            main_grid = ctk.CTkFrame(self.container, fg_color="transparent")
            main_grid.pack(fill="both", expand=True, padx=10, pady=10)
            main_grid.grid_columnconfigure(0, weight=2, uniform="main_layout")
            main_grid.grid_columnconfigure(1, weight=3, uniform="main_layout")
            main_grid.grid_rowconfigure(0, weight=1)

            left_card = ctk.CTkFrame(main_grid, corner_radius=20, fg_color=('#e6e6e6', '#212121'))
            left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=0)
            
            right_card = ctk.CTkFrame(main_grid, corner_radius=20, fg_color=('#f0f0f0', '#1a1a1a'))
            right_card.grid(row=0, column=1, sticky="nsew", padx=0, pady=0)

            ctk.CTkLabel(left_card, text="📝 İŞLEM BİLGİLERİ", font=("Segoe UI", 24, "bold"), text_color="#3498db").pack(pady=(20, 15))

            input_container = ctk.CTkFrame(left_card, fg_color="transparent")
            input_container.pack(fill="x", padx=20)

            ctk.CTkLabel(input_container, text="👤 Alıcı ve Tarih Seçimi", font=("Segoe UI", 14, "bold"), text_color="gray60").pack(anchor="w", pady=(0, 5))
            
            if DateEntry is not None:
                is_dark = (ctk.get_appearance_mode() == "Dark")
                self.ent_date = DateEntry(input_container, date_pattern='dd.mm.yyyy', font=("Segoe UI", 12), background='#3498db', foreground='white', borderwidth=2)
                self.ent_date.pack(fill="x", pady=5)
            else:
                self.ent_date = ctk.CTkEntry(input_container, height=45)
                self.ent_date.pack(fill="x", pady=5)
                self.ent_date.insert(0, datetime.now().strftime("%d.%m.%Y"))

            seg = ctk.CTkSegmentedButton(input_container, values=["Birim", "Personel"], height=35, font=("Segoe UI", 12, "bold"), selected_color="#3498db")
            seg.set("Birim")
            seg.pack(fill="x", pady=10)

            target_frame = ctk.CTkFrame(input_container, fg_color="transparent")
            target_frame.pack(fill="x")
            
            self.cb_team = ctk.CTkComboBox(target_frame, values=teams, height=40, font=("Segoe UI", 13), state="readonly")
            self.ent_person = ctk.CTkEntry(target_frame, placeholder_text="Personel Adı Giriniz...", height=40, font=("Segoe UI", 13))
            self.cb_team.pack(fill="x")

            def on_type_change(val):
                self.cb_team.pack_forget(); self.ent_person.pack_forget()
                if val == "Birim": self.cb_team.pack(fill="x")
                else: self.ent_person.pack(fill="x")
            seg.configure(command=on_type_change)

            ctk.CTkFrame(left_card, height=2, fg_color=("gray80", "gray30")).pack(fill="x", padx=20, pady=20)

            product_container = ctk.CTkFrame(left_card, fg_color="transparent")
            product_container.pack(fill="x", padx=20)

            ctk.CTkLabel(product_container, text="📦 Malzeme Ekleme", font=("Segoe UI", 14, "bold"), text_color="gray60").pack(anchor="w", pady=(0, 5))

            self.ent_mat_search = ctk.CTkEntry(product_container, placeholder_text="🔍 Malzeme Ara...", height=45, font=("Segoe UI", 14))
            self.ent_mat_search.pack(fill="x", pady=(5, 0))

            self.search_res_frame = tk.Frame(product_container)
            self.lb_results = tk.Listbox(self.search_res_frame, height=5, activestyle="none", relief="flat", 
                                         bg="#333333" if ctk.get_appearance_mode()=="Dark" else "#ffffff", 
                                         fg="white" if ctk.get_appearance_mode()=="Dark" else "black",
                                         selectbackground="#3498db", font=("Segoe UI", 11))
            self.lb_results.pack(side="left", fill="both", expand=True)
            
            self.selected_mat_id = None

            def filter_mats(event):
                if event.keysym in ['Up', 'Down', 'Return', 'Tab']: return
                query = tr_lower(self.ent_mat_search.get())
                self.lb_results.delete(0, tk.END)
                if not query: self.search_res_frame.place_forget(); return

                matches = [item for item in m_display if query in tr_lower(item)]
                if matches:
                    for m in matches: self.lb_results.insert(tk.END, m)
                    self.search_res_frame.place(in_=self.ent_mat_search, x=0, rely=1, relwidth=1)
                    self.search_res_frame.lift()
                else: self.search_res_frame.place_forget()

            def on_select(event):
                if not self.lb_results.curselection(): return
                sel_text = self.lb_results.get(self.lb_results.curselection())
                self.ent_mat_search.delete(0, tk.END); self.ent_mat_search.insert(0, sel_text)
                self.search_res_frame.place_forget()
                clean_name = sel_text.split(" |")[0]
                for mid, mdata in self.stock_map.items():
                    if mdata['name'] == clean_name:
                        self.selected_mat_id = mid; break
                self.ent_qty.focus_set()

            self.ent_mat_search.bind("<KeyRelease>", filter_mats)
            self.lb_results.bind("<<ListboxSelect>>", on_select)
            # ENTER DESTREĞİ
            self.lb_results.bind("<Return>", on_select)
            
            self.ent_mat_search.bind("<Down>", lambda e: (self.lb_results.focus_set(), self.lb_results.selection_set(0)) if self.search_res_frame.winfo_ismapped() else None)

            self.ent_qty = ctk.CTkEntry(product_container, placeholder_text="Adet / Miktar", height=40, font=("Segoe UI", 13))
            self.ent_qty.pack(fill="x", pady=10)

            def add_to_cart(event=None):
                if not self.selected_mat_id:
                    txt = self.ent_mat_search.get().split(" |")[0]
                    found = False
                    for mid, mdata in self.stock_map.items():
                        if mdata['name'] == txt: self.selected_mat_id = mid; found = True; break
                    if not found: return messagebox.showwarning("!", "Listeden bir malzeme seçiniz.")

                try: qty = float(self.ent_qty.get().replace(',', '.'))
                except: return messagebox.showwarning("!", "Geçersiz miktar.")
                if qty <= 0: return messagebox.showwarning("!", "Miktar > 0 olmalı.")

                m = self.stock_map[self.selected_mat_id]
                is_ul = m.get('is_unlimited', False)
                
                cur_in_cart = sum([x[2] for x in self.checkout_cart if x[0] == self.selected_mat_id])
                real = m['stock']
                
                if not is_ul and (cur_in_cart + qty) > real:
                    return messagebox.showerror("Stok Yetersiz", f"Stok: {real:g}\nSepette: {cur_in_cart:g}")

                self.checkout_cart.append((self.selected_mat_id, m['name'], qty, m['unit']))
                
                refresh_cart_table()
                self.ent_qty.delete(0, 'end'); self.ent_mat_search.delete(0, 'end')
                self.selected_mat_id = None; self.ent_mat_search.focus_set()

            self.ent_qty.bind("<Return>", add_to_cart)
            
            ctk.CTkButton(left_card, text="⬇️ LİSTEYE EKLE", command=add_to_cart, fg_color="#2980b9", hover_color="#21618c", height=40, font=("Segoe UI", 13, "bold"), corner_radius=10).pack(fill="x", padx=20, pady=10)

            # Header
            header_frame = ctk.CTkFrame(right_card, height=50, fg_color="transparent")
            header_frame.pack(side="top", fill="x", padx=20, pady=15)
            ctk.CTkLabel(header_frame, text="🛒 ÇIKIŞ LİSTESİ", font=("Segoe UI", 18, "bold")).pack(side="left")
            self.lbl_count = ctk.CTkLabel(header_frame, text="0 Kalem", font=("Segoe UI", 12), text_color="gray")
            self.lbl_count.pack(side="right", padx=10)

            # Tree
            tree_container = ctk.CTkFrame(right_card, fg_color="transparent")
            tree_container.pack(side="top", fill="both", expand=True, padx=20, pady=(0, 10))
            
            cart_tree = self.setup_treeview(tree_container, ("ID", "Malzeme Adı", "Miktar", "Birim"))
            cart_tree.column("ID", width=0, stretch=False)
            cart_tree.column("Malzeme Adı", width=200, stretch=True, anchor="w")
            cart_tree.column("Miktar", width=100, stretch=False, anchor="center")
            cart_tree.column("Birim", width=100, stretch=False, anchor="center")

            # --- BUTONLARI ALT KISMA TASIDIK ---
            action_area = ctk.CTkFrame(right_card, height=100, fg_color="transparent")
            action_area.pack(side="bottom", fill="x", padx=20, pady=(0, 15))
            
            # Alt satir (Kaydet butonlari)
            bottom_row = ctk.CTkFrame(action_area, fg_color="transparent")
            bottom_row.pack(side="bottom", fill="x", pady=5)
            
            # Ust satir (Silme butonlari)
            top_row = ctk.CTkFrame(action_area, fg_color="transparent")
            top_row.pack(side="bottom", fill="x", pady=5)

            def remove_selected():
                sel = cart_tree.selection()
                if not sel: return
                del self.checkout_cart[cart_tree.index(sel[0])]
                refresh_cart_table()

            def clear_cart():
                if not self.checkout_cart: return
                if ask_yesno_optout(self, "Onay", "Tüm liste temizlensin mi?", "opt_clear_cart_confirm", self.db):
                    self.checkout_cart = []
                    refresh_cart_table()

            ctk.CTkButton(top_row, text="SEÇİLİ SİL", command=remove_selected, fg_color="#c0392b", hover_color="#922b21", width=120, height=35).pack(side="left", padx=(0, 5))
            ctk.CTkButton(top_row, text="TEMİZLE", command=clear_cart, fg_color="#7f8c8d", hover_color="#626567", width=120, height=35).pack(side="left", padx=5)
            
            def preview_pdf():
                if not self.checkout_cart: return messagebox.showwarning("!", "Liste boş.")
                is_team = (seg.get() == "Birim")
                rcv = self.cb_team.get() if is_team else self.ent_person.get()
                if not rcv: rcv = "ONIZLEME"
                try:
                    pdf_items = [(item[1], item[2], item[3]) for item in self.checkout_cart]
                    d_val = self.ent_date.get()
                    t_label = seg.get() if is_team else "Personel"
                    pdf_path = PDFGenerator.create_custody_report(rcv, t_label, pdf_items, d_val)
                    os.startfile(pdf_path)
                except Exception as e: messagebox.showerror("Hata", str(e))

            ctk.CTkButton(top_row, text="TASLAK PDF", command=preview_pdf, fg_color="#95a5a6", hover_color="#7f8c8d", width=120, height=35).pack(side="right", padx=0)

            def run_checkout(create_pdf=False):
                if not self.checkout_cart: return messagebox.showwarning("!", "Liste boş.")
                is_team = (seg.get() == "Birim")
                rcv = self.cb_team.get() if is_team else self.ent_person.get()
                if not rcv: return messagebox.showwarning("!", "Alıcı seçilmedi.")
                
                if not ask_yesno_optout(self, "Onay", f"Toplam {len(self.checkout_cart)} kalem malzeme\n{rcv} adına çıkış yapılacak.\nStoktan düşülecek.\nOnaylıyor musunuz?", "opt_checkout_confirm", self.db): return

                try:
                    pdf_items = []
                    checkout_data = [(m[0], m[1], m[2], m[3]) for m in self.checkout_cart] # (id, name, qty, unit)
                    d_val = self.ent_date.get()

                    def redo_op():
                        with self.db.get_conn() as conn:
                            for mid, mname, mqty, munit in checkout_data:
                                is_ul = self.stock_map[mid].get('is_unlimited', False)
                                if not is_ul:
                                    conn.execute("UPDATE materials SET stock = stock - ? WHERE id=?", (mqty, mid))
                                conn.execute("INSERT INTO transactions (date, type, material_id, receiver, quantity) VALUES (?,?,?,?,?)", (d_val, "ÇIKIŞ", mid, rcv, mqty))
                            conn.commit()

                    def undo_op():
                        with self.db.get_conn() as conn:
                            for mid, mname, mqty, munit in checkout_data:
                                is_ul = self.stock_map[mid].get('is_unlimited', False)
                                if not is_ul:
                                    conn.execute("UPDATE materials SET stock = stock + ? WHERE id=?", (mqty, mid))
                                # Fix: SQLite DELETE with ORDER BY/LIMIT is optional and might not be enabled. Use rowid.
                                # En son eklenen ilgili kaydi bul ve sil
                                last_id = conn.execute("SELECT id FROM transactions WHERE material_id=? AND type='ÇIKIŞ' AND receiver=? ORDER BY id DESC LIMIT 1", (mid, rcv)).fetchone()
                                if last_id:
                                    conn.execute("DELETE FROM transactions WHERE id=?", (last_id[0],))
                            conn.commit()

                    # Islemi yap
                    redo_op()
                    self.push_undo(f"Çıkış: {len(checkout_data)} Kalem - {rcv}", undo_op, redo_op)

                    # PDF Verileri
                    for mid, mname, mqty, munit in checkout_data:
                        pdf_items.append((mname, mqty, munit))

                    msg = "İşlem Başarılı.\nStoklar güncellendi."
                    if create_pdf:
                        try:
                            t_label = seg.get() if is_team else "Personel"
                            pdf_path = PDFGenerator.create_custody_report(rcv, t_label, pdf_items, d_val)
                            os.startfile(pdf_path); msg += "\nTutanak oluşturuldu."
                        except Exception as e: msg += f"\nPDF Hatası: {e}"

                    messagebox.showinfo("Başarılı", msg)
                    self.checkout_cart = []; refresh_cart_table()
                    
                    with self.db.get_conn() as conn:
                        try: mats_raw = conn.execute("SELECT id, name, stock, unit, is_unlimited FROM materials ORDER BY name").fetchall()
                        except: mats_raw = conn.execute("SELECT id, name, stock, unit, 0 FROM materials ORDER BY name").fetchall()
                        
                        self.stock_map = {m[0]: {'name': m[1], 'stock': float(m[2]), 'unit': m[3], 'is_unlimited': (m[4]==1)} for m in mats_raw}
                        m_display.clear()
                        for m in mats_raw:
                            stk_str = "∞" if m[4]==1 else f"{float(m[2]):g}"
                            m_display.append(f"{m[1]} | Stok: {stk_str}")

                except Exception as e: messagebox.showerror("Hata", str(e))

            ctk.CTkButton(bottom_row, text="✅ STOKTAN DÜŞ VE KAYDET", command=lambda: run_checkout(False), fg_color="#27ae60", hover_color="#1e8449", height=40).pack(side="left", fill="x", expand=True, padx=(0, 5))
            ctk.CTkButton(bottom_row, text="💾 KAYDET VE YAZDIR", command=lambda: run_checkout(True), fg_color="#e67e22", hover_color="#d35400", height=40).pack(side="left", fill="x", expand=True, padx=(5, 0))

            def refresh_cart_table():
                for i in cart_tree.get_children(): cart_tree.delete(i)
                for item in self.checkout_cart: cart_tree.insert("", "end", values=item)
                self.lbl_count.configure(text=f"{len(self.checkout_cart)} Kalem")

        except Exception as e: messagebox.showerror("Hata", str(e))

    def open_location_selector(self):
        pop = ctk.CTkToplevel(self)
        pop.title("Depo Lokasyonu Seç")
        
        # Pencereyi ortala
        w, h = 500, 650
        px = self.winfo_x()
        py = self.winfo_y()
        pw = self.winfo_width()
        ph = self.winfo_height()
        
        x = px + (pw // 2) - (w // 2)
        y = py + (ph // 2) - (h // 2)
        pop.geometry(f"{w}x{h}+{x}+{y}")
        
        pop.transient(self)
        pop.attributes("-topmost", True)
        pop.grab_set()
        pop.focus()

        ctk.CTkLabel(pop, text="📍 LOKASYON SEÇİNİZ", font=("Segoe UI", 16, "bold")).pack(pady=10)
        
        # --- ARAMA BÖLÜMÜ ---
        search_frame = ctk.CTkFrame(pop, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        ent_search = ctk.CTkEntry(search_frame, placeholder_text="🔍 Lokasyon Ara...", height=35)
        ent_search.pack(fill="x")

        tree_frame = ctk.CTkFrame(pop, fg_color="#2b2b2b", corner_radius=10)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=10)

        style = ttk.Style()
        style.configure("Selector.Treeview", background="#2b2b2b", foreground="white", fieldbackground="#2b2b2b", rowheight=30, font=("Segoe UI", 11))
        
        tree = ttk.Treeview(tree_frame, selectmode="browse", show="tree", style="Selector.Treeview")
        tree.column("#0", width=400, stretch=True)
        
        scrollbar = ctk.CTkScrollbar(tree_frame, orientation="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        # Veri Yükleme
        all_nodes = []
        with self.db.get_conn() as conn:
            all_nodes = conn.execute("SELECT id, parent_id, level_type, name FROM location_nodes WHERE active=1").fetchall()

        def build_tree(query=""):
            for i in tree.get_children(): tree.delete(i)
            
            nodes_data = {}
            children_map = {}
            q = tr_lower(query)
            
            for r in all_nodes:
                nid, pid, ltype, name = r
                pid = pid or 0
                nodes_data[nid] = r
                if pid not in children_map: children_map[pid] = []
                children_map[pid].append(r)

            def insert_recursive(pid, ui_parent):
                if pid in children_map:
                    for c in children_map[pid]:
                        # Arama filtresi: Eğer query varsa ve isimde geçmiyorsa ve alt dallarda da yoksa ekleme
                        # (Basitlik için sadece isme bakıyoruz, istenirse derin arama eklenebilir)
                        if q and q not in tr_lower(c[3]):
                            # Alt dallarda eşleşme var mı kontrolü
                            has_match_in_descendants = False
                            def check_desc(parent_id):
                                nonlocal has_match_in_descendants
                                if parent_id in children_map:
                                    for child in children_map[parent_id]:
                                        if q in tr_lower(child[3]): 
                                            has_match_in_descendants = True; return
                                        check_desc(child[0])
                            check_desc(c[0])
                            if not has_match_in_descendants: continue

                        icon = "🏢" if c[2]=="KAT" else "🚧" if c[2]=="BOLGE" else "🗄️" if c[2]=="RAF" else "📦"
                        uid = tree.insert(ui_parent, "end", text=f"{icon} {c[3]}", values=(c[0], c[2], c[3]))
                        if q: tree.item(uid, open=True) # Aramada tümünü aç
                        insert_recursive(c[0], uid)

            insert_recursive(0, "")

        build_tree()
        ent_search.bind("<KeyRelease>", lambda e: build_tree(ent_search.get()))

        def confirm_selection():
            sel = tree.selection()
            if not sel: return messagebox.showwarning("!", "Lütfen bir lokasyon seçin.", parent=pop)
            
            item = tree.item(sel[0])
            nid, ntype, nname = item['values']
            
            # Tam yolu bul
            path_parts = [nname]
            curr_item = tree.parent(sel[0])
            while curr_item:
                path_parts.insert(0, tree.item(curr_item)['values'][2])
                curr_item = tree.parent(curr_item)
            
            full_path = " > ".join(path_parts)
            self.selected_node_id = nid
            self.selected_loc_path.set(full_path)
            pop.destroy()

        ctk.CTkButton(pop, text="SEÇ", command=confirm_selection, height=40, fg_color="#27ae60", font=("Segoe UI", 13, "bold")).pack(pady=20, padx=50, fill="x")

    def render_entry(self):
        for widget in self.container.winfo_children(): widget.destroy()

        tabs = ctk.CTkTabview(self.container, anchor="nw", corner_radius=15, height=350)
        tabs.pack(fill="both", expand=True, padx=20, pady=20)
        
        tab_add = tabs.add("Hızlı Stok Ekle")
        tab_new = tabs.add("YENİ MALZEME")

        with self.db.get_conn() as conn:
            mats = [r[0] for r in conn.execute("SELECT name FROM materials ORDER BY name").fetchall()]
        
        # --- TAB 1: HIZLI STOK EKLE ---
        f1 = ctk.CTkFrame(tab_add, fg_color="transparent")
        f1.place(relx=0.5, rely=0.4, anchor="center", relwidth=0.5)

        ctk.CTkLabel(f1, text="HIZLI STOK EKLEME", font=("Segoe UI", 14, "bold"), text_color="gray70").pack(pady=(0,15))
        
        self.cb_add_mat = ctk.CTkComboBox(f1, values=mats, height=28, justify="center", font=("Segoe UI", 11))
        self.cb_add_mat.pack(fill="x", pady=5); self.cb_add_mat.set("Seçiniz...")
        
        self.ent_add_qty = ctk.CTkEntry(f1, placeholder_text="Miktar", height=28, justify="center", font=("Segoe UI", 11))
        self.ent_add_qty.pack(fill="x", pady=5)

        def run_add(event=None):
            try:
                name = self.cb_add_mat.get()
                if name == "Seçiniz..." or not name: return messagebox.showwarning("!", "Seçim yapın.")
                qty = float(self.ent_add_qty.get().replace(',','.'))
                
                def redo_op():
                    with self.db.get_conn() as conn:
                        conn.execute("UPDATE materials SET stock = stock + ? WHERE name=?", (qty, name))
                        mid_res = conn.execute("SELECT id FROM materials WHERE name=?", (name,)).fetchone()
                        if mid_res:
                            # expiry_date kolonuna bos string yaz (Bu ekranda tarih yok)
                            conn.execute("INSERT INTO transactions (date, type, material_id, receiver, quantity, expiry_date) VALUES (?,?,?,?,?,?)", 
                                         (datetime.now().strftime("%d.%m.%Y"), "GİRİŞ", mid_res[0], "DEPO", qty, ""))
                        conn.commit()

                def undo_op():
                    with self.db.get_conn() as conn:
                         mid_res = conn.execute("SELECT id FROM materials WHERE name=?", (name,)).fetchone()
                         if mid_res:
                             conn.execute("UPDATE materials SET stock = stock - ? WHERE id=?", (qty, mid_res[0]))
                             conn.execute("DELETE FROM transactions WHERE material_id=? AND type='GİRİŞ' ORDER BY id DESC LIMIT 1", (mid_res[0],))
                         conn.commit()

                # Islemi ilk kez yap
                redo_op()
                self.push_undo(f"Giriş: {name} ({qty})", undo_op, redo_op)
                messagebox.showinfo("OK", "Stok Eklendi."); self.render_entry()
            except Exception as e: messagebox.showerror("Hata", str(e))

        self.ent_add_qty.bind("<Return>", run_add)
        ctk.CTkButton(f1, text="ONAYLA", command=run_add, height=32, fg_color="#27ae60", font=("Segoe UI", 12, "bold")).pack(pady=15, fill="x")
        # --- TAB 2: YENİ MALZEME ---
        f2 = ctk.CTkFrame(tab_new, fg_color="transparent")
        f2.place(relx=0.5, rely=0.4, anchor="center", relwidth=0.6)
        f2.grid_columnconfigure((0,1), weight=1, uniform="x")

        self.en_new_name = ctk.CTkEntry(f2, placeholder_text="Malzeme Adı", height=28, font=("Segoe UI", 11))
        self.en_new_name.grid(row=0, column=0, columnspan=2, sticky="ew", pady=5, padx=5)
        self.en_new_stock = ctk.CTkEntry(f2, placeholder_text="Açılış Stoğu (0)", height=28, font=("Segoe UI", 11))
        self.en_new_stock.grid(row=1, column=0, sticky="ew", pady=5, padx=5)
        
        with self.db.get_conn() as conn:
            unit_list = [u[0] for u in conn.execute("SELECT name FROM stock_units ORDER BY name").fetchall()]
            if not unit_list: unit_list = ["Adet", "Kg"]

        self.cb_new_unit = ctk.CTkComboBox(f2, values=unit_list, height=28, font=("Segoe UI", 11))
        self.cb_new_unit.grid(row=1, column=1, sticky="ew", pady=5, padx=5); self.cb_new_unit.set(unit_list[0])
        
        self.var_unlimited = tk.IntVar(value=0)
        def toggle_stock_entry():
            if self.var_unlimited.get() == 1:
                self.en_new_stock.delete(0, 'end'); self.en_new_stock.insert(0, "0")
                self.en_new_stock.configure(state="disabled", fg_color="gray20")
            else:
                self.en_new_stock.configure(state="normal", fg_color=("white", "#343638"))
                
        self.chk_unlimited = ctk.CTkCheckBox(f2, text="Sınırsız Stok (Takip Edilmez)", variable=self.var_unlimited, command=toggle_stock_entry, font=("Segoe UI", 11))
        self.chk_unlimited.grid(row=2, column=0, columnspan=2, sticky="w", padx=5, pady=5)

        # MODUL: SKT Checkbox ve Tarih (YAN YANA)
        self.var_expiry = tk.IntVar(value=0)
        self.frame_new_exp_date = ctk.CTkFrame(f2, fg_color="transparent")
        
        def toggle_expiry_date():
            if self.var_expiry.get() == 1:
                self.frame_new_exp_date.grid(row=3, column=1, sticky="w", padx=5, pady=5)
            else:
                self.frame_new_exp_date.grid_forget()

        if "expiry_date" in self.loaded_modules:
            chk_exp = ctk.CTkCheckBox(f2, text="📅 SKT Takibi Yap", variable=self.var_expiry, command=toggle_expiry_date, font=("Segoe UI", 11), fg_color="#e67e22")
            chk_exp.grid(row=3, column=0, sticky="w", padx=5, pady=5)
            
            ctk.CTkLabel(self.frame_new_exp_date, text="SKT Seçiniz:", font=("Segoe UI", 10)).pack(side="left", padx=5)
            if DateEntry:
                self.ent_new_exp_date = DateEntry(self.frame_new_exp_date, date_pattern='dd.mm.yyyy', width=12)
                self.ent_new_exp_date.pack(side="left")
            else:
                self.ent_new_exp_date = ctk.CTkEntry(self.frame_new_exp_date, width=100)
                self.ent_new_exp_date.pack(side="left")
                self.ent_new_exp_date.insert(0, datetime.now().strftime("%d.%m.%Y"))
            
            row_offset = 1 
        else:
            row_offset = 0

        # --- LOKASYON YONETIMI MODULU ---
        self.selected_node_id = None 
        self.selected_loc_path = tk.StringVar(value="Henüz Seçilmedi")
        
        if "location_management" in self.loaded_modules:
            f_loc = ctk.CTkFrame(f2, fg_color="transparent")
            f_loc.grid(row=3+row_offset, column=0, columnspan=2, sticky="ew", pady=10)
            
            ctk.CTkLabel(f_loc, text="📍 Depo Lokasyonu (Açılış Stoğu Varsa):", font=("Bold", 11), text_color="#3498db").grid(row=0, column=0, columnspan=2, sticky="w", padx=5)
            
            # Tek bir gösterge kutusu ve buton - Genişlik optimize edildi
            self.en_loc_display = ctk.CTkEntry(f_loc, textvariable=self.selected_loc_path, state="disabled", height=30, width=250, font=("Segoe UI", 11))
            self.en_loc_display.grid(row=1, column=0, sticky="w", padx=5, pady=5)
            
            ctk.CTkButton(f_loc, text="Lokasyon Seç", command=self.open_location_selector, width=100, height=30, fg_color="#34495e").grid(row=1, column=1, sticky="w", padx=5, pady=5)
                
            row_offset += 1

        self.new_img_path = tk.StringVar(value="")
        lbl_img_status = ctk.CTkLabel(f2, text="Resim Yok", font=("Segoe UI", 10), text_color="gray")
        
        def sel_img():
            p = filedialog.askopenfilename(filetypes=[("Resim", "*.jpg;*.jpeg;*.png")])
            if p: self.new_img_path.set(p); lbl_img_status.configure(text=os.path.basename(p), text_color="#2ecc71")

        ctk.CTkButton(f2, text="📷 Resim Seç", command=sel_img, height=28, fg_color="#8e44ad").grid(row=4+row_offset, column=0, sticky="ew", pady=5, padx=5)
        lbl_img_status.grid(row=4+row_offset, column=1, sticky="w", padx=5)

        def run_new(event=None):
            try:
                n = self.en_new_name.get().strip()
                s = float(self.en_new_stock.get().replace(',','.') or 0)
                u = self.cb_new_unit.get()
                is_ul = self.var_unlimited.get()
                track_exp = self.var_expiry.get()
                
                exp_date_val = ""
                if track_exp == 1 and self.frame_new_exp_date.winfo_ismapped():
                    exp_date_val = self.ent_new_exp_date.get()

                img_src = self.new_img_path.get()
                final_path = None
                if not n: return
                if img_src and os.path.exists(img_src):
                    ext = os.path.splitext(img_src)[1]
                    safe_name = f"{tr_sort(n).replace(' ','_')}_{datetime.now().strftime('%H%M%S')}{ext}"
                    dest = ROOT_DIR / "Urun_Resimleri" / safe_name
                    shutil.copy(img_src, dest)
                    final_path = str(dest)
                
                # Seçilen Node ID üzerinden Location ID bulma (veya yoksa oluşturma)
                final_loc_id = None
                if "location_management" in self.loaded_modules and self.selected_node_id:
                    with self.db.get_conn() as conn:
                        res = conn.execute("SELECT id FROM locations WHERE node_id=?", (self.selected_node_id,)).fetchone()
                        if res:
                            final_loc_id = res[0]
                        else:
                            # Eğer seçilen node bir fiziksel slot olarak tanımlanmamışsa otomatik ekle
                            cur_l = conn.execute("INSERT INTO locations (node_id, capacity) VALUES (?, 999999)", (self.selected_node_id,))
                            final_loc_id = cur_l.lastrowid

                def redo_op():
                    with self.db.get_conn() as conn:
                        cur = conn.execute("INSERT INTO materials (name, stock, unit, track_critical, image_path, is_unlimited, track_expiry) VALUES (?,?,?,1,?,?,?)", (n,s,u,final_path, is_ul, track_exp))
                        mid = cur.lastrowid
                        if s > 0:
                            conn.execute("INSERT INTO transactions (date, type, material_id, receiver, quantity, expiry_date) VALUES (?,?,?,?,?,?)", 
                                         (datetime.now().strftime("%d.%m.%Y"), "GİRİŞ", mid, "DEPO", s, exp_date_val))
                            if "location_management" in self.loaded_modules and final_loc_id:
                                conn.execute("INSERT INTO product_locations (product_id, location_id, quantity, entry_date) VALUES (?,?,?,?)",
                                             (mid, final_loc_id, s, datetime.now().isoformat()))
                                conn.execute("UPDATE locations SET current_load = current_load + ? WHERE id=?", (s, final_loc_id))
                        conn.commit()

                def undo_op():
                    with self.db.get_conn() as conn:
                        conn.execute("DELETE FROM materials WHERE name=? ORDER BY id DESC LIMIT 1", (n,))
                        conn.commit()
                    self.db.reindex_materials()

                redo_op()
                self.push_undo(f"Yeni Malzeme: {n}", undo_op, redo_op)
                messagebox.showinfo("OK", "Oluşturuldu."); self.render_entry()
            except Exception as e: messagebox.showerror("Hata", str(e))

        self.en_new_name.bind("<Return>", run_new)
        self.en_new_stock.bind("<Return>", run_new)
        ctk.CTkButton(f2, text="KAYDET", command=run_new, height=32, fg_color="#2980b9", font=("Segoe UI", 12, "bold")).grid(row=5+row_offset, column=0, columnspan=2, sticky="ew", pady=15, padx=5)

    def render_history(self):
        # Once temizle
        self.hist_tree = None
        
        ctk.CTkLabel(self.container, text="📜 İŞLEM GEÇMİŞİ", font=("Segoe UI", 22, "bold")).pack(pady=(15, 10))

        filter_frame = ctk.CTkFrame(self.container, fg_color="transparent")
        filter_frame.pack(fill="x", padx=10, pady=(0, 10))
        filter_frame.grid_columnconfigure((0, 1, 2, 3, 4), weight=1)

        ctk.CTkLabel(filter_frame, text="Malzeme Adı:", font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w", padx=5)
        self.hist_filter_mat = ctk.CTkEntry(filter_frame, placeholder_text="Ara...", height=28)
        self.hist_filter_mat.grid(row=1, column=0, sticky="ew", padx=5)

        ctk.CTkLabel(filter_frame, text="Alan Kişi / Ekip:", font=("Segoe UI", 11, "bold")).grid(row=0, column=1, sticky="w", padx=5)
        self.hist_filter_rcv = ctk.CTkEntry(filter_frame, placeholder_text="Ara...", height=28)
        self.hist_filter_rcv.grid(row=1, column=1, sticky="ew", padx=5)

        ctk.CTkLabel(filter_frame, text="Tarih:", font=("Segoe UI", 11, "bold")).grid(row=0, column=2, sticky="w", padx=5)
        self.hist_filter_date = ctk.CTkEntry(filter_frame, placeholder_text="gg.aa.yyyy", height=28)
        self.hist_filter_date.grid(row=1, column=2, sticky="ew", padx=5)
        
        ctk.CTkLabel(filter_frame, text="İşlem Tipi:", font=("Segoe UI", 11, "bold")).grid(row=0, column=3, sticky="w", padx=5)
        self.hist_filter_type = ctk.CTkComboBox(filter_frame, values=["Tümü", "GİRİŞ", "ÇIKIŞ", "SATINALMA"], height=28)
        self.hist_filter_type.set("Tümü")
        self.hist_filter_type.grid(row=1, column=3, sticky="ew", padx=5)

        btn_frame = ctk.CTkFrame(filter_frame, fg_color="transparent")
        btn_frame.grid(row=1, column=4, sticky="ew", padx=5)
        ctk.CTkButton(btn_frame, text="FİLTRELE", command=lambda: self.load_history_data(), width=80, height=28, fg_color="#2980b9").pack(side="left", padx=2, fill="x", expand=True)
        ctk.CTkButton(btn_frame, text="TEMİZLE", command=lambda: self.clear_history_filters(), width=80, height=28, fg_color="#7f8c8d").pack(side="left", padx=2, fill="x", expand=True)

        card = ctk.CTkFrame(self.container, corner_radius=15)
        card.pack(fill="both", expand=True)
        
        cols = ("ID", "Tarih", "İşlem", "Malzeme", "Alan/Ekip", "Miktar")
        self.hist_tree = self.setup_treeview(card, cols)
        self.hist_tree.column("ID", width=0, stretch=False); self.hist_tree.heading("ID", text="") 
        self.hist_tree.column("Tarih", width=100, anchor="center")
        self.hist_tree.column("İşlem", width=80, anchor="center")
        self.hist_tree.column("Miktar", width=80, anchor="center")

        self.hist_tree.tag_configure("GİRİŞ", foreground="#2ecc71", font=("Segoe UI", 10, "bold"))
        self.hist_tree.tag_configure("ÇIKIŞ", foreground="#e74c3c", font=("Segoe UI", 10, "bold"))
        self.hist_tree.tag_configure("SATINALMA", foreground="#3498db", font=("Segoe UI", 10, "bold"))

        m = tk.Menu(self.hist_tree, tearoff=0)
        # Lambda icinde self.hist_tree'yi dogrudan kullanmak yerine tree referansi alalim
        m.add_command(label="🗑️ İşlemi Sil ve Geri Al", command=lambda t=self.hist_tree: self.del_log(t))
        
        def do_popup(e):
            row = self.hist_tree.identify_row(e.y)
            if row: self.hist_tree.selection_set(row); m.post(e.x_root, e.y_root)
        self.hist_tree.bind("<Button-3>", do_popup)

        self.hist_filter_mat.bind("<Return>", lambda e: self.load_history_data())
        self.hist_filter_rcv.bind("<Return>", lambda e: self.load_history_data())
        self.hist_filter_date.bind("<Return>", lambda e: self.load_history_data())

        # DUZENLEME POPUP (GECMIS ICIN)
        def edit_history_popup(event):
            try:
                tree = event.widget
                item_id = tree.identify_row(event.y)
                if not item_id: return
                vals = tree.item(item_id)['values']
                tid = vals[0] # ID
            except: return
            
            with self.db.get_conn() as conn:
                try: rec = conn.execute("SELECT t.date, t.description, t.quantity, t.unit_price, t.material_id, m.name, t.expiry_date, t.type FROM transactions t LEFT JOIN materials m ON t.material_id=m.id WHERE t.id=?", (tid,)).fetchone()
                except: rec = conn.execute("SELECT t.date, t.description, t.quantity, t.unit_price, t.material_id, m.name, '', t.type FROM transactions t LEFT JOIN materials m ON t.material_id=m.id WHERE t.id=?", (tid,)).fetchone()
            
            if not rec: return
            
            pop = ctk.CTkToplevel(self)
            pop.title("İşlem Düzenle")
            pop.geometry("400x600")
            pop.attributes("-topmost", True)
            
            ctk.CTkLabel(pop, text="İŞLEM DÜZENLE", font=("Bold", 16)).pack(pady=15)
            ctk.CTkLabel(pop, text=f"Malzeme: {rec[5]}", font=("Bold", 12)).pack(pady=5)
            ctk.CTkLabel(pop, text=f"İşlem Tipi: {rec[7]}", text_color="gray").pack()
            
            ctk.CTkLabel(pop, text="Tarih:").pack(pady=(10,0))
            e_date = ctk.CTkEntry(pop); e_date.pack(); e_date.insert(0, rec[0])
            
            # SKT Duzenleme
            var_has_exp = tk.IntVar(value=0)
            f_exp_edit = ctk.CTkFrame(pop, fg_color="transparent")
            e_exp_date = None
            
            if "expiry_date" in self.loaded_modules and rec[7] in ["GİRİŞ", "SATINALMA"]:
                f_exp_edit.pack(pady=(5,0))
                f_exp_input = ctk.CTkFrame(f_exp_edit, fg_color="transparent")
                
                def toggle_exp_edit():
                    if var_has_exp.get() == 1: f_exp_input.pack(side="left", padx=5)
                    else: f_exp_input.pack_forget()

                ctk.CTkCheckBox(f_exp_edit, text="SKT'li Ürün", variable=var_has_exp, command=toggle_exp_edit, fg_color="#e67e22", width=20).pack(side="left")
                
                if DateEntry:
                    e_exp_date = DateEntry(f_exp_input, date_pattern='dd.mm.yyyy', width=12)
                    e_exp_date.pack()
                else:
                    e_exp_date = ctk.CTkEntry(f_exp_input, width=100)
                    e_exp_date.pack()
                
                if rec[6] and rec[6] != "":
                    var_has_exp.set(1)
                    if DateEntry: e_exp_date.set_date(rec[6])
                    else: e_exp_date.insert(0, rec[6])
                    toggle_exp_edit()
                else:
                    if not DateEntry: e_exp_date.insert(0, datetime.now().strftime("%d.%m.%Y"))

            ctk.CTkLabel(pop, text="Açıklama / Tedarikçi / Alıcı:").pack(pady=(5,0))
            e_desc = ctk.CTkEntry(pop, width=250); e_desc.pack(); e_desc.insert(0, rec[1] if rec[1] else "")
            
            ctk.CTkLabel(pop, text="Miktar:").pack(pady=(5,0))
            e_qty = ctk.CTkEntry(pop); e_qty.pack(); e_qty.insert(0, str(rec[2]))
            
            old_qty = float(rec[2])
            mat_id = rec[4]
            
            def save_edit():
                try:
                    n_date = e_date.get()
                    n_desc = e_desc.get()
                    n_qty = float(e_qty.get().replace(',','.'))
                    
                    n_exp = ""
                    if var_has_exp.get() == 1 and e_exp_date:
                        n_exp = e_exp_date.get()
                    
                    if n_qty <= 0: return messagebox.showwarning("!", "Geçersiz miktar")
                    
                    diff = n_qty - old_qty
                    
                    with self.db.get_conn() as conn:
                        if rec[7] in ["GİRİŞ", "SATINALMA"]:
                            conn.execute("UPDATE materials SET stock = stock + ? WHERE id=?", (diff, mat_id))
                        elif rec[7] == "ÇIKIŞ":
                            conn.execute("UPDATE materials SET stock = stock - ? WHERE id=?", (diff, mat_id))

                        conn.execute("UPDATE transactions SET date=?, description=?, quantity=?, expiry_date=? WHERE id=?", 
                                     (n_date, n_desc, n_qty, n_exp, tid))
                        conn.commit()
                        
                    messagebox.showinfo("Başarılı", "Kayıt güncellendi.")
                    pop.destroy()
                    self.load_history_data()
                except Exception as e: messagebox.showerror("Hata", str(e))
            
            ctk.CTkButton(pop, text="KAYDET", command=save_edit, fg_color="#27ae60").pack(pady=20)

        self.hist_tree.bind("<Double-1>", edit_history_popup)

        self.load_history_data()

    def clear_history_filters(self):
        self.hist_filter_mat.delete(0, 'end')
        self.hist_filter_rcv.delete(0, 'end')
        self.hist_filter_date.delete(0, 'end')
        self.hist_filter_type.set("Tümü")
        self.load_history_data()

    def load_history_data(self):
        for i in self.hist_tree.get_children(): self.hist_tree.delete(i)
        
        f_mat = self.hist_filter_mat.get().strip()
        f_rcv = self.hist_filter_rcv.get().strip()
        f_date = self.hist_filter_date.get().strip()
        f_type = self.hist_filter_type.get()

        query = "SELECT t.id, t.date, t.type, m.name, t.receiver, t.quantity FROM transactions t LEFT JOIN materials m ON t.material_id=m.id WHERE 1=1"
        params = []

        if f_mat:
            query += " AND TR_LOWER(m.name) LIKE TR_LOWER(?)"
            params.append(f"%{f_mat}%")
        if f_rcv:
            query += " AND TR_LOWER(t.receiver) LIKE TR_LOWER(?)"
            params.append(f"%{f_rcv}%")
        if f_date:
            query += " AND t.date LIKE ?"
            params.append(f"%{f_date}%")
        if f_type and f_type != "Tümü":
            query += " AND t.type = ?"
            params.append(f_type)
            
        query += " ORDER BY t.id DESC"

        with self.db.get_conn() as conn:
            logs = conn.execute(query, params).fetchall()
            for l in logs: self.hist_tree.insert("", "end", values=l, tags=(l[2],))

    def del_log(self, tree):
        if not tree.selection(): return
        item = tree.item(tree.selection()[0])['values']
        
        if not ask_yesno_optout(self, "Onay", f"Seçilen işlem silinecek ve stok güncellenecektir.\nİşlem: {item[3]} ({item[2]})\nMiktar: {item[5]}\n\nOnaylıyor musunuz?", "opt_hist_del", self.db): return
        
        try:
            with self.db.get_conn() as conn:
                mid_res = conn.execute("SELECT material_id FROM transactions WHERE id=?", (item[0],)).fetchone()
                if not mid_res: return
                mid = mid_res[0]
                if str(item[2]) == "GİRİŞ": conn.execute("UPDATE materials SET stock = stock - ? WHERE id=?", (float(item[5]), mid))
                else: conn.execute("UPDATE materials SET stock = stock + ? WHERE id=?", (float(item[5]), mid))
                conn.execute("DELETE FROM transactions WHERE id=?", (item[0],)); conn.commit()
            messagebox.showinfo("Başarılı", "İşlem silindi."); self.render_history()
        except Exception as e: messagebox.showerror("Hata", str(e))

    def render_report(self):
        try:
            # Lazy Import
            import pandas as pd
        except ImportError:
            messagebox.showerror("Hata", "Pandas kütüphanesi eksik.")
            return

        for widget in self.container.winfo_children(): widget.destroy()

        top_panel = ctk.CTkFrame(self.container, fg_color="#2c3e50", corner_radius=10)
        top_panel.pack(side="top", fill="x", pady=(0, 10), ipady=10)
        
        ctk.CTkLabel(top_panel, text="TARİH ARALIKLI RAPOR", font=("Segoe UI", 18, "bold"), text_color="white").pack(pady=5)
        filter_box = ctk.CTkFrame(top_panel, fg_color="transparent")
        filter_box.pack()

        ctk.CTkLabel(filter_box, text="Başlangıç:", text_color="white").pack(side="left", padx=5)
        
        if DateEntry is not None:
            style_args = {'width': 12, 'background': '#3498db', 'foreground': 'white', 'borderwidth': 2, 'date_pattern': 'dd.mm.yyyy'}
            ent_start = DateEntry(filter_box, **style_args)
            ent_start.pack(side="left", padx=5)
            
            ctk.CTkLabel(filter_box, text="Bitiş:", text_color="white").pack(side="left", padx=5)
            ent_end = DateEntry(filter_box, **style_args)
            ent_end.pack(side="left", padx=5)
        else:
            ent_start = ctk.CTkEntry(filter_box, width=100)
            ent_start.insert(0, "01.01.2025")
            ent_start.pack(side="left", padx=5)
            
            ctk.CTkLabel(filter_box, text="Bitiş:", text_color="white").pack(side="left", padx=5)
            ent_end = ctk.CTkEntry(filter_box, width=100)
            ent_end.insert(0, datetime.now().strftime("%d.%m.%Y"))
            ent_end.pack(side="left", padx=5)

        self.report_data = []

        summary_frame = ctk.CTkFrame(self.container, height=40, fg_color="#27ae60")
        summary_frame.pack(side="bottom", fill="x", pady=(0, 10))
        lbl_summary = ctk.CTkLabel(summary_frame, text="Özet: -", font=("Segoe UI", 14, "bold"), text_color="white")
        lbl_summary.pack(pady=5)

        tree_frame = ctk.CTkFrame(self.container)
        tree_frame.pack(side="top", fill="both", expand=True)
        cols = ("Tarih", "Tür", "Malzeme", "Alıcı/Ekip", "Miktar", "Birim")
        tree = self.setup_treeview(tree_frame, cols)

        def run_filter():
            try:
                d_start = datetime.strptime(ent_start.get(), "%d.%m.%Y")
                d_end = datetime.strptime(ent_end.get(), "%d.%m.%Y")
                d_end = d_end.replace(hour=23, minute=59, second=59)

                for i in tree.get_children(): tree.delete(i)
                self.report_data = []
                total_qty = 0; count = 0

                with self.db.get_conn() as conn:
                    raw = conn.execute("SELECT t.date, t.type, m.name, t.receiver, t.quantity, m.unit FROM transactions t LEFT JOIN materials m ON t.material_id=m.id").fetchall()
                    for r in raw:
                        try:
                            r_date = datetime.strptime(r[0], "%d.%m.%Y")
                            if d_start <= r_date <= d_end:
                                tree.insert("", "end", values=r)
                                self.report_data.append(r)
                                if r[1] == "ÇIKIŞ": total_qty += float(r[4])
                                count += 1
                        except: pass
                lbl_summary.configure(text=f"RAPOR ÖZETİ: {count} İşlem | Toplam Çıkış: {total_qty:g}")
            except Exception as e: messagebox.showerror("Hata", f"Tarih hatası: {e}")

        def export_excel():
            if not self.report_data: return messagebox.showwarning("!", "Liste boş.")
            try:
                df = pd.DataFrame(self.report_data, columns=["Tarih", "Tür", "Malzeme", "Alıcı", "Miktar", "Birim"])
                s_date = ent_start.get().replace('.', '')
                e_date = ent_end.get().replace('.', '')
                fname = f"Rapor_Aralik_{s_date}_{e_date}.xlsx"
                path = REPORT_DIR / fname
                df.to_excel(path, index=False)
                messagebox.showinfo("Başarılı", f"Kaydedildi:\n{path}")
                os.startfile(path)
            except Exception as e: messagebox.showerror("Hata", str(e))

        ctk.CTkButton(top_panel, text="LİSTELE / FİLTRELE", command=run_filter, fg_color="#e67e22", width=200).pack(pady=(10, 5))
        btn_box_top = ctk.CTkFrame(top_panel, fg_color="transparent")
        btn_box_top.pack(pady=5)
        ctk.CTkButton(btn_box_top, text="EXCEL (SEÇİLİ)", command=export_excel, fg_color="#2980b9", width=140).pack(side="left", padx=5)
        ctk.CTkButton(btn_box_top, text="EXCEL (TÜMÜ)", command=self.export_action, fg_color="#27ae60", width=140).pack(side="left", padx=5)
        run_filter()

    def render_purchase(self):
        for widget in self.container.winfo_children(): widget.destroy()

        tabs = ctk.CTkTabview(self.container, anchor="nw", corner_radius=15)
        tabs.pack(fill="both", expand=True, padx=20, pady=20)
        
        tab_buy = tabs.add("YENİ SATINALMA")
        tab_pending = tabs.add("ONAY BEKLEYENLER")
        tab_sup = tabs.add("TEDARİKÇİ YÖNETİMİ")
        tab_hist = tabs.add("SATINALMA GEÇMİŞİ")

        # --- TAB 1: YENİ SATINALMA ---
        f_buy = ctk.CTkFrame(tab_buy, fg_color="transparent")
        f_buy.place(relx=0.5, rely=0.4, anchor="center")

        ctk.CTkLabel(f_buy, text="FATURA / SATINALMA GİRİŞİ", font=("Segoe UI", 18, "bold")).grid(row=0, column=0, columnspan=2, pady=(0, 20))

        # Tarih
        ctk.CTkLabel(f_buy, text="Tarih:").grid(row=1, column=0, sticky="e", padx=10, pady=5)
        if DateEntry:
            ent_date = DateEntry(f_buy, date_pattern='dd.mm.yyyy', width=20)
            ent_date.grid(row=1, column=1, sticky="w", padx=10, pady=5)
        else:
            ent_date = ctk.CTkEntry(f_buy, width=150)
            ent_date.grid(row=1, column=1, sticky="w", padx=10, pady=5)
            ent_date.insert(0, datetime.now().strftime("%d.%m.%Y"))

        # Tedarikçi Seçimi
        ctk.CTkLabel(f_buy, text="Tedarikçi:").grid(row=2, column=0, sticky="e", padx=10, pady=5)
        cb_sup = ctk.CTkComboBox(f_buy, values=[], width=200)
        cb_sup.grid(row=2, column=1, sticky="w", padx=10, pady=5)
        
        def refresh_suppliers_cb():
            with self.db.get_conn() as conn:
                sups = [r[0] for r in conn.execute("SELECT name FROM suppliers ORDER BY name").fetchall()]
                cb_sup.configure(values=sups)
                if sups: cb_sup.set(sups[0])
                else: cb_sup.set("Tanımsız")
        refresh_suppliers_cb()

        # Malzeme Seçimi
        ctk.CTkLabel(f_buy, text="Malzeme:").grid(row=3, column=0, sticky="e", padx=10, pady=5)
        with self.db.get_conn() as conn:
            mats = [r[0] for r in conn.execute("SELECT name FROM materials ORDER BY name").fetchall()]
        
        cb_mat = ctk.CTkComboBox(f_buy, values=mats, width=200)
        cb_mat.grid(row=3, column=1, sticky="w", padx=10, pady=5); cb_mat.set("Seçiniz...")

        # Miktar ve Fiyat
        ctk.CTkLabel(f_buy, text="Miktar:").grid(row=4, column=0, sticky="e", padx=10, pady=5)
        ent_qty = ctk.CTkEntry(f_buy, width=100); ent_qty.grid(row=4, column=1, sticky="w", padx=10, pady=5)
        
        ctk.CTkLabel(f_buy, text="Birim Fiyat (TL):").grid(row=5, column=0, sticky="e", padx=10, pady=5)
        ent_price = ctk.CTkEntry(f_buy, width=100); ent_price.grid(row=5, column=1, sticky="w", padx=10, pady=5)

        # Toplam Tutar Label
        lbl_total = ctk.CTkLabel(f_buy, text="Toplam: 0.00 TL", font=("Bold", 14), text_color="#27ae60")
        lbl_total.grid(row=6, column=0, columnspan=2, pady=10)

        # MODUL: SKT Checkbox
        var_pur_expiry = tk.IntVar(value=0)
        f_pur_exp_wrapper = ctk.CTkFrame(f_buy, fg_color="transparent")
        ent_pur_exp = None
        
        if "expiry_date" in self.loaded_modules:
            def toggle_pur_exp():
                if var_pur_expiry.get() == 1:
                    f_pur_exp_wrapper.grid(row=7, column=1, sticky="w", padx=10, pady=5)
                else:
                    f_pur_exp_wrapper.grid_forget()

            chk_pur_exp = ctk.CTkCheckBox(f_buy, text="SKT Takibi Yap", variable=var_pur_expiry, command=toggle_pur_exp, fg_color="#e67e22")
            chk_pur_exp.grid(row=7, column=0, sticky="e", padx=10, pady=5)
            
            # Tarih Alani (Gizli/Acik)
            ctk.CTkLabel(f_pur_exp_wrapper, text="SKT:", font=("Segoe UI", 11)).pack(side="left", padx=5)
            if DateEntry:
                ent_pur_exp = DateEntry(f_pur_exp_wrapper, date_pattern='dd.mm.yyyy', width=12)
                ent_pur_exp.pack(side="left")
            else:
                ent_pur_exp = ctk.CTkEntry(f_pur_exp_wrapper, width=100)
                ent_pur_exp.pack(side="left")
                ent_pur_exp.insert(0, datetime.now().strftime("%d.%m.%Y"))
            
            row_btn_offset = 1
        else:
            row_btn_offset = 0

        def calc_total(*a):
            try:
                q = float(ent_qty.get().replace(',','.') or 0)
                p = float(ent_price.get().replace(',','.') or 0)
                lbl_total.configure(text=f"Toplam: {q*p:,.2f} TL")
            except: lbl_total.configure(text="Toplam: 0.00 TL")
        
        ent_qty.bind("<KeyRelease>", calc_total)
        ent_price.bind("<KeyRelease>", calc_total)

        def save_purchase():
            try:
                s_name = cb_sup.get()
                m_name = cb_mat.get()
                qty = float(ent_qty.get().replace(',', '.'))
                price = float(ent_price.get().replace(',', '.'))
                d_str = ent_date.get()
                
                # SKT Degeri
                exp_date_val = ""
                if var_pur_expiry.get() == 1 and ent_pur_exp:
                    exp_date_val = ent_pur_exp.get()
                
                if m_name == "Seçiniz..." or not m_name: return messagebox.showwarning("!", "Malzeme seçin.")
                if qty <= 0: return messagebox.showwarning("!", "Miktar girin.")

                if not ask_yesno_optout(self, "Onay", f"Toplam {qty*price:,.2f} TL tutarındaki satın alma işlemini onaylıyor musunuz?", "opt_purchase_create", self.db): return
                
                with self.db.get_conn() as conn:
                    # Malzeme ID bul
                    mid = conn.execute("SELECT id FROM materials WHERE name=?", (m_name,)).fetchone()[0]
                    # Transaction Ekle (status='PENDING', Receiver=DEPO, Desc=Tedarikci)
                    # STOK HENUZ GUNCELLEMIYORUZ!
                    conn.execute("INSERT INTO transactions (date, type, material_id, receiver, quantity, unit_price, description, status, expiry_date) VALUES (?,?,?,?,?,?,?,?,?)", 
                                 (d_str, "SATINALMA", mid, "DEPO", qty, price, s_name, "PENDING", exp_date_val))
                    conn.commit()
                    
                show_info_optout(self, "Bilgi", "Satınalma talebi oluşturuldu.\n'ONAY BEKLEYENLER' sekmesinden onaylayınız.", "opt_purchase_info", self.db)
                ent_qty.delete(0, 'end'); ent_price.delete(0, 'end'); calc_total()
                load_pending() # Bekleyenleri yenile
            except Exception as e: messagebox.showerror("Hata", str(e))

        ctk.CTkButton(f_buy, text="TALEP OLUŞTUR", command=save_purchase, fg_color="#2980b9", width=200).grid(row=7+row_btn_offset, column=0, columnspan=2, pady=20)


        # --- TAB 2: ONAY BEKLEYENLER ---
        f_pending = ctk.CTkFrame(tab_pending, fg_color="transparent")
        f_pending.pack(fill="both", expand=True)
        
        # Baslik
        ctk.CTkLabel(f_pending, text="ONAY BEKLEYEN SATINALMA İŞLEMLERİ", font=("Bold", 14), text_color="orange").pack(pady=10)

        pen_tree = self.setup_treeview(f_pending, ("ID", "Tarih", "Tedarikçi", "Malzeme", "Miktar", "Birim Fiyat", "Toplam"))
        pen_tree.column("ID", width=0, stretch=False)
        pen_tree.column("Tarih", width=90, anchor="center")
        pen_tree.column("Tedarikçi", width=150, anchor="w")
        pen_tree.column("Malzeme", width=150, anchor="w")
        pen_tree.column("Miktar", width=80, anchor="center")
        pen_tree.column("Birim Fiyat", width=90, anchor="e")
        pen_tree.column("Toplam", width=100, anchor="e")
        
        def load_pending():
            for i in pen_tree.get_children(): pen_tree.delete(i)
            with self.db.get_conn() as conn:
                rows = conn.execute("""
                    SELECT t.id, t.date, t.description, m.name, t.quantity, t.unit_price, (t.quantity * t.unit_price) 
                    FROM transactions t 
                    LEFT JOIN materials m ON t.material_id = m.id 
                    WHERE t.type='SATINALMA' AND t.status='PENDING'
                    ORDER BY t.id DESC
                """).fetchall()
                for r in rows:
                    try: up = f"{float(r[5]):.2f} ₺"; tp = f"{float(r[6]):.2f} ₺"
                    except: up=r[5]; tp=r[6]
                    pen_tree.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], up, tp))
        
        def approve_selected():
            sel = pen_tree.selection()
            if not sel: return
            vals = pen_tree.item(sel[0])['values']
            tid = vals[0]
            
            if not ask_yesno_optout(self, "Onay", "İşlem onaylansın ve stok güncellensin mi?", "opt_pending_approve", self.db): return
            
            try:
                with self.db.get_conn() as conn:
                    # Islem detayini al (Miktar ve Malzeme ID ve Birim Fiyat)
                    rec = conn.execute("SELECT material_id, quantity, unit_price, description FROM transactions WHERE id=?", (tid,)).fetchone()
                    if not rec: return
                    mid, qty, price, desc = rec[0], rec[1], rec[2], rec[3]
                    
                    # Mevcut stogu ve maliyeti al (ESKI DEGERLER)
                    mat = conn.execute("SELECT stock, average_cost, name FROM materials WHERE id=?", (mid,)).fetchone()
                    cur_stock = mat[0] if mat[0] else 0
                    cur_avg = mat[1] if mat[1] else 0
                    m_name = mat[2]
                    
                    # Agirlikli Ortalama Maliyet Hesabi
                    total_val = (cur_stock * cur_avg) + (qty * price)
                    new_total_stock = cur_stock + qty
                    
                    if new_total_stock > 0:
                        new_avg = total_val / new_total_stock
                    else:
                        new_avg = price # Stok sifirsa veya eksi ise son fiyati baz al
                    
                    # 1. Stogu ve maliyeti guncelle
                    conn.execute("UPDATE materials SET stock = ?, average_cost = ? WHERE id=?", (new_total_stock, new_avg, mid))
                    # 2. Durumu 'APPROVED' yap
                    conn.execute("UPDATE transactions SET status='APPROVED' WHERE id=?", (tid,))
                    conn.commit()
                
                # UNDO (ONAY GERI ALMA)
                def undo_approve():
                    with self.db.get_conn() as conn:
                        # Eski stok ve maliyeti geri yukle
                        conn.execute("UPDATE materials SET stock = ?, average_cost = ? WHERE id=?", (cur_stock, cur_avg, mid))
                        # Islemi tekrar PENDING yap
                        conn.execute("UPDATE transactions SET status='PENDING' WHERE id=?", (tid,))
                        conn.commit()
                
                self.undo_stack.append((f"Onay: {desc} - {m_name}", undo_approve))

                load_pending(); load_purchases()
                show_info_optout(self, "Başarılı", "Onaylandı.", "opt_approve_success", self.db)
            except Exception as e: messagebox.showerror("Hata", str(e))

        def reject_selected():
            sel = pen_tree.selection()
            if not sel: return
            vals = pen_tree.item(sel[0])['values']
            tid = vals[0]
            
            if not ask_yesno_optout(self, "Red", "İşlem reddedilsin ve silinsin mi?", "opt_pending_reject", self.db): return
            
            try:
                with self.db.get_conn() as conn:
                    conn.execute("DELETE FROM transactions WHERE id=?", (tid,))
                    conn.commit()
                load_pending()
                show_info_optout(self, "Bilgi", "İşlem silindi.", "opt_reject_success", self.db)
            except Exception as e: messagebox.showerror("Hata", str(e))

        btn_box = ctk.CTkFrame(f_pending, fg_color="transparent")
        btn_box.pack(pady=10, fill="x")
        
        # Tik ve X butonlari
        ctk.CTkButton(btn_box, text="✔", command=approve_selected, fg_color="#27ae60", width=60, height=40, font=("Arial", 20, "bold")).pack(side="right", padx=10)
        ctk.CTkButton(btn_box, text="❌", command=reject_selected, fg_color="#c0392b", width=60, height=40, font=("Arial", 20, "bold")).pack(side="right", padx=10)
        
        load_pending()


        # --- TAB 3: TEDARİKÇİ YÖNETİMİ ---
        f_sup = ctk.CTkFrame(tab_sup, fg_color="transparent")
        f_sup.pack(fill="both", expand=True, padx=20, pady=20)
        
        f_sup_add = ctk.CTkFrame(f_sup, fg_color="transparent")
        f_sup_add.pack(fill="x", pady=(0, 10))
        
        en_s_name = ctk.CTkEntry(f_sup_add, placeholder_text="Firma Adı", width=180); en_s_name.pack(side="left", padx=5)
        en_s_phone = ctk.CTkEntry(f_sup_add, placeholder_text="Telefon", width=120); en_s_phone.pack(side="left", padx=5)
        en_s_email = ctk.CTkEntry(f_sup_add, placeholder_text="E-Posta", width=180); en_s_email.pack(side="left", padx=5)
        en_s_info = ctk.CTkEntry(f_sup_add, placeholder_text="Not/Adres", width=180); en_s_info.pack(side="left", padx=5)
        
        def add_supplier():
            name = en_s_name.get()
            phone = en_s_phone.get()
            email = en_s_email.get()
            info = en_s_info.get()
            if not name: return
            
            with self.db.get_conn() as conn:
                cur = conn.execute("INSERT INTO suppliers (name, phone, info, email, rating) VALUES (?,?,?,?,0)", (name, phone, info, email))
                sid = cur.lastrowid
                conn.commit()
            
            def undo_add():
                with self.db.get_conn() as conn:
                    conn.execute("DELETE FROM suppliers WHERE id=?", (sid,))
                    conn.commit()
            self.push_undo(f"Tedarikçi Eklendi: {name}", undo_add, add_supplier)

            en_s_name.delete(0, 'end'); en_s_phone.delete(0, 'end'); en_s_email.delete(0, 'end'); en_s_info.delete(0, 'end')
            self.db.reindex_suppliers()
            load_suppliers(); refresh_suppliers_cb()

        ctk.CTkButton(f_sup_add, text="EKLE", command=add_supplier, width=80, fg_color="#27ae60").pack(side="left", padx=5)

        # MODUL KONTROLU
        is_quality_mod_active = "supplier_quality" in self.loaded_modules

        if is_quality_mod_active:
            # --- MODUL AKTIF: PUANLI/GRADYANLI OZEL LISTE ---
            header_frame = ctk.CTkFrame(f_sup, fg_color="#34495e", height=35, corner_radius=5)
            header_frame.pack(fill="x", pady=(10, 0))
            header_frame.pack_propagate(False)
            
            W_NAME, W_PHONE, W_EMAIL, W_INFO, W_ACTION = 160, 110, 160, 160, 60
            ctk.CTkLabel(header_frame, text="Firma Adı", font=("Bold", 12), text_color="white", width=W_NAME, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(header_frame, text="Telefon", font=("Bold", 12), text_color="white", width=W_PHONE, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(header_frame, text="E-Posta", font=("Bold", 12), text_color="white", width=W_EMAIL, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(header_frame, text="Bilgi", font=("Bold", 12), text_color="white", width=W_INFO, anchor="w").pack(side="left", padx=5)
            ctk.CTkLabel(header_frame, text="Kalite / Puan", font=("Bold", 12), text_color="white", anchor="center").pack(side="left", padx=5, fill="x", expand=True)
            ctk.CTkLabel(header_frame, text="İşlemler", font=("Bold", 12), text_color="white", width=W_ACTION, anchor="e").pack(side="right", padx=10)

            sup_scroll = ctk.CTkScrollableFrame(f_sup, fg_color="transparent")
            sup_scroll.pack(fill="both", expand=True, pady=(5, 0))

            def get_rating_color(val):
                if val <= 5:
                    ratio = val / 5.0
                    r, g, b = int(231+(241-231)*ratio), int(76+(196-76)*ratio), int(60+(15-60)*ratio)
                else:
                    ratio = (val-5) / 5.0
                    r, g, b = int(241+(39-241)*ratio), int(196+(174-196)*ratio), int(15+(96-15)*ratio)
                return f"#{r:02x}{g:02x}{b:02x}"

            def update_rating(sid, new_val):
                v = max(0, min(10, new_val))
                with self.db.get_conn() as conn:
                    conn.execute("UPDATE suppliers SET rating=? WHERE id=?", (v, sid))
                    conn.commit()
                load_suppliers()

            def del_sup_mod(sid, name):
                if not ask_yesno_optout(self, "Sil", f"{name} silinsin mi?", "opt_sup_delete", self.db): return
                with self.db.get_conn() as conn:
                    conn.execute("DELETE FROM suppliers WHERE id=?", (sid,))
                    conn.commit()
                self.db.reindex_suppliers(); load_suppliers(); refresh_suppliers_cb()

            def load_suppliers():
                for w in sup_scroll.winfo_children(): w.destroy()
                with self.db.get_conn() as conn:
                    rows = conn.execute("SELECT id, name, phone, email, info, rating FROM suppliers ORDER BY id ASC").fetchall()
                for r in rows:
                    sid, name, phone, email, info, rating = r
                    rating = rating if rating is not None else 0
                    row = ctk.CTkFrame(sup_scroll, height=45, fg_color=("gray95", "#252525"))
                    row.pack(fill="x", pady=2); row.pack_propagate(False)
                    ctk.CTkLabel(row, text=name, width=W_NAME, anchor="w", font=("Segoe UI", 12, "bold")).pack(side="left", padx=5)
                    ctk.CTkLabel(row, text=phone, width=W_PHONE, anchor="w", font=("Segoe UI", 11)).pack(side="left", padx=5)
                    ctk.CTkLabel(row, text=email, width=W_EMAIL, anchor="w", font=("Segoe UI", 11)).pack(side="left", padx=5)
                    ctk.CTkLabel(row, text=info, width=W_INFO, anchor="w", font=("Segoe UI", 11), text_color="gray").pack(side="left", padx=5)
                    
                    rw = ctk.CTkFrame(row, fg_color="transparent")
                    rw.pack(side="left", fill="x", expand=True, padx=5)
                    ri = ctk.CTkFrame(rw, fg_color="transparent"); ri.pack(anchor="center")
                    ctk.CTkButton(ri, text="-", width=24, height=20, fg_color="#7f8c8d", command=lambda s=sid, v=rating: update_rating(s, v-1)).pack(side="left", padx=2)
                    bf = ctk.CTkFrame(ri, fg_color="transparent"); bf.pack(side="left", padx=5)
                    ac = get_rating_color(rating)
                    for i in range(1, 11):
                        bg = ac if i <= rating else ("#dcdcdc" if ctk.get_appearance_mode()=="Light" else "#404040")
                        ctk.CTkFrame(bf, width=10, height=14, fg_color=bg, corner_radius=2).pack(side="left", padx=1)
                    ctk.CTkButton(ri, text="+", width=24, height=20, fg_color="#7f8c8d", command=lambda s=sid, v=rating: update_rating(s, v+1)).pack(side="left", padx=2)
                    ctk.CTkButton(row, text="SİL", width=W_ACTION, height=24, fg_color="#c0392b", font=("Bold", 10), command=lambda s=sid, n=name: del_sup_mod(s, n)).pack(side="right", padx=10)
        else:
            # --- MODUL PASIF: STANDART TREEVIEW (TAM GENISLIK) ---
            sup_tree = self.setup_treeview(f_sup, ("ID", "Firma Adı", "Telefon", "E-Posta", "Bilgi"))
            sup_tree.column("ID", width=40, stretch=False)
            sup_tree.column("Firma Adı", width=200)
            sup_tree.column("Telefon", width=120)
            sup_tree.column("E-Posta", width=180)
            sup_tree.column("Bilgi", width=300)

            def load_suppliers():
                for i in sup_tree.get_children(): sup_tree.delete(i)
                with self.db.get_conn() as conn:
                    for r in conn.execute("SELECT id, name, phone, email, info FROM suppliers ORDER BY id ASC").fetchall():
                        sup_tree.insert("", "end", values=r)
            
            def del_supplier():
                sel = sup_tree.selection()
                if not sel: return
                vals = sup_tree.item(sel[0])['values']
                if not ask_yesno_optout(self, "Sil", f"{vals[1]} silinsin mi?", "opt_sup_delete", self.db): return
                with self.db.get_conn() as conn:
                    conn.execute("DELETE FROM suppliers WHERE id=?", (vals[0],))
                    conn.commit()
                self.db.reindex_suppliers(); load_suppliers(); refresh_suppliers_cb()
            
            ctk.CTkButton(f_sup_add, text="Seçili Tedarikçiyi Sil", command=del_supplier, width=140, fg_color="#c0392b").pack(side="left", padx=5)

        load_suppliers()
                # --- TAB 4: GEÇMİŞ ---
        f_hist = ctk.CTkFrame(tab_hist, fg_color="transparent")
        f_hist.pack(fill="both", expand=True)

        # Filtreleme Alani
        f_filter = ctk.CTkFrame(f_hist, fg_color="transparent")
        f_filter.pack(fill="x", padx=5, pady=(0, 10))

        ctk.CTkLabel(f_filter, text="Tedarikçi:", font=("Bold", 11)).pack(side="left", padx=2)
        ent_search_sup = ctk.CTkEntry(f_filter, width=120, placeholder_text="Ara..."); ent_search_sup.pack(side="left", padx=5)

        ctk.CTkLabel(f_filter, text="Malzeme:", font=("Bold", 11)).pack(side="left", padx=2)
        ent_search_mat = ctk.CTkEntry(f_filter, width=120, placeholder_text="Ara..."); ent_search_mat.pack(side="left", padx=5)
        
        ctk.CTkLabel(f_filter, text="Tarih:", font=("Bold", 11)).pack(side="left", padx=2)
        ent_search_date = ctk.CTkEntry(f_filter, width=90, placeholder_text="gg.aa.yyyy"); ent_search_date.pack(side="left", padx=5)
        
        hist_tree = self.setup_treeview(f_hist, ("ID", "Tarih", "Tedarikçi", "Malzeme", "Miktar", "Birim Fiyat", "Toplam"))
        hist_tree.column("ID", width=0, stretch=False)
        hist_tree.column("Tarih", width=90, anchor="center")
        hist_tree.column("Tedarikçi", width=150, anchor="w")
        hist_tree.column("Malzeme", width=150, anchor="w")
        hist_tree.column("Miktar", width=80, anchor="center")
        hist_tree.column("Birim Fiyat", width=90, anchor="e")
        hist_tree.column("Toplam", width=110, anchor="e")
        
        # ONCE TANIMLA
        def load_purchases():
            for i in hist_tree.get_children(): hist_tree.delete(i)
            
            sup_filter = ent_search_sup.get().lower()
            mat_filter = ent_search_mat.get().lower()
            date_filter = ent_search_date.get()

            # Sadece APPROVED olanlari goster
            query = """
                SELECT t.id, t.date, t.description, m.name, t.quantity, t.unit_price, (t.quantity * t.unit_price) 
                FROM transactions t 
                LEFT JOIN materials m ON t.material_id = m.id 
                WHERE t.type='SATINALMA' AND (t.status IS NULL OR t.status='APPROVED')
            """
            params = []
            
            if sup_filter:
                query += " AND TR_LOWER(t.description) LIKE ?"
                params.append(f"%{sup_filter}%")
            if mat_filter:
                query += " AND TR_LOWER(m.name) LIKE ?"
                params.append(f"%{mat_filter}%")
            if date_filter:
                query += " AND t.date LIKE ?"
                params.append(f"%{date_filter}%")
                
            query += " ORDER BY t.id DESC"

            with self.db.get_conn() as conn:
                rows = conn.execute(query, params).fetchall()
                for r in rows:
                    try: up = f"{float(r[5]):.2f} ₺"; tp = f"{float(r[6]):.2f} ₺"
                    except: up=r[5]; tp=r[6]
                    hist_tree.insert("", "end", values=(r[0], r[1], r[2], r[3], r[4], up, tp))

        # SONRA KULLAN
        def edit_purchase_popup(event):
            item_id = hist_tree.identify_row(event.y)
            if not item_id: return
            vals = hist_tree.item(item_id)['values']
            tid = vals[0] # ID
            
            # DB'den guncel veriyi cek
            with self.db.get_conn() as conn:
                try: rec = conn.execute("SELECT t.date, t.description, t.quantity, t.unit_price, t.material_id, m.name, t.expiry_date, t.type FROM transactions t LEFT JOIN materials m ON t.material_id=m.id WHERE t.id=?", (tid,)).fetchone()
                except: rec = conn.execute("SELECT t.date, t.description, t.quantity, t.unit_price, t.material_id, m.name, '', t.type FROM transactions t LEFT JOIN materials m ON t.material_id=m.id WHERE t.id=?", (tid,)).fetchone()
            
            if not rec: return
            
            pop = ctk.CTkToplevel(self)
            pop.title("İşlem Düzenle")
            pop.geometry("400x500")
            pop.attributes("-topmost", True)
            
            ctk.CTkLabel(pop, text="İŞLEM DÜZENLE", font=("Bold", 16)).pack(pady=15)
            
            ctk.CTkLabel(pop, text=f"Malzeme: {rec[5]}", font=("Bold", 12)).pack(pady=5)
            
            ctk.CTkLabel(pop, text="Tarih:").pack(pady=(10,0))
            e_date = ctk.CTkEntry(pop); e_date.pack(); e_date.insert(0, rec[0])
            
            # SKT Duzenleme
            var_has_exp = tk.IntVar(value=0)
            f_exp_edit = ctk.CTkFrame(pop, fg_color="transparent")
            e_exp_date = None
            
            if "expiry_date" in self.loaded_modules and rec[7] in ["GİRİŞ", "SATINALMA"]:
                f_exp_edit.pack(pady=(5,0))
                f_exp_input = ctk.CTkFrame(f_exp_edit, fg_color="transparent")
                
                def toggle_exp_edit():
                    if var_has_exp.get() == 1: f_exp_input.pack(side="left", padx=5)
                    else: f_exp_input.pack_forget()

                ctk.CTkCheckBox(f_exp_edit, text="SKT'li Ürün", variable=var_has_exp, command=toggle_exp_edit, fg_color="#e67e22", width=20).pack(side="left")
                
                if DateEntry:
                    e_exp_date = DateEntry(f_exp_input, date_pattern='dd.mm.yyyy', width=12)
                    e_exp_date.pack()
                else:
                    e_exp_date = ctk.CTkEntry(f_exp_input, width=100)
                    e_exp_date.pack()
                
                if rec[6] and rec[6] != "":
                    var_has_exp.set(1)
                    if DateEntry: e_exp_date.set_date(rec[6])
                    else: e_exp_date.insert(0, rec[6])
                    toggle_exp_edit()
                else:
                    if not DateEntry: e_exp_date.insert(0, datetime.now().strftime("%d.%m.%Y"))

            ctk.CTkLabel(pop, text="Açıklama / Tedarikçi:").pack(pady=(5,0))
            with self.db.get_conn() as conn:
                s_list = [r[0] for r in conn.execute("SELECT name FROM suppliers").fetchall()]
            e_sup = ctk.CTkComboBox(pop, values=s_list); e_sup.pack(); e_sup.set(rec[1] if rec[1] else "")
            
            ctk.CTkLabel(pop, text="Miktar:").pack(pady=(5,0))
            e_qty = ctk.CTkEntry(pop); e_qty.pack(); e_qty.insert(0, str(rec[2]))
            
            ctk.CTkLabel(pop, text="Birim Fiyat:").pack(pady=(5,0))
            e_price = ctk.CTkEntry(pop); e_price.pack(); e_price.insert(0, str(rec[3]))
            
            old_qty = float(rec[2])
            mat_id = rec[4]
            
            def save_edit():
                # load_purchases fonksiyonu edit_purchase_popup'dan once tanimlandigi icin erisilebilir olmali
                try:
                    n_date = e_date.get()
                    n_sup = e_sup.get()
                    n_qty = float(e_qty.get().replace(',','.'))
                    n_price = float(e_price.get().replace(',','.'))
                    
                    n_exp = ""
                    if var_has_exp.get() == 1 and e_exp_date:
                        n_exp = e_exp_date.get()
                    
                    if n_qty <= 0: return messagebox.showwarning("!", "Geçersiz miktar")
                    
                    diff = n_qty - old_qty
                    
                    with self.db.get_conn() as conn:
                        conn.execute("UPDATE materials SET stock = stock + ? WHERE id=?", (diff, mat_id))
                        conn.execute("UPDATE transactions SET date=?, description=?, quantity=?, unit_price=?, expiry_date=? WHERE id=?", 
                                     (n_date, n_sup, n_qty, n_price, n_exp, tid))
                        conn.commit()
                        
                    messagebox.showinfo("Başarılı", "Kayıt güncellendi.")
                    pop.destroy()
                    load_purchases() # Listeyi yenile
                except Exception as e: messagebox.showerror("Hata", str(e))
            
            ctk.CTkButton(pop, text="KAYDET", command=save_edit, fg_color="#27ae60").pack(pady=20)

        ctk.CTkButton(f_filter, text="FİLTRELE", command=load_purchases, width=80, height=28, fg_color="#2980b9").pack(side="left", padx=5)
        ctk.CTkButton(f_filter, text="TEMİZLE", command=lambda: [ent_search_sup.delete(0,'end'), ent_search_mat.delete(0,'end'), ent_search_date.delete(0,'end'), load_purchases()], width=80, height=28, fg_color="#7f8c8d").pack(side="left", padx=5)
        
        ent_search_sup.bind("<Return>", lambda e: load_purchases())
        ent_search_mat.bind("<Return>", lambda e: load_purchases())
        ent_search_date.bind("<Return>", lambda e: load_purchases())
            
        hist_tree.bind("<Double-1>", edit_purchase_popup)

        load_purchases()

    
    def render_settings(self):
        # TABVIEW YAPISI
        tabs = ctk.CTkTabview(self.container, anchor="nw", corner_radius=15)
        tabs.pack(fill="both", expand=True, padx=20, pady=20)
        
        tab_gen = tabs.add("GENEL AYARLAR")
        tab_mod = tabs.add("🧩 MODÜL YÖNETİMİ")
        tab_menu = tabs.add("MENÜ YÖNETİMİ")
        
        # --- TAB 1: GENEL AYARLAR ---
        card = ctk.CTkFrame(tab_gen, corner_radius=15, fg_color="transparent")
        card.pack(fill="both", expand=True, padx=20, pady=10)
        
        # --- GENEL AYARLAR (Hizalama Duzeltildi - Grid) ---
        f_gen = ctk.CTkFrame(card, fg_color="transparent")
        f_gen.pack(pady=10)
        
        ctk.CTkLabel(f_gen, text="Depo İsmi:").grid(row=0, column=0, sticky="e", padx=10, pady=10)
        en_depot = ctk.CTkEntry(f_gen, width=250); en_depot.grid(row=0, column=1, sticky="w", padx=10, pady=10)
        en_depot.insert(0, self.db.get_setting('depot_name'))
        
        ctk.CTkLabel(f_gen, text="Versiyon:").grid(row=1, column=0, sticky="e", padx=10, pady=10)
        lbl_ver = ctk.CTkLabel(f_gen, text="v1.1 (Modular)", font=("Segoe UI", 12, "bold"), text_color="gray70")
        lbl_ver.grid(row=1, column=1, sticky="w", padx=10, pady=10)

        # MODUL: SKT Ayari
        if "expiry_date" in self.loaded_modules:
            ctk.CTkLabel(f_gen, text="SKT Uyarı (Gün):").grid(row=2, column=0, sticky="e", padx=10, pady=10)
            en_exp_days = ctk.CTkEntry(f_gen, width=100)
            en_exp_days.grid(row=2, column=1, sticky="w", padx=10, pady=10)
            en_exp_days.insert(0, self.db.get_setting('expiry_warning_days') or "30")

        def save_gen(): 
            self.db.update_setting('depot_name', en_depot.get())
            
            if "expiry_date" in self.loaded_modules:
                try:
                    days = int(en_exp_days.get())
                    self.db.update_setting('expiry_warning_days', str(days))
                except: pass

            self.logo_label.configure(text=en_depot.get())
            self.title("RDT Pro")
            messagebox.showinfo("OK", "Genel ayarlar kaydedildi.")
            
        def reset_opts():
            if messagebox.askyesno("Onay", "Gizlenen tüm uyarı kutuları (Bir daha sorma dedikleriniz) tekrar aktif edilsin mi?"):
                with self.db.get_conn() as conn:
                    conn.execute("DELETE FROM app_settings WHERE key LIKE 'opt_%'")
                    conn.commit()
                messagebox.showinfo("Başarılı", "Tercihler sıfırlandı, uyarılar tekrar gösterilecek.")

        ctk.CTkButton(card, text="AYARLARI KAYDET", command=save_gen, height=35, fg_color="#27ae60", font=("Bold", 12)).pack(pady=5)
        ctk.CTkButton(card, text="UYARI TERCİHLERİNİ SIFIRLA", command=reset_opts, height=30, fg_color="#e67e22", font=("Bold", 11)).pack(pady=(0, 10))
        
        # --- GERI AL GECMISI ---
        f_undo_log = ctk.CTkFrame(card, fg_color="transparent")
        f_undo_log.pack(pady=5, fill="x", padx=20)
        ctk.CTkLabel(f_undo_log, text="SON GERİ ALINANLAR (Son 5)", font=("Bold", 12), text_color="#e74c3c").pack(pady=(5,2))
        
        if not self.undone_log:
            ctk.CTkLabel(f_undo_log, text="Henüz işlem yok.", text_color="gray70", font=("Segoe UI", 11)).pack()
        else:
            for log in list(reversed(self.undone_log))[:5]:
                ctk.CTkLabel(f_undo_log, text=log, font=("Segoe UI", 11)).pack()

        # Grid Layout for Lists
        grid_f = ctk.CTkFrame(card, fg_color="transparent")
        grid_f.pack(fill="both", expand=True, padx=20, pady=10)
        grid_f.grid_columnconfigure((0, 1), weight=1, uniform="x")

        # --- Birimler ---
        f_units = ctk.CTkFrame(grid_f); f_units.grid(row=0, column=0, sticky="nsew", padx=10)
        ctk.CTkLabel(f_units, text="BİRİM YÖNETİMİ", font=("Bold", 14)).pack(pady=5)
        
        u_add = ctk.CTkFrame(f_units, fg_color="transparent"); u_add.pack(pady=5)
        en_u = ctk.CTkEntry(u_add, placeholder_text="Yeni Birim", width=150); en_u.pack(side="left", padx=2)
        
        u_scroll = ctk.CTkScrollableFrame(f_units, height=200); u_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        def load_units():
            for w in u_scroll.winfo_children(): w.destroy()
            with self.db.get_conn() as conn:
                for r in conn.execute("SELECT name FROM stock_units ORDER BY name").fetchall():
                    r_f = ctk.CTkFrame(u_scroll, height=30); r_f.pack(fill="x", pady=2)
                    ctk.CTkLabel(r_f, text=r[0]).pack(side="left", padx=5)
                    ctk.CTkButton(r_f, text="Sil", width=40, fg_color="#c0392b", command=lambda n=r[0]: [conn.execute("DELETE FROM stock_units WHERE name=?",(n,)).connection.commit(), load_units()]).pack(side="right", padx=5)
        
        ctk.CTkButton(u_add, text="Ekle", width=50, command=lambda: [self.db.get_conn().execute("INSERT INTO stock_units (name) VALUES (?)",(en_u.get(),)).connection.commit(), en_u.delete(0,'end'), load_units()] if en_u.get() else None).pack(side="left")

        # --- Ekipler ---
        f_teams = ctk.CTkFrame(grid_f); f_teams.grid(row=0, column=1, sticky="nsew", padx=10)
        ctk.CTkLabel(f_teams, text="EKİP / ÇALIŞAN YÖNETİMİ", font=("Bold", 14)).pack(pady=5)
        
        t_add = ctk.CTkFrame(f_teams, fg_color="transparent"); t_add.pack(pady=5)
        en_t = ctk.CTkEntry(t_add, placeholder_text="Yeni Ekip", width=150); en_t.pack(side="left", padx=2)
        
        t_scroll = ctk.CTkScrollableFrame(f_teams, height=200); t_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        def load_teams():
            for w in t_scroll.winfo_children(): w.destroy()
            with self.db.get_conn() as conn:
                for r in conn.execute("SELECT name FROM teams ORDER BY name").fetchall():
                    r_f = ctk.CTkFrame(t_scroll, height=30); r_f.pack(fill="x", pady=2)
                    ctk.CTkLabel(r_f, text=r[0]).pack(side="left", padx=5)
                    ctk.CTkButton(r_f, text="Sil", width=40, fg_color="#c0392b", command=lambda n=r[0]: [conn.execute("DELETE FROM teams WHERE name=?",(n,)).connection.commit(), load_teams()]).pack(side="right", padx=5)
        
        ctk.CTkButton(t_add, text="Ekle", width=50, command=lambda: [self.db.get_conn().execute("INSERT INTO teams (name) VALUES (?)",(en_t.get(),)).connection.commit(), en_t.delete(0,'end'), load_teams()] if en_t.get() else None).pack(side="left")

        load_units(); load_teams()
        
        # --- TAB 2: MODÜL YÖNETİMİ ---
        ctk.CTkLabel(tab_mod, text="YÜKLÜ MODÜLLER VE EKLENTİLER", font=("Segoe UI", 18, "bold")).pack(pady=20)
        ctk.CTkLabel(tab_mod, text="Modülleri buradan aktif/pasif yapabilirsiniz. Değişiklikler yeniden başlatınca etkili olur.", text_color="gray").pack(pady=(0,20))
        
        mod_scroll = ctk.CTkScrollableFrame(tab_mod, fg_color="transparent")
        mod_scroll.pack(fill="both", expand=True, padx=20)
        
        if not self.available_modules:
            ctk.CTkLabel(mod_scroll, text="Klasörde modül dosyası bulunamadı.", text_color="#c0392b").pack(pady=20)
        
        for mod_data in self.available_modules:
            key = mod_data["key"]
            title = mod_data["title"]
            path = mod_data["path"]
            
            # DB'den durumu al
            current_state = self.db.get_setting(f"mod_state_{key}")
            is_active = (current_state != "0") # Default Active
            
            row = ctk.CTkFrame(mod_scroll, height=60, fg_color=("gray90", "gray20"))
            row.pack(fill="x", pady=5)
            
            # Ikon/Baslik
            ctk.CTkLabel(row, text=title, font=("Bold", 14)).pack(side="left", padx=15)
            
            # Dosya Yolu
            ctk.CTkLabel(row, text=os.path.basename(path), font=("Segoe UI", 11), text_color="gray").pack(side="left", padx=10)
            
            # Switch
            def on_toggle(k=key, var=None, sw_widget=None):
                val = "1" if var.get() == 1 else "0"
                self.db.update_setting(f"mod_state_{k}", val)
                if sw_widget: sw_widget.configure(text="AKTİF" if val=="1" else "PASİF")
                
                # Degisiklik oldu, butonu goster
                if btn_restart.winfo_ismapped() == 0:
                    btn_restart.pack(pady=10)

            var_sw = tk.IntVar(value=1 if is_active else 0)
            sw_text = "AKTİF" if is_active else "PASİF"
            sw = ctk.CTkSwitch(row, text=sw_text, variable=var_sw, onvalue=1, offvalue=0)
            sw.configure(command=lambda k=key, v=var_sw, s=sw: on_toggle(k, v, s))
            sw.pack(side="right", padx=15)

        def restart_program():
            try:
                python = sys.executable
                os.execl(python, python, *sys.argv)
            except Exception as e:
                messagebox.showerror("Hata", f"Yeniden başlatılamadı:\n{e}\nLütfen manuel kapatıp açın.")

        btn_restart = ctk.CTkButton(tab_mod, text="♻️ DEĞİŞİKLİKLER İÇİN YENİDEN BAŞLAT", command=restart_program, fg_color="#e67e22", hover_color="#d35400", height=40, font=("Bold", 12))
        # Baslangicta gizli (pack yapmiyoruz)

        # --- TAB 3: MENU YONETIMI ---
        ctk.CTkLabel(tab_menu, text="MENÜ GÖRÜNÜRLÜK AYARLARI", font=("Segoe UI", 18, "bold")).pack(pady=20)
        
        menu_scroll = ctk.CTkScrollableFrame(tab_menu, fg_color="transparent")
        menu_scroll.pack(fill="both", expand=True, padx=20)
        
        # Standart Menuler + Moduller
        all_menus = self.menu_definitions + []
        
        # Modulden gelenleri de ekleyelim (Eger tanimda yoksa)
        existing_keys = [x[0] for x in all_menus]
        for key, mod in self.loaded_modules.items():
            if key not in existing_keys:
                all_menus.append((key, mod.info.get("title", key)))
        
        for key, title in all_menus:
            # Dashboard gizlenemez
            if key == "dashboard": continue
            
            row = ctk.CTkFrame(menu_scroll, height=50, fg_color=("gray90", "gray20"))
            row.pack(fill="x", pady=5)
            
            ctk.CTkLabel(row, text=title, font=("Bold", 14)).pack(side="left", padx=15)
            
            # DB durumu (Default: 1)
            curr = self.db.get_setting(f"menu_vis_{key}")
            is_vis = (curr != "0")
            
            def toggle_menu(k=key, var=None):
                val = "1" if var.get() == 1 else "0"
                self.db.update_setting(f"menu_vis_{k}", val)
                
                if val == "0":
                    # Gizle (Animasyonlu - Wrapper uzerinden)
                    if hasattr(self, 'nav_wrappers') and k in self.nav_wrappers:
                        wrapper = self.nav_wrappers[k]
                        self.animate_hide(wrapper)
                        if k in self.nav_buttons: del self.nav_buttons[k]
                        if k in self.nav_wrappers: del self.nav_wrappers[k]
                else:
                    # Goster (Refresh + Show Animasyon)
                    self.refresh_sidebar()
                    # Yeni eklenen wrapper'i bul
                    if hasattr(self, 'nav_wrappers') and k in self.nav_wrappers:
                        wrapper = self.nav_wrappers[k]
                        # Baslangic boyutu 1, hedef 50
                        wrapper.configure(height=1)
                        self.animate_show(wrapper, target_h=50, current_h=1)

            var_sw = tk.IntVar(value=1 if is_vis else 0)
            sw = ctk.CTkSwitch(row, text="GÖSTER", variable=var_sw, command=lambda k=key, v=var_sw: toggle_menu(k, v), onvalue=1, offvalue=0)
            sw.pack(side="right", padx=15)

        # Yedek Geri Yükle Butonu (Tab Geneline Tasindi)
        def restore_backup():
            if not messagebox.askyesno("DİKKAT", "Veriler silinecek. Devam?"): return
            p = filedialog.askopenfilename(filetypes=[("Veritabanı", "*.db")])
            if p:
                try: shutil.copy(p, DB_PATH); messagebox.showinfo("OK", "Yedek yüklendi. Yeniden başlatın."); sys.exit(0)
                except Exception as e: messagebox.showerror("Hata", str(e))

        def factory_reset():
            if not messagebox.askyesno("KRİTİK UYARI", "Tüm malzemeler, stok hareketleri ve satın alma verileri kalıcı olarak SİLİNECEKTİR!\n\nBu işlem geri alınamaz. Devam etmek istiyor musunuz?"): 
                return
            
            if not messagebox.askyesno("SON ONAY", "Emin misiniz?"):
                return

            try:
                with self.db.get_conn() as conn:
                    # Temizlenecek tablolar
                    tables = ["materials", "transactions", "product_locations", "suppliers", "undo_logs"]
                    for table in tables:
                        try: conn.execute(f"DELETE FROM {table}")
                        except: pass
                    
                    # SQLite sayacını sıfırla
                    conn.execute("DELETE FROM sqlite_sequence")
                    conn.commit()
                
                self.cached_fig = None # Grafiği temizle
                messagebox.showinfo("Başarılı", "Sistem fabrika ayarlarına sıfırlandı.")
                self.show_page("dashboard")
            except Exception as e:
                messagebox.showerror("Hata", f"Sıfırlama sırasında hata oluştu: {e}")

        # Alt Butonlar Konteyner (Genişlik uyumu için)
        bottom_btns = ctk.CTkFrame(tab_gen, fg_color="transparent")
        bottom_btns.pack(side="bottom", pady=20)

        ctk.CTkButton(bottom_btns, text="FABRİKA A. SIFIRLA", command=factory_reset, fg_color="#c0392b", hover_color="#a93226", width=250, height=35).pack(pady=(0, 10))
        ctk.CTkButton(bottom_btns, text="YEDEKTEN GERİ YÜKLE", command=restore_backup, fg_color="#7f8c8d", width=250, height=35).pack()

    # ... (Helper methods preserved: setup_treeview, sort_tree, apply_sorting, open_edit_popup, import_action, clear_db_action, export_action)
    def setup_treeview(self, parent, cols):
        style = ttk.Style(); style.theme_use("clam")
        mode = ctk.get_appearance_mode(); bg = "#2b2b2b" if mode == "Dark" else "white"; fg = "white" if mode == "Dark" else "black"
        style.configure("Treeview", background=bg, foreground=fg, fieldbackground=bg, rowheight=35, borderwidth=0)
        style.configure("Treeview.Heading", background="#34495e", foreground="white", font=("Segoe UI", 11, "bold"))
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=20)
        for c in cols: tree.heading(c, text=c, command=lambda _c=c: self.sort_tree(_c, tree)); tree.column(c, anchor="center")
        sc = ctk.CTkScrollbar(parent, command=tree.yview); tree.configure(yscrollcommand=sc.set)
        tree.pack(side="left", fill="both", expand=True); sc.pack(side="right", fill="y"); return tree

    def sort_tree(self, col, tree):
        data = [(tree.set(child, col), child) for child in tree.get_children('')]
        reverse = bool(self.db.get_setting('sort_reverse') == '1')
        if self.db.get_setting('sort_col') == col: reverse = not reverse
        else: reverse = False
        try: data.sort(key=lambda x: float(x[0].replace(',', '.')), reverse=reverse)
        except ValueError: data.sort(key=lambda x: tr_sort(x[0]), reverse=reverse)
        for index, (val, child) in enumerate(data): tree.move(child, '', index)
        self.db.update_setting('sort_col', col)
        self.db.update_setting('sort_reverse', '1' if reverse else '0')
        for c in tree["columns"]: tree.heading(c, text=c)
        arrow = " ▼" if reverse else " ▲"
        tree.heading(col, text=col + arrow, command=lambda _c=col: self.sort_tree(_c, tree))

    def apply_sorting(self, tree):
        col = self.db.get_setting('sort_col') or "Malzeme Adı"
        # Eğer bu kolon mevcut değilse sıralama yapma (Örn: Konum modülü kapalıyken Konum'a göre sıralı kalmış olabilir)
        if col not in tree["columns"]: return
        
        rev = self.db.get_setting('sort_reverse') == "1"
        data = [(tree.set(child, col), child) for child in tree.get_children('')]
        try: data.sort(key=lambda x: float(str(x[0]).replace(',', '.')), reverse=rev)
        except: data.sort(key=lambda x: tr_sort(x[0]), reverse=rev)
        for index, (val, child) in enumerate(data): tree.move(child, '', index)

    def open_edit_popup(self, m_id, cb):
        pop = ctk.CTkToplevel(self); pop.title("Düzenle"); pop.geometry("450x700"); pop.attributes("-topmost", True)
        
        with self.db.get_conn() as conn: 
            # track_expiry kolonunu da cek (index 6)
            try: d = conn.execute("SELECT name, stock, unit, track_critical, image_path, is_unlimited, track_expiry FROM materials WHERE id=?", (m_id,)).fetchone()
            except: d = conn.execute("SELECT name, stock, unit, track_critical, NULL, 0, 0 FROM materials WHERE id=?", (m_id,)).fetchone()

        ctk.CTkLabel(pop, text="MALZEME DÜZENLE", font=("Bold", 18)).pack(pady=15)
        
        img_frame = ctk.CTkFrame(pop, width=120, height=120, fg_color="transparent"); img_frame.pack(pady=5)
        curr_img_path = tk.StringVar(value=d[4] if d[4] else "")
        lbl_img = tk.Label(img_frame, bg="#2b2b2b"); lbl_img.pack()

        def refresh_preview():
            path = curr_img_path.get()
            if path and os.path.exists(path) and Image and ImageTk:
                try:
                    pil = Image.open(path); pil.thumbnail((120, 120))
                    tk_im = ImageTk.PhotoImage(pil)
                    lbl_img.configure(image=tk_im, text=""); lbl_img.image = tk_im
                except: lbl_img.configure(text="Hata", image="")
            else: lbl_img.configure(image="", text="Resim Yok", fg="white", bg="#2b2b2b")

        refresh_preview()

        def chg_img():
            p = filedialog.askopenfilename(filetypes=[("Resim", "*.jpg;*.jpeg;*.png")])
            if p: curr_img_path.set(p); refresh_preview()

        def rem_img(): curr_img_path.set(""); refresh_preview()

        btn_box = ctk.CTkFrame(pop, fg_color="transparent"); btn_box.pack(pady=5)
        ctk.CTkButton(btn_box, text="📷 Değiştir", command=chg_img, width=80, height=24, fg_color="#8e44ad").pack(side="left", padx=5)
        ctk.CTkButton(btn_box, text="🗑️ Kaldır", command=rem_img, width=80, height=24, fg_color="#c0392b").pack(side="left", padx=5)

        en = ctk.CTkEntry(pop, width=300); en.pack(pady=10); en.insert(0, d[0])
        es = ctk.CTkEntry(pop, width=300); es.pack(pady=10); es.insert(0, f"{d[1]:g}")
        
        with self.db.get_conn() as conn:
            unit_list = [u[0] for u in conn.execute("SELECT name FROM stock_units ORDER BY name").fetchall()]
            if not unit_list: unit_list = ["Adet", "Kg"]
            
        eu = ctk.CTkComboBox(pop, values=unit_list, width=300); eu.pack(pady=10); eu.set(d[2])
        
        tc = tk.IntVar(value=d[3])
        ctk.CTkCheckBox(pop, text="Kritik Stok Takibi", variable=tc).pack(pady=5)
        
        # MODUL: SKT Takibi
        te = tk.IntVar(value=d[6] if len(d)>6 and d[6] else 0)
        
        # SKT Duzenleme (En son giris islemi icin)
        ent_last_exp = None
        
        if "expiry_date" in self.loaded_modules:
            f_skt = ctk.CTkFrame(pop, fg_color="transparent")
            f_skt.pack(pady=2)
            
            chk_te = ctk.CTkCheckBox(f_skt, text="📅 SKT Takibi", variable=te, fg_color="#e67e22")
            chk_te.pack(pady=2)
            
            f_exp_wrapper = ctk.CTkFrame(f_skt, fg_color="transparent")
            
            def toggle_skt_entry():
                if te.get() == 1:
                    f_exp_wrapper.pack(pady=2)
                else:
                    f_exp_wrapper.pack_forget()

            chk_te.configure(command=toggle_skt_entry)
            
            last_exp_val = ""
            try:
                lexp = conn.execute("SELECT expiry_date FROM transactions WHERE material_id=? AND (type='GİRİŞ' OR type='SATINALMA') ORDER BY id DESC LIMIT 1", (m_id,)).fetchone()
                if lexp: last_exp_val = lexp[0]
            except: pass
            
            if DateEntry:
                ent_last_exp = DateEntry(f_exp_wrapper, date_pattern='dd.mm.yyyy', width=12)
                ent_last_exp.pack()
                if last_exp_val: ent_last_exp.set_date(last_exp_val)
            else:
                ent_last_exp = ctk.CTkEntry(f_exp_wrapper, width=100)
                ent_last_exp.pack()
                if last_exp_val: ent_last_exp.insert(0, last_exp_val)
            
            toggle_skt_entry()
        
        ul = tk.IntVar(value=d[5] if len(d) > 5 and d[5] else 0)
        
        def toggle_es():
            if ul.get() == 1: es.configure(state="disabled", fg_color="gray20")
            else: es.configure(state="normal", fg_color=("white", "#343638"))
            
        ctk.CTkCheckBox(pop, text="Sınırsız Stok", variable=ul, command=toggle_es).pack(pady=5)
        toggle_es()

        # --- KONUM DÜZENLEME BÖLÜMÜ ---
        if "location_management" in self.loaded_modules:
            ctk.CTkLabel(pop, text="📍 Malzeme Konumu:", font=("Segoe UI", 12, "bold")).pack(pady=(10, 0))
            
            loc_frame = ctk.CTkFrame(pop, fg_color="transparent")
            loc_frame.pack(fill="x", pady=5)
            
            # Ortalama için iç frame
            loc_inner = ctk.CTkFrame(loc_frame, fg_color="transparent")
            loc_inner.pack(expand=True)
            
            self.edit_loc_path = tk.StringVar()
            self.edit_selected_node_id = None
            
            # Mevcut konumu çek
            with self.db.get_conn() as conn:
                cur_loc = conn.execute("""
                    WITH RECURSIVE Path(id, name, parent_id, full_path) AS (
                        SELECT id, name, parent_id, name FROM location_nodes WHERE (parent_id IS NULL OR parent_id = 0)
                        UNION ALL
                        SELECT n.id, n.name, n.parent_id, p.full_path || ' > ' || n.name
                        FROM location_nodes n JOIN Path p ON n.parent_id = p.id
                    )
                    SELECT p.full_path, p.id FROM Path p 
                    JOIN product_locations pl ON pl.location_id = (SELECT id FROM locations WHERE node_id = p.id)
                    WHERE pl.product_id = ? LIMIT 1
                """, (m_id,)).fetchone()
                
                if cur_loc:
                    self.edit_loc_path.set(cur_loc[0])
                    self.edit_selected_node_id = cur_loc[1]
                else:
                    self.edit_loc_path.set("Konum Atanmamış")

            ent_loc_disp = ctk.CTkEntry(loc_inner, textvariable=self.edit_loc_path, state="readonly", width=220, font=("Segoe UI", 11))
            ent_loc_disp.pack(side="left", padx=(0, 5))
            
            def open_edit_loc_selector():
                self.open_location_selector_for_edit(pop)

            ctk.CTkButton(loc_inner, text="✏️", width=35, command=open_edit_loc_selector).pack(side="left")

        def save():
            final_path = d[4]
            new_p = curr_img_path.get()
            if new_p != d[4]:
                if new_p and os.path.exists(new_p):
                    ext = os.path.splitext(new_p)[1]
                    safe_name = f"{tr_sort(en.get()).replace(' ','_')}_{datetime.now().strftime('%H%M%S')}{ext}"
                    dest = ROOT_DIR / "Urun_Resimleri" / safe_name
                    try: shutil.copy(new_p, dest); final_path = str(dest)
                    except: final_path = new_p
                else: final_path = None
            
            if ul.get() == 1:
                stock_val = 0.0
            else:
                try: stock_val = float(es.get().replace(',', '.'))
                except: stock_val = 0.0

            with self.db.get_conn() as conn: 
                conn.execute("UPDATE materials SET name=?, stock=?, unit=?, track_critical=?, image_path=?, is_unlimited=?, track_expiry=? WHERE id=?", 
                             (en.get(), stock_val, eu.get(), tc.get(), final_path, ul.get(), te.get(), m_id))
                
                # Konumu Guncelle (Sadece modül aktifse)
                if "location_management" in self.loaded_modules and hasattr(self, 'edit_selected_node_id') and self.edit_selected_node_id:
                    # locations tablosunda node_id'ye karşılık gelen id'yi bul
                    loc_row = conn.execute("SELECT id FROM locations WHERE node_id=?", (self.edit_selected_node_id,)).fetchone()
                    if loc_row:
                        loc_id = loc_row[0]
                        # Varsa güncelle, yoksa ekle
                        conn.execute("DELETE FROM product_locations WHERE product_id=?", (m_id,))
                        conn.execute("INSERT INTO product_locations (product_id, location_id) VALUES (?,?)", (m_id, loc_id))

                # SKT Guncelleme (Varsa)
                if ent_last_exp:
                    new_exp = ent_last_exp.get()
                    # En son giris islemine update at
                    last_tx = conn.execute("SELECT id FROM transactions WHERE material_id=? AND (type='GİRİŞ' OR type='SATINALMA') ORDER BY id DESC LIMIT 1", (m_id,)).fetchone()
                    if last_tx:
                        conn.execute("UPDATE transactions SET expiry_date=? WHERE id=?", (new_exp, last_tx[0]))

                conn.commit()
            cb(); pop.destroy() 
            
        def run_delete():
            if not ask_yesno_optout(self, "Onay", "Bu malzeme ve geçmiş hareketleri silinecek.\nDevam edilsin mi?", "opt_del_mat_confirm", self.db): return
            
            # Silinmeden once verileri yedekle
            deleted_data = {
                'id': int(m_id), # Eski ID'yi sakla
                'name': str(d[0]), 'stock': float(d[1]) if d[1] is not None else 0.0, 
                'unit': str(d[2]), 'critical': int(d[3]), 
                'image': str(d[4]) if d[4] else None, 
                'unlimited': int(d[5]) if len(d)>5 and d[5] is not None else 0
            }

            def redo_op():
                """Silme islemini yapar (veya yeniden yapar)"""
                try:
                    with self.db.get_conn() as conn:
                        conn.execute("DELETE FROM materials WHERE name=? AND stock=?", (deleted_data['name'], deleted_data['stock']))
                        conn.commit()
                    self.db.reindex_materials()
                except Exception as e: log_debug(f"Redo Delete Error: {e}")

            def undo_op():
                """Silineni eski yerine koyar"""
                try:
                    with self.db.get_conn() as conn:
                        rows = conn.execute("SELECT name, stock, unit, track_critical, image_path, is_unlimited FROM materials ORDER BY id").fetchall()
                        data_list = list(rows)
                        restored_row = (deleted_data['name'], deleted_data['stock'], deleted_data['unit'], 
                                        deleted_data['critical'], deleted_data['image'], deleted_data['unlimited'])
                        
                        insert_idx = deleted_data['id'] - 1
                        if insert_idx < 0: insert_idx = 0
                        if insert_idx > len(data_list): insert_idx = len(data_list)
                        
                        data_list.insert(insert_idx, restored_row)
                        
                        conn.execute("DELETE FROM materials"); conn.execute("DELETE FROM sqlite_sequence WHERE name='materials'")
                        for i, r in enumerate(data_list, 1):
                            conn.execute("INSERT INTO materials (id, name, stock, unit, track_critical, image_path, is_unlimited) VALUES (?,?,?,?,?,?,?)",
                                         (i, r[0], r[1], r[2], r[3], r[4], r[5]))
                        conn.commit()
                except Exception as e: log_debug(f"Undo Delete Error: {e}")

            # Ilk silme islemini yap
            redo_op()
            self.push_undo(f"Silindi: {deleted_data['name']}", undo_op, redo_op)
            
            cb(); pop.destroy()
            show_info_optout(self, "Bilgi", "Malzeme silindi.", "opt_del_mat_info", self.db)

        ctk.CTkButton(pop, text="KAYDET", fg_color="#27ae60", command=save, height=40).pack(pady=10)
        ctk.CTkButton(pop, text="SİL", fg_color="#c0392b", command=run_delete).pack()

    def import_action(self):
        import pandas as pd
        p = filedialog.askopenfilename(filetypes=[("Excel", "*.xlsx")])
        if p:
            try:
                df = pd.read_excel(p, header=None)
                with self.db.get_conn() as conn:
                    for _, r in df.iterrows():
                        try:
                            if pd.isna(r[1]) or str(r[1]).strip().lower() in ['nan', 'ad', 'malzeme', 'malzeme adı']: continue
                            name = str(r[1]).strip()
                            stock = float(r[2]) if not pd.isna(r[2]) else 0.0
                            unit = str(r[3]).strip() if not pd.isna(r[3]) else "Adet"
                            conn.execute("INSERT INTO materials (name, stock, unit, track_critical) VALUES (?,?,?,1)", (name, stock, unit))
                        except Exception: continue
                    conn.commit()
                self.db.reindex_materials()
            except Exception as e:
                messagebox.showerror("Hata", f"İçe aktarma hatası: {e}")
            self.show_page("stock")
            messagebox.showinfo("Başarılı", "Kayıtlar başarıyla eklendi.")

    def open_location_selector_for_edit(self, parent_pop):
        pop = ctk.CTkToplevel(parent_pop)
        pop.title("Yeni Konum Seç")
        
        # Pencereyi ortala
        w, h = 500, 650
        px = parent_pop.winfo_x()
        py = parent_pop.winfo_y()
        pw = parent_pop.winfo_width()
        ph = parent_pop.winfo_height()
        
        x = px + (pw // 2) - (w // 2)
        y = py + (ph // 2) - (h // 2)
        pop.geometry(f"{w}x{h}+{x}+{y}")
        
        pop.transient(parent_pop)
        pop.attributes("-topmost", True)
        pop.grab_set()
        pop.focus()

        ctk.CTkLabel(pop, text="📍 YENİ KONUM SEÇİNİZ", font=("Segoe UI", 16, "bold")).pack(pady=10)

        # --- ARAMA BÖLÜMÜ ---
        search_frame = ctk.CTkFrame(pop, fg_color="transparent")
        search_frame.pack(fill="x", padx=20, pady=(0, 10))
        
        ent_search = ctk.CTkEntry(search_frame, placeholder_text="🔍 Lokasyon Ara...", height=35)
        ent_search.pack(fill="x")

        tree_frame = ctk.CTkFrame(pop, fg_color="#2b2b2b", corner_radius=10)
        tree_frame.pack(fill="both", expand=True, padx=20, pady=10)

        tree = ttk.Treeview(tree_frame, selectmode="browse", show="tree")
        tree.column("#0", width=400, stretch=True)
        
        scrollbar = ctk.CTkScrollbar(tree_frame, orientation="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        # Veri Yükleme
        all_nodes = []
        with self.db.get_conn() as conn:
            all_nodes = conn.execute("SELECT id, parent_id, level_type, name FROM location_nodes WHERE active=1").fetchall()

        nodes_ref = {} # Isim bulmak icin global referans (Full Path icin)
        for r in all_nodes: nodes_ref[r[0]] = r

        def build_tree(query=""):
            for i in tree.get_children(): tree.delete(i)
            
            children_map = {}
            q = tr_lower(query)
            
            for r in all_nodes:
                pid = r[1] or 0
                if pid not in children_map: children_map[pid] = []
                children_map[pid].append(r)

            def insert_recursive(pid, ui_parent):
                if pid in children_map:
                    for c in children_map[pid]:
                        if q and q not in tr_lower(c[3]):
                            has_match = False
                            def check_desc(parent_id):
                                nonlocal has_match
                                if parent_id in children_map:
                                    for child in children_map[parent_id]:
                                        if q in tr_lower(child[3]): has_match = True; return
                                        check_desc(child[0])
                            check_desc(c[0])
                            if not has_match: continue

                        icon = "🏢" if c[2]=="KAT" else "🚧" if c[2]=="BOLGE" else "🗄️" if c[2]=="RAF" else "📦"
                        uid = tree.insert(ui_parent, "end", text=f"{icon} {c[3]}", values=(c[0], c[2], c[3]))
                        if q: tree.item(uid, open=True)
                        insert_recursive(c[0], uid)

            insert_recursive(0, "")

        build_tree()
        ent_search.bind("<KeyRelease>", lambda e: build_tree(ent_search.get()))

        def confirm_selection():
            sel = tree.selection()
            if not sel: return messagebox.showwarning("!", "Lütfen bir lokasyon seçin.", parent=pop)
            
            item = tree.item(sel[0])
            nid, ntype, nname = item['values']
            
            # Tam yolu bul
            path_parts = [nname]
            curr_id = nid
            while True:
                parent_info = nodes_ref.get(curr_id)
                if not parent_info or not parent_info[1] or parent_info[1] == 0: break
                parent_node = nodes_ref.get(parent_info[1])
                if not parent_node: break
                path_parts.insert(0, parent_node[3])
                curr_id = parent_node[0]
            
            full_path = " > ".join(path_parts)
            self.edit_loc_path.set(full_path)
            self.edit_selected_node_id = nid
            pop.destroy()

        ctk.CTkButton(pop, text="SEÇİMİ ONAYLA", command=confirm_selection, fg_color="#27ae60", height=40, font=("Segoe UI", 13, "bold")).pack(pady=10)

    def open_location_selector_for_bulk(self, parent_pop, path_var, id_var):
        pop = ctk.CTkToplevel(parent_pop)
        pop.title("Toplu Konum Seç")
        w, h = 500, 650
        px, py = parent_pop.winfo_x(), parent_pop.winfo_y()
        pw, ph = parent_pop.winfo_width(), parent_pop.winfo_height()
        pop.geometry(f"500x650+{px+(pw//2)-250}+{py+(ph//2)-325}")
        pop.transient(parent_pop); pop.attributes("-topmost", True); pop.grab_set(); pop.focus()

        ctk.CTkLabel(pop, text="📍 TOPLU KONUM SEÇİMİ", font=("Segoe UI", 16, "bold")).pack(pady=10)
        ent_search = ctk.CTkEntry(pop, placeholder_text="🔍 Lokasyon Ara...", height=35); ent_search.pack(fill="x", padx=20, pady=10)
        tree_frame = ctk.CTkFrame(pop, fg_color="#2b2b2b", corner_radius=10); tree_frame.pack(fill="both", expand=True, padx=20, pady=10)
        tree = ttk.Treeview(tree_frame, selectmode="browse", show="tree"); tree.column("#0", width=400, stretch=True)
        scrollbar = ctk.CTkScrollbar(tree_frame, orientation="vertical", command=tree.yview); tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y"); tree.pack(side="left", fill="both", expand=True, padx=5, pady=5)

        all_nodes = []
        with self.db.get_conn() as conn:
            all_nodes = conn.execute("SELECT id, parent_id, level_type, name FROM location_nodes WHERE active=1").fetchall()
        nodes_ref = {r[0]: r for r in all_nodes}

        def build_tree(query=""):
            for i in tree.get_children(): tree.delete(i)
            children_map = {}; q = tr_lower(query)
            for r in all_nodes:
                pid = r[1] or 0
                if pid not in children_map: children_map[pid] = []
                children_map[pid].append(r)
            def ins_rec(pid, ui_p):
                if pid in children_map:
                    for c in children_map[pid]:
                        icon = "🏢" if c[2]=="KAT" else "🚧" if c[2]=="BOLGE" else "🗄️" if c[2]=="RAF" else "📦"
                        uid = tree.insert(ui_p, "end", text=f"{icon} {c[3]}", values=(c[0], c[2], c[3]))
                        if q: tree.item(uid, open=True)
                        ins_rec(c[0], uid)
            ins_rec(0, "")
        build_tree(); ent_search.bind("<KeyRelease>", lambda e: build_tree(ent_search.get()))

        def confirm():
            sel = tree.selection()
            if not sel: return
            item = tree.item(sel[0]); nid, ntype, nname = item['values']
            path_parts = [nname]; curr_id = nid
            while True:
                p_info = nodes_ref.get(curr_id)
                if not p_info or not p_info[1] or p_info[1] == 0: break
                p_node = nodes_ref.get(p_info[1])
                if not p_node: break
                path_parts.insert(0, p_node[3]); curr_id = p_node[0]
            path_var.set(" > ".join(path_parts)); id_var.set(nid); pop.destroy()

        ctk.CTkButton(pop, text="KONUMU ONAYLA", command=confirm, fg_color="#27ae60", height=40).pack(pady=10)

    def clear_db_action(self):
        if messagebox.askyesno("Onay", "Sıfırlansın mı?"):
            with self.db.get_conn() as conn:
                conn.execute("DELETE FROM materials"); conn.execute("DELETE FROM transactions")
                conn.execute("DELETE FROM sqlite_sequence"); conn.commit()
            self.show_page("stock")

    def export_action(self):
        import pandas as pd
        try:
            with self.db.get_conn() as conn:
                df1 = pd.read_sql_query("SELECT id as ID, name as 'Malzeme Adı', stock as Stok, unit as Birim FROM materials", conn)
                timestamp = datetime.now().strftime('%d%m%y_%H%M')
                path = REPORT_DIR / f"Rapor_{timestamp}.xlsx"; df1.to_excel(path, index=False)
                messagebox.showinfo("Başarılı", f"Kaydedildi:\n{path}")
                os.startfile(path)
        except Exception as e: messagebox.showerror("Hata", str(e))

    def show_full_image(self, img_path):
        if not os.path.exists(img_path) or not Image or not ImageTk: return
        
        # 1. KATMAN: Saydam Siyah Arka Plan (Overlay)
        overlay = tk.Toplevel(self)
        overlay.attributes("-fullscreen", True)
        overlay.attributes("-topmost", True)
        overlay.configure(bg="black")
        overlay.attributes("-alpha", 0.7) # Arka plan saydamlığı
        
        # 2. KATMAN: Opak Resim Penceresi
        img_win = tk.Toplevel(self)
        img_win.overrideredirect(True) # Kenarlıkları kaldır
        img_win.attributes("-topmost", True)
        img_win.configure(bg="black") # Resim etrafındaki çok küçük boşluklar için
        
        def close_gallery(e=None):
            img_win.destroy()
            overlay.destroy()

        # Her iki pencereye de kapatma komutunu bağla
        overlay.bind("<Button-1>", close_gallery)
        img_win.bind("<Button-1>", close_gallery)
        overlay.bind("<Key>", close_gallery)

        try:
            sw = overlay.winfo_screenwidth()
            sh = overlay.winfo_screenheight()
            
            pil_img = Image.open(img_path)
            orig_w, orig_h = pil_img.size
            
            # Ekranın %85'ine kadar büyütebilir
            ratio = min((sw * 0.85) / orig_w, (sh * 0.85) / orig_h)
            new_w = int(orig_w * ratio)
            new_h = int(orig_h * ratio)
            
            pil_img = pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            tk_img = ImageTk.PhotoImage(pil_img)
            
            # Resim penceresini ortala
            x = (sw - new_w) // 2
            y = (sh - new_h) // 2
            img_win.geometry(f"{new_w}x{new_h}+{x}+{y}")
            
            # Resmi yerleştir (Opak pencerede)
            lbl = tk.Label(img_win, image=tk_img, bg="black", borderwidth=0)
            lbl.image = tk_img 
            lbl.pack()
            
            # Bilgi yazısını saydam overlay'e ekle
            ctk.CTkLabel(overlay, text="Kapatmak için herhangi bir yere tıklayın", text_color="white", font=("Segoe UI", 14)).place(relx=0.5, rely=0.95, anchor="center")
            
            img_win.focus_force()
            
        except Exception as e:
            close_gallery()
            messagebox.showerror("Hata", f"Resim yüklenemedi: {e}")

if __name__ == "__main__":
    multiprocessing.freeze_support()
    log_debug("Main block basliyor...")
    try: 
        app = FIDTApp()
        log_debug("Uygulama baslatiliyor (mainloop)...")
        app.mainloop()
    except Exception as e:
        log_debug(f"KRITIK HATA: {e}")
        log_debug(traceback.format_exc())