from decimal import Decimal
from pathlib import Path
from datetime import date, timedelta
import shutil
import smtplib
import ssl
import tempfile
from email.message import EmailMessage
from email.utils import parseaddr
from PySide6.QtCore import Qt, QRectF, QDate
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget,
    QLabel, QLineEdit, QPushButton, QMessageBox, QTableWidget, QTableWidgetItem,
    QComboBox, QDoubleSpinBox, QSpinBox, QHeaderView, QFileDialog, QInputDialog, QCheckBox,
    QDialog, QDialogButtonBox, QAbstractItemView, QStackedWidget, QDateEdit,
    QListWidget, QListWidgetItem, QFrame, QApplication, QScrollArea, QSizePolicy
)
from sqlalchemy import select, func
from .db import SessionLocal, User, Customer, Product, Invoice, InvoiceItem, Payment, BusinessSettings, Supplier, Purchase, PurchaseItem, SupplierPayment, StockMovement, AuditLog, verify_password, hash_password, money, UserCompanyAccess, BranchAccess
from .access import get_accessible_contexts
from .services import (
    add_customer, add_product, create_invoice,
    calculate_invoice_preview, record_payment,
    add_supplier, record_purchase, update_purchase, record_supplier_payment
)
from .pdf_invoice import generate_invoice_pdf, generate_thermal_receipt
from .purchase_ocr import read_bill_text, suggest_purchase_fields

_active_window = None
_active_login_dialog = None

def show_error(parent, message):
    QMessageBox.critical(parent, "Unable to complete action", str(message))

def normalize_smtp_password(host, password):
    if host.strip().lower() == "smtp.gmail.com":
        password = "".join(password.split())
        if len(password) != 16 or not password.isalnum():
            raise ValueError("Google App Passwords are 16 letters/numbers. Enter the generated code without spaces or separators.")
    return password

def item(text):
    return QTableWidgetItem(str(text if text is not None else ""))



class PaymentDialog(QDialog):
    """Enter a partial payment or fill the invoice's remaining balance."""
    def __init__(self, invoice_number, balance, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Record Payment — {invoice_number}")
        self.setMinimumWidth(390)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Invoice:</b> {invoice_number}"))
        layout.addWidget(QLabel(f"Outstanding balance: ₹{balance:,.2f}"))
        form = QFormLayout()
        self.amount = QDoubleSpinBox()
        self.amount.setRange(0.01, float(max(balance, Decimal("0.01"))))
        self.amount.setDecimals(2)
        self.amount.setPrefix("₹ ")
        self.amount.setValue(float(balance))
        form.addRow("Amount received", self.amount)
        self.method = QComboBox()
        self.method.addItems(["UPI", "Cash", "Card", "Bank transfer"])
        form.addRow("Payment method", self.method)
        self.reference = QLineEdit()
        self.reference.setPlaceholderText("Optional transaction/reference number")
        form.addRow("Reference", self.reference)
        layout.addLayout(form)
        shortcuts = QHBoxLayout()
        full_due = QPushButton("Pay Full Due")
        full_due.clicked.connect(lambda: self.amount.setValue(float(balance)))
        one_thousand = QPushButton("₹1,000")
        one_thousand.clicked.connect(lambda: self.amount.setValue(min(1000.0, float(balance))))
        shortcuts.addWidget(full_due)
        shortcuts.addWidget(one_thousand)
        shortcuts.addStretch()
        layout.addLayout(shortcuts)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class SupplierPaymentDialog(QDialog):
    def __init__(self, purchase_number, due, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Record Supplier Payment — {purchase_number}")
        self.setMinimumWidth(400)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"<b>Purchase:</b> {purchase_number}"))
        layout.addWidget(QLabel(f"Outstanding: ₹{due:,.2f}"))
        form = QFormLayout()
        self.amount = QDoubleSpinBox(); self.amount.setRange(0.01, float(due)); self.amount.setDecimals(2)
        self.amount.setPrefix("₹ "); self.amount.setValue(float(due))
        self.method = QComboBox(); self.method.addItems(["Bank transfer", "UPI", "Cash", "Card", "Cheque"])
        self.reference = QLineEdit(); self.reference.setPlaceholderText("Optional transaction/reference number")
        form.addRow("Amount paid", self.amount); form.addRow("Payment method", self.method); form.addRow("Reference", self.reference)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept); buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class PasswordChangeDialog(QDialog):
    def __init__(self, username, require_current=True, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Change password — {username}")
        self.setMinimumWidth(420)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Set a new password for <b>{username}</b>. Password length is unrestricted."))
        form = QFormLayout()
        self.current = QLineEdit()
        self.current.setEchoMode(QLineEdit.Password)
        self.new = QLineEdit()
        self.new.setEchoMode(QLineEdit.Password)
        self.confirm = QLineEdit()
        self.confirm.setEchoMode(QLineEdit.Password)
        if require_current:
            form.addRow("Current password", self.current)
        form.addRow("New password", self.new)
        form.addRow("Confirm new password", self.confirm)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class CustomerAccountDialog(QDialog):
    """Professional customer account window with summary, invoices and payments."""
    def __init__(self, customer_data, invoice_rows, payment_rows, parent=None):
        super().__init__(parent)
        self.customer_id = int(customer_data["id"])
        self.setWindowTitle(f"Customer Account — {customer_data['name']}")
        self.resize(1050, 720)
        self.setMinimumSize(850, 600)
        self.setStyleSheet("""
            QDialog { background: #F4F7FB; color: #172033; }
            QLabel#pageTitle { font-size: 22px; font-weight: 700; color: #172033; }
            QLabel#muted { color: #64748B; font-size: 12px; }
            QFrame#panel { background: white; border: 1px solid #E2E8F0; border-radius: 10px; }
            QLabel#cardLabel { color: #64748B; font-size: 12px; }
            QLabel#cardValue { color: #172033; font-size: 20px; font-weight: 700; }
            QTableWidget { background: white; border: 1px solid #E2E8F0; gridline-color: #E8EDF4; border-radius: 7px; selection-background-color: #2563EB; selection-color: white; }
            QTableWidget::item:selected { background: #2563EB; color: white; }
            QTableWidget::item:selected:!active { background: #93C5FD; color: #172033; }
            QHeaderView::section { background: #EEF3FA; color: #334155; padding: 10px; border: none; border-bottom: 1px solid #DCE4EF; font-weight: 600; }
            QPushButton { background: #2563EB; color: white; border: none; border-radius: 6px; padding: 9px 20px; font-weight: 600; min-width: 90px; }
            QPushButton:hover { background: #1D4ED8; }
            QTabWidget::pane { border: 1px solid #E2E8F0; background: white; border-radius: 8px; }
            QTabBar::tab { background: #E8EEF7; padding: 10px 18px; margin-right: 4px; border-top-left-radius: 6px; border-top-right-radius: 6px; }
            QTabBar::tab:selected { background: white; color: #1D4ED8; font-weight: 700; }
        """)
        root = QVBoxLayout(self); root.setContentsMargins(22, 20, 22, 18); root.setSpacing(14)
        top = QHBoxLayout()
        title_col = QVBoxLayout()
        title = QLabel("Customer Account"); title.setObjectName("pageTitle")
        subtitle = QLabel(f"{customer_data['name']}  •  Customer ID #{customer_data['id']}"); subtitle.setObjectName("muted")
        title_col.addWidget(title); title_col.addWidget(subtitle)
        top.addLayout(title_col); top.addStretch()
        create_invoice_btn = QPushButton("+  Create Invoice")
        create_invoice_btn.setMinimumHeight(40)
        create_invoice_btn.clicked.connect(lambda: self._start_invoice(customer_data["id"]))
        status = QLabel("CUSTOMER LEDGER"); status.setStyleSheet("background:#DBEAFE;color:#1D4ED8;padding:7px 10px;border-radius:5px;font-size:11px;font-weight:700;")
        top.addWidget(create_invoice_btn, 0, Qt.AlignTop)
        top.addWidget(status, 0, Qt.AlignTop); root.addLayout(top)

        details = QFrame(); details.setObjectName("panel")
        dl = QVBoxLayout(details); dl.setContentsMargins(16, 12, 16, 12)
        info = QLabel(f"<b>Phone:</b> {customer_data['phone'] or '—'}   &nbsp;&nbsp; <b>Email:</b> {customer_data['email'] or '—'}<br><b>GSTIN:</b> {customer_data['gstin'] or '—'}   &nbsp;&nbsp; <b>State code:</b> {customer_data['state_code'] or '—'}<br><b>Address:</b> {customer_data['address'] or '—'}")
        info.setTextFormat(Qt.RichText); info.setWordWrap(True); info.setStyleSheet("line-height:1.5;color:#334155;")
        dl.addWidget(info); root.addWidget(details)

        cards = QHBoxLayout(); cards.setSpacing(12)
        metrics = [("TOTAL PURCHASES", customer_data['billed'], "#172033"), ("TOTAL PAID", customer_data['paid'], "#15803D"), ("OUTSTANDING DUE", customer_data['due'], "#B91C1C"), ("CREDIT LIMIT", customer_data['limit'], "#1D4ED8")]
        for label_text, amount, accent in metrics:
            card = QFrame(); card.setObjectName("panel"); cl = QVBoxLayout(card); cl.setContentsMargins(14, 12, 14, 12); cl.setSpacing(5)
            lab = QLabel(label_text); lab.setObjectName("cardLabel")
            val = QLabel(f"₹{amount:,.2f}"); val.setObjectName("cardValue"); val.setStyleSheet(f"color:{accent};")
            cl.addWidget(lab); cl.addWidget(val); cards.addWidget(card)
        root.addLayout(cards)

        tabs = QTabWidget()
        inv_page = QWidget(); il = QVBoxLayout(inv_page); il.setContentsMargins(10, 12, 10, 10)
        inv_table = QTableWidget(len(invoice_rows), 7); inv_table.setHorizontalHeaderLabels(["ID", "Invoice No.", "Date", "Total", "Paid", "Due", "Status"])
        inv_table.setColumnHidden(0, True)
        inv_table.setEditTriggers(QAbstractItemView.NoEditTriggers); inv_table.setSelectionBehavior(QAbstractItemView.SelectRows); inv_table.setAlternatingRowColors(True); inv_table.verticalHeader().setVisible(False)
        for r, row in enumerate(invoice_rows):
            for c, value in enumerate(row): inv_table.setItem(r, c, item(value))
        inv_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); inv_table.setMinimumHeight(180); il.addWidget(inv_table)
        self.invoice_table = inv_table
        invoice_actions = QHBoxLayout()
        self.account_payment_btn = QPushButton("Record Payment for Selected Invoice")
        self.account_payment_btn.clicked.connect(self.record_selected_payment)
        self.account_download_btn = QPushButton("Download Invoice PDF")
        self.account_download_btn.clicked.connect(self.download_selected_invoice)
        invoice_actions.addStretch(); invoice_actions.addWidget(self.account_download_btn); invoice_actions.addWidget(self.account_payment_btn)
        il.addLayout(invoice_actions)
        tabs.addTab(inv_page, f"Invoice History ({len(invoice_rows)})")

        pay_page = QWidget(); pl = QVBoxLayout(pay_page); pl.setContentsMargins(10, 12, 10, 10)
        pay_table = QTableWidget(len(payment_rows), 5); pay_table.setHorizontalHeaderLabels(["Payment Date", "Invoice No.", "Amount", "Method", "Reference"])
        pay_table.setEditTriggers(QAbstractItemView.NoEditTriggers); pay_table.setSelectionBehavior(QAbstractItemView.SelectRows); pay_table.setAlternatingRowColors(True); pay_table.verticalHeader().setVisible(False)
        for r, row in enumerate(payment_rows):
            for c, value in enumerate(row): pay_table.setItem(r, c, item(value))
        pay_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); pay_table.setMinimumHeight(180); pl.addWidget(pay_table)
        tabs.addTab(pay_page, f"Payment History ({len(payment_rows)})")
        root.addWidget(tabs, 1)
        bottom = QHBoxLayout(); note = QLabel("Account balances are calculated from issued invoices and recorded payments."); note.setObjectName("muted")
        close_btn = QPushButton("Close"); close_btn.clicked.connect(self.accept)
        bottom.addWidget(note); bottom.addStretch(); bottom.addWidget(close_btn); root.addLayout(bottom)

    def _start_invoice(self, customer_id):
        parent = self.parent()
        if parent is not None and hasattr(parent, "start_invoice_for_customer"):
            self.accept()
            parent.start_invoice_for_customer(customer_id)

    def record_selected_payment(self):
        row = self.invoice_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select an invoice", "Select an invoice to record a payment.")
            return
        try:
            invoice_id = int(self.invoice_table.item(row, 0).text())
        except (AttributeError, ValueError):
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "open_invoice_payment"):
            if parent.open_invoice_payment(invoice_id):
                self.accept()
                parent.refresh_dashboard()
                parent.view_record("customer", self.customer_id)

    def download_selected_invoice(self):
        row = self.invoice_table.currentRow()
        if row < 0:
            QMessageBox.information(self, "Select an invoice", "Select an invoice to download.")
            return
        try:
            invoice_id = int(self.invoice_table.item(row, 0).text())
        except (AttributeError, ValueError):
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "export_invoice_pdf"):
            parent.export_invoice_pdf(invoice_id)


class LoginDialog(QDialog):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("GST Billing — Login")
        self.setMinimumWidth(330)
        self.username = QLineEdit("admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form = QFormLayout()
        form.addRow("Username", self.username)
        form.addRow("Password", self.password)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.try_login)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("<h2>GST Billing System</h2>"))
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.user = None

    def try_login(self):
        with SessionLocal() as s:
            u = s.scalar(select(User).where(
                User.username == self.username.text().strip(),
                User.active.is_(True),
            ))
            if not u or not verify_password(self.password.text(), u.password_hash):
                QMessageBox.warning(self, "Login failed", "Invalid username or password.")
                return

            contexts = get_accessible_contexts(s, u.id)
            if not contexts:
                QMessageBox.warning(
                    self, "No access assigned",
                    "This user has no active company, branch, and warehouse access. "
                    "Ask an administrator to assign access.",
                )
                return

            def choose_context_value(title, values, label):
                unique = {}
                for context in contexts:
                    key = context[label]
                    unique[str(key)] = context[label.replace("_name", "_id")]
                labels = list(unique.keys())
                if len(labels) == 1:
                    return unique[labels[0]]
                selected, ok = QInputDialog.getItem(self, title, title, labels, 0, False)
                if not ok:
                    return None
                return unique[selected]

            company_id = choose_context_value("Select Company", contexts, "company_name")
            if company_id is None:
                return
            company_contexts = [x for x in contexts if x["company_id"] == company_id]
            branch_id = choose_context_value("Select Branch", company_contexts, "branch_name")
            if branch_id is None:
                return
            branch_contexts = [x for x in company_contexts if x["branch_id"] == branch_id]
            warehouse_id = choose_context_value("Select Warehouse", branch_contexts, "warehouse_name")
            if warehouse_id is None:
                return
            selected = next(
                x for x in branch_contexts if x["warehouse_id"] == warehouse_id
            )
            self.user = {
                "id": u.id,
                "username": u.username,
                "role": u.role,
                "company_id": selected["company_id"],
                "company_name": selected["company_name"],
                "branch_id": selected["branch_id"],
                "branch_name": selected["branch_name"],
                "warehouse_id": selected["warehouse_id"],
                "warehouse_name": selected["warehouse_name"],
            }
            self.accept()

class SalesChart(QWidget):
    """Lightweight monthly sales chart drawn with Qt; no extra packages required."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.months = []
        self.values = []
        self.setMinimumHeight(220)

    def set_data(self, months, values):
        self.months = list(months)
        self.values = [float(v) for v in values]
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor("#FFFFFF"))
        rect = self.rect().adjusted(42, 18, -12, -34)
        if not self.values:
            painter.setPen(QColor("#64748B"))
            painter.drawText(rect, Qt.AlignCenter, "No sales data available yet")
            painter.end()
            return

        max_value = max(self.values) or 1.0
        painter.setPen(QPen(QColor("#E8EDF5"), 1))
        for i in range(4):
            y = rect.bottom() - (rect.height() * i / 3)
            painter.drawLine(int(rect.left()), int(y), int(rect.right()), int(y))

        n = len(self.values)
        slot = rect.width() / max(n, 1)
        bar_width = min(30, slot * 0.55)
        for i, value in enumerate(self.values):
            bar_height = (value / max_value) * max(1, rect.height() - 8)
            x = rect.left() + i * slot + (slot - bar_width) / 2
            y = rect.bottom() - bar_height
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#4776E6"))
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_height), 4, 4)
            painter.setPen(QColor("#64748B"))
            painter.setFont(QFont("Segoe UI", 8))
            label = self.months[i] if i < len(self.months) else ""
            painter.drawText(QRectF(rect.left() + i * slot, rect.bottom() + 7, slot, 22), Qt.AlignHCenter | Qt.AlignTop, label)
        painter.end()


class MainWindow(QMainWindow):
    def __init__(self, user):
        super().__init__()
        self.user = user
        self.setWindowTitle("GST Billing System — Wholesale")
        self.resize(1440, 900)
        self.setMinimumSize(1100, 700)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(225)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(12, 22, 12, 16)
        sidebar_layout.setSpacing(8)

        brand = QLabel("GST BILLING\nWHOLESALE")
        brand.setObjectName("brand")
        brand.setAlignment(Qt.AlignCenter)
        sidebar_layout.addWidget(brand)
        sidebar_layout.addSpacing(18)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        self.navigation.setSpacing(5)
        sidebar_layout.addWidget(self.navigation, 1)

        self.logout_button = QPushButton("↪   Logout")
        self.logout_button.setObjectName("logoutButton")
        self.logout_button.clicked.connect(self.logout)
        sidebar_layout.addWidget(self.logout_button)

        content = QWidget()
        content.setObjectName("mainContent")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 18, 24, 18)
        content_layout.setSpacing(16)

        header = QFrame()
        header.setObjectName("topHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(18, 12, 18, 12)

        self.page_title = QLabel("Dashboard Overview")
        self.page_title.setObjectName("pageTitle")
        user_label = QLabel(
            f"{self.user['username']}  ·  {self.user['role']}  ·  "
            f"{self.user['company_name']} / {self.user['branch_name']} / {self.user['warehouse_name']}"
        )
        user_label.setObjectName("userLabel")
        header_layout.addWidget(self.page_title)
        header_layout.addStretch()
        header_layout.addWidget(user_label)
        content_layout.addWidget(header)

        self.pages_stack = QStackedWidget()
        content_layout.addWidget(self.pages_stack)
        main_layout.addWidget(sidebar)
        main_layout.addWidget(content, 1)

        page_specs = [
            ("▦   Dashboard", "Dashboard Overview", self.dashboard_tab),
            ("♙   Customers", "Customers & Parties", self.customers_tab),
            ("▣   Products & Stock", "Products & Stock", self.products_tab),
            ("♧   Suppliers", "Supplier Management", self.suppliers_tab),
            ("↓   Purchases / Stock In", "Purchases & Stock In", self.purchases_tab),
            ("▤   Invoices", "Invoices", self.invoice_workspace_tab),
            ("▥   Reports", "Sales & GST Reports", self.reports_tab),
        ]
        if user["role"] == "admin":
            page_specs.extend([
                ("♙   Users", "User Management", self.users_tab),
                ("⚙   Business Settings", "Business Settings", self.settings_tab),
            ])

        self.page_titles = []
        for nav_text, title, page_builder in page_specs:
            page = page_builder()

            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setWidget(page)
            self.pages_stack.addWidget(scroll)

            nav_item = QListWidgetItem(nav_text)
            nav_item.setData(Qt.UserRole, title)
            self.navigation.addItem(nav_item)
            self.page_titles.append(title)

        self.navigation.currentRowChanged.connect(self.change_page)
        self.navigation.setCurrentRow(0)
        self.statusBar().showMessage(
            f"Signed in as {user['username']} ({user['role']})"
        )

        self.setStyleSheet(self.styleSheet() + """
            QMainWindow { background: #F3F6FB; }
            #sidebar { background: #151526; border: none; }
            #brand {
                color: #FFFFFF; font-size: 19px; font-weight: 700;
                padding: 12px 4px;
            }
            #navigation {
                background: transparent; border: none; outline: none;
                color: #D5D7E4; font-size: 10pt;
            }
            #navigation::item {
                padding: 13px 12px; margin: 2px 0; border-radius: 8px;
            }
            #navigation::item:selected {
                background: #303047; color: #FFFFFF; font-weight: 600;
            }
            #navigation::item:hover:!selected {
                background: #24243A; color: #FFFFFF;
            }
            QPushButton#logoutButton {
                background-color: #29293F;
                color: #FFFFFF;
                border: 1px solid #42425A;
                border-radius: 8px;
                padding: 12px;
                text-align: left;
            }
            QPushButton#logoutButton:hover {
                background-color: #B91C1C;
                border-color: #B91C1C;
            }
            #mainContent { background: #F3F6FB; }
            #topHeader {
                background: #FFFFFF; border: 1px solid #E8EDF5;
                border-radius: 10px;
            }
            #pageTitle { color: #172033; font-size: 17px; font-weight: 700; }
            #userLabel { color: #64748B; font-size: 10pt; padding: 5px; }
            QPushButton#userPasswordButton {
                background-color: #EEF4FF; color: #1D4ED8; border: 1px solid #BFDBFE;
                border-radius: 6px; padding: 2px 8px; min-height: 28px; max-height: 28px;
            }
            QPushButton#userPasswordButton:hover { background-color: #DBEAFE; }
            QStackedWidget { background: transparent; border: none; }
            #dashboardPanel { background: #FFFFFF; border: 1px solid #E5EAF2; border-radius: 10px; }
            QStatusBar { background: #FFFFFF; color: #64748B; }
        """)

    def change_page(self, index):
        if index < 0 or index >= self.pages_stack.count():
            return
        self.pages_stack.setCurrentIndex(index)
        self.page_title.setText(self.page_titles[index])

    def logout(self):
        global _active_window, _active_login_dialog

        answer = QMessageBox.question(
            self,
            "Confirm Logout",
            "Are you sure you want to log out?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        self.hide()
        _active_login_dialog = LoginDialog()
        if (
            _active_login_dialog.exec() == QDialog.Accepted
            and _active_login_dialog.user
        ):
            _active_window = MainWindow(_active_login_dialog.user)
            _active_window.show()
            self.close()
        else:
            self.close()
            QApplication.instance().quit()

    def dashboard_tab(self):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(14)

        heading = QLabel("Business Overview")
        heading.setStyleSheet("font-size: 21px; font-weight: 700; color: #172033;")
        subtitle = QLabel("Monitor sales, invoices and inventory in one place.")
        subtitle.setStyleSheet("color: #64748B; font-size: 10pt;")
        layout.addWidget(heading)
        layout.addWidget(subtitle)

        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(12)
        self.sales_card = self.create_dashboard_card("TODAY'S SALES", "₹0.00", "#2563EB")
        self.outstanding_card = self.create_dashboard_card("OUTSTANDING", "₹0.00", "#D97706")
        self.stock_card = self.create_dashboard_card("LOW-STOCK PRODUCTS", "0", "#DC2626")
        self.invoice_count_card = self.create_dashboard_card("ISSUED INVOICES", "0", "#059669")
        for card in (self.sales_card, self.outstanding_card, self.stock_card, self.invoice_count_card):
            cards_layout.addWidget(card)
        layout.addLayout(cards_layout)

        lower = QHBoxLayout()
        lower.setSpacing(14)

        chart_panel = QFrame()
        chart_panel.setObjectName("dashboardPanel")
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(14, 12, 14, 12)
        chart_title = QLabel("Monthly Sales Overview")
        chart_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #172033;")
        chart_layout.addWidget(chart_title)
        self.sales_chart = SalesChart()
        chart_layout.addWidget(self.sales_chart)
        lower.addWidget(chart_panel, 3)

        stock_panel = QFrame()
        stock_panel.setObjectName("dashboardPanel")
        stock_layout = QVBoxLayout(stock_panel)
        stock_layout.setContentsMargins(14, 12, 14, 12)
        stock_title = QLabel("Product Stock & Alerts")
        stock_title.setStyleSheet("font-size: 15px; font-weight: 700; color: #172033;")
        stock_layout.addWidget(stock_title)
        self.low_stock_table = QTableWidget(0, 5)
        self.low_stock_table.setHorizontalHeaderLabels(["SKU", "Product", "Available", "Reorder at", "Status"])
        stock_header = self.low_stock_table.horizontalHeader()
        stock_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        stock_header.setSectionResizeMode(1, QHeaderView.Stretch)
        for column in (2, 3, 4):
            stock_header.setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.low_stock_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.low_stock_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.low_stock_table.verticalHeader().setVisible(False)
        self.low_stock_table.setAlternatingRowColors(True)
        self.low_stock_table.setMinimumHeight(190)
        stock_layout.addWidget(self.low_stock_table)
        lower.addWidget(stock_panel, 2)
        layout.addLayout(lower, 3)

        invoices_panel = QFrame()
        invoices_panel.setObjectName("dashboardPanel")
        invoices_layout = QVBoxLayout(invoices_panel)
        invoices_layout.setContentsMargins(14, 12, 14, 12)
        invoices_heading = QLabel("Recent Invoices")
        invoices_heading.setStyleSheet("font-size: 15px; font-weight: 700; color: #172033;")
        invoices_layout.addWidget(invoices_heading)
        self.recent_invoice_table = QTableWidget(0, 5)
        self.recent_invoice_table.setHorizontalHeaderLabels(["Invoice", "Date", "Customer", "Total", "Balance"])
        self.recent_invoice_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.recent_invoice_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.recent_invoice_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.recent_invoice_table.verticalHeader().setVisible(False)
        self.recent_invoice_table.setMinimumHeight(180)
        self.recent_invoice_table.setMaximumHeight(350)
        invoices_layout.addWidget(self.recent_invoice_table)
        layout.addWidget(invoices_panel, 2)

        actions = QHBoxLayout()
        new_invoice_btn = QPushButton("+  Create Invoice")
        new_invoice_btn.clicked.connect(self.open_create_invoice_tab)
        customers_btn = QPushButton("View Customers")
        customers_btn.clicked.connect(lambda: self.navigation.setCurrentRow(1))
        products_btn = QPushButton("Manage Stock")
        products_btn.clicked.connect(lambda: self.navigation.setCurrentRow(2))
        refresh_btn = QPushButton("Refresh Dashboard")
        refresh_btn.clicked.connect(self.refresh_dashboard)
        actions.addWidget(new_invoice_btn)
        actions.addWidget(customers_btn)
        actions.addWidget(products_btn)
        actions.addStretch()
        actions.addWidget(refresh_btn)
        layout.addLayout(actions)
        self.refresh_dashboard()
        return w

    def create_dashboard_card(self, title, value, accent):
        card = QFrame()
        card.setObjectName("dashboardCard")
        card.setMinimumHeight(112)
        card.setStyleSheet(f"""
            QFrame#dashboardCard {{ background: #FFFFFF; border: 1px solid #E5EAF2;
                border-top: 4px solid {accent}; border-radius: 10px; }}
        """)
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 12, 14, 12)
        card_layout.setSpacing(10)
        title_label = QLabel(title)
        title_label.setStyleSheet("color: #64748B; font-size: 9pt; font-weight: 600; border: none;")
        value_label = QLabel(value)
        value_label.setStyleSheet("color: #111827; font-size: 20px; font-weight: 700; border: none;")
        value_label.setWordWrap(True)
        card_layout.addWidget(title_label)
        card_layout.addWidget(value_label)
        card_layout.addStretch()
        card.value_label = value_label
        return card

    def refresh_dashboard(self):
        with SessionLocal() as s:
            today = __import__("datetime").date.today()
            invoices = list(s.scalars(select(Invoice).where(Invoice.company_id == self.user["company_id"]).order_by(Invoice.invoice_date.desc())))
            issued = [inv for inv in invoices if inv.status == "issued"]
            sales = sum((Decimal(x.grand_total) for x in issued if x.invoice_date.date() == today), Decimal("0"))
            outstanding = sum((max(Decimal("0"), Decimal(x.grand_total) - Decimal(x.amount_paid)) for x in issued), Decimal("0"))
            products = list(s.scalars(select(Product).where(Product.company_id == self.user["company_id"], Product.active.is_(True)).order_by(Product.name)))
            low_products = [p for p in products if Decimal(p.stock_qty) <= Decimal(p.reorder_level)]

            # Last six calendar months, including the current month.
            from datetime import date
            now = date.today()
            month_keys = []
            year, month = now.year, now.month
            for _ in range(6):
                month_keys.append((year, month))
                month -= 1
                if month == 0:
                    month, year = 12, year - 1
            month_keys.reverse()
            monthly_values = []
            month_labels = []
            for y, m in month_keys:
                monthly_values.append(sum((Decimal(inv.grand_total) for inv in issued
                    if inv.invoice_date.year == y and inv.invoice_date.month == m), Decimal("0")))
                month_labels.append(date(y, m, 1).strftime("%b"))

            recent = issued[:7]
            recent_rows = []
            for inv in recent:
                customer = s.scalar(select(Customer).where(Customer.id == inv.customer_id, Customer.company_id == self.user["company_id"]))
                balance = max(Decimal("0"), Decimal(inv.grand_total) - Decimal(inv.amount_paid))
                recent_rows.append((inv.invoice_number, inv.invoice_date.strftime("%d-%m-%Y"),
                                    customer.name if customer else "", f"₹{Decimal(inv.grand_total):,.2f}", f"₹{balance:,.2f}"))

            # Put products that need attention first, while keeping the full active
            # catalogue visible in the dashboard table.
            dashboard_products = sorted(
                products,
                key=lambda p: (
                    Decimal(str(p.stock_qty or 0)) > Decimal(str(p.reorder_level or 0)),
                    Decimal(str(p.stock_qty or 0)),
                    p.name.casefold(),
                ),
            )
            stock_rows = [
                (p.sku, p.name, f"{Decimal(str(p.stock_qty or 0)):,.3f} {p.unit}",
                 f"{Decimal(str(p.reorder_level or 0)):,.3f} {p.unit}",
                 "LOW STOCK" if Decimal(str(p.stock_qty or 0)) <= Decimal(str(p.reorder_level or 0)) else "In stock",
                 Decimal(str(p.stock_qty or 0)) <= Decimal(str(p.reorder_level or 0)))
                for p in dashboard_products
            ]

        self.sales_card.value_label.setText(f"₹{sales:,.2f}")
        self.outstanding_card.value_label.setText(f"₹{outstanding:,.2f}")
        self.stock_card.value_label.setText(str(len(low_products)))
        self.invoice_count_card.value_label.setText(str(len(issued)))
        self.sales_chart.set_data(month_labels, monthly_values)

        self.recent_invoice_table.setRowCount(len(recent_rows))
        for r, values in enumerate(recent_rows):
            for c, value in enumerate(values):
                self.recent_invoice_table.setItem(r, c, item(value))

        self.low_stock_table.setRowCount(max(1, len(stock_rows)))
        if not stock_rows:
            self.low_stock_table.setItem(0, 0, item("No products added yet"))
            self.low_stock_table.setSpan(0, 0, 1, self.low_stock_table.columnCount())
        else:
            for r, values in enumerate(stock_rows):
                is_low = values[-1]
                for c, value in enumerate(values[:-1]):
                    cell = item(value)
                    if c in (2, 3, 4):
                        cell.setTextAlignment(Qt.AlignCenter)
                    if c == 4:
                        cell.setForeground(QColor("#B91C1C" if is_low else "#047857"))
                        cell.setBackground(QColor("#FEF2F2" if is_low else "#ECFDF5"))
                        font = cell.font(); font.setBold(True); cell.setFont(font)
                    self.low_stock_table.setItem(r, c, cell)

    def _row_actions(self, entity_type, entity_id):
        box = QWidget()
        layout = QHBoxLayout(box)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignCenter)
        view_btn = QPushButton("View")
        edit_btn = QPushButton("Edit")
        for button in (view_btn, edit_btn):
            button.setObjectName("rowActionButton")
            button.setFixedSize(76, 30)
            button.setStyleSheet("QPushButton#rowActionButton { padding: 3px 8px; min-height: 0; max-height: 30px; }")
        view_btn.clicked.connect(lambda checked=False, t=entity_type, i=entity_id: self.view_record(t, i))
        edit_btn.clicked.connect(lambda checked=False, t=entity_type, i=entity_id: self.edit_record(t, i))
        layout.addWidget(view_btn)
        layout.addWidget(edit_btn)
        return box

    def _purchase_row_actions(self, purchase_id, due):
        box = QWidget(); layout = QHBoxLayout(box)
        layout.setContentsMargins(2, 2, 2, 2); layout.setSpacing(4); layout.setAlignment(Qt.AlignCenter)
        actions = [("View", lambda checked=False, i=purchase_id: self.view_record("purchase", i)),
                   ("Edit", lambda checked=False, i=purchase_id: self.edit_record("purchase", i))]
        if due > 0:
            actions.append(("Pay", lambda checked=False, i=purchase_id: self.pay_supplier_purchase(i)))
        for label, callback in actions:
            button = QPushButton(label); button.setFixedSize(70, 30)
            button.setStyleSheet("QPushButton { padding: 2px 5px; min-height: 0; max-height: 30px; }")
            button.clicked.connect(callback); layout.addWidget(button)
        return box

    def pay_supplier_purchase(self, purchase_id):
        with SessionLocal() as session:
            purchase = session.scalar(select(Purchase).where(Purchase.id == int(purchase_id), Purchase.company_id == self.user["company_id"]))
            if not purchase: show_error(self, "Purchase not found."); return
            due = money(Decimal(str(purchase.grand_total)) - Decimal(str(purchase.amount_paid or 0)))
            number = purchase.purchase_number
        if due <= 0:
            QMessageBox.information(self, "Already paid", "This purchase has no outstanding balance."); return
        dialog = SupplierPaymentDialog(number, due, self)
        if dialog.exec() != QDialog.Accepted: return
        try:
            record_supplier_payment(purchase_id, dialog.amount.value(), dialog.method.currentText(),
                                    dialog.reference.text(), self.user["username"],
                                    company_id=self.user["company_id"])
            self.refresh_purchases()
            self.refresh_suppliers()
            QMessageBox.information(self, "Payment recorded", f"Supplier payment for {number} recorded.")
        except Exception as exc: show_error(self, exc)

    def view_record(self, entity_type, entity_id):
        models = {"customer": Customer, "product": Product, "supplier": Supplier, "purchase": Purchase}
        customer_account = None
        invoice_rows = []
        payment_rows = []
        with SessionLocal() as session:
            obj = session.scalar(select(models[entity_type]).where(models[entity_type].id == int(entity_id), models[entity_type].company_id == self.user["company_id"]))
            if not obj:
                QMessageBox.warning(self, "Not found", "This record no longer exists.")
                return
            if entity_type == "customer":
                invoices = list(session.scalars(select(Invoice).where(Invoice.company_id == self.user["company_id"], Invoice.customer_id == obj.id, Invoice.status == "issued")))
                total_billed = sum((Decimal(str(inv.grand_total or 0)) for inv in invoices), Decimal("0.00"))
                total_paid = sum((Decimal(str(inv.amount_paid or 0)) for inv in invoices), Decimal("0.00"))
                total_due = total_billed - total_paid
                details = (f"Name: {obj.name}\nGSTIN: {obj.gstin}\nState: {obj.state_code}\nPhone: {obj.phone}\nEmail: {obj.email}\nAddress: {obj.address}\n\nCredit limit: ₹{Decimal(str(obj.credit_limit or 0)):.2f}\nTotal purchases: ₹{total_billed:.2f}\nTotal paid: ₹{total_paid:.2f}\nOutstanding due: ₹{total_due:.2f}\n\nInvoice history:")
                for inv in sorted(invoices, key=lambda x: x.invoice_date or __import__('datetime').datetime.min, reverse=True):
                    details += f"\n{inv.invoice_number} | {inv.invoice_date:%d-%m-%Y} | Total ₹{inv.grand_total:.2f} | Paid ₹{inv.amount_paid:.2f} | Due ₹{(Decimal(str(inv.grand_total))-Decimal(str(inv.amount_paid))):.2f}"
                payments = list(session.scalars(select(Payment).join(Invoice).where(Payment.company_id == self.user["company_id"], Invoice.company_id == self.user["company_id"], Invoice.customer_id == obj.id).order_by(Payment.paid_at.desc())))
                for inv in sorted(invoices, key=lambda x: x.invoice_date or __import__('datetime').datetime.min, reverse=True):
                    billed = Decimal(str(inv.grand_total or 0)); paid = Decimal(str(inv.amount_paid or 0)); due = billed - paid
                    invoice_rows.append((inv.id, inv.invoice_number, inv.invoice_date.strftime('%d-%m-%Y') if inv.invoice_date else '—', f"₹{billed:,.2f}", f"₹{paid:,.2f}", f"₹{due:,.2f}", "Paid" if due <= 0 else ("Partially Paid" if paid > 0 else "Unpaid")))
                for payment in payments:
                    inv = session.scalar(select(Invoice).where(Invoice.id == payment.invoice_id, Invoice.company_id == self.user["company_id"]))
                    payment_rows.append((payment.paid_at.strftime('%d-%m-%Y %H:%M') if payment.paid_at else '—', inv.invoice_number if inv else '—', f"₹{Decimal(str(payment.amount or 0)):,.2f}", payment.method or '—', payment.reference or '—'))
                customer_account = {"id": obj.id, "name": obj.name, "phone": obj.phone, "email": obj.email, "gstin": obj.gstin, "state_code": obj.state_code, "address": obj.address, "limit": Decimal(str(obj.credit_limit or 0)), "billed": total_billed, "paid": total_paid, "due": total_due}
            elif entity_type == "product":
                details = f"SKU: {obj.sku}\nName: {obj.name}\nHSN/SAC: {obj.hsn_sac}\nUnit: {obj.unit}\nSelling price: ₹{obj.selling_price}\nPurchase price: ₹{obj.purchase_price}\nGST: {obj.gst_rate}%\nCurrent stock: {obj.stock_qty}\nReorder level: {obj.reorder_level}"
            elif entity_type == "supplier":
                details = f"Name: {obj.name}\nGSTIN: {obj.gstin}\nState: {obj.state_code}\nPhone: {obj.phone}\nAddress: {obj.address}"
            else:
                supplier = session.scalar(select(Supplier).where(Supplier.id == obj.supplier_id, Supplier.company_id == self.user["company_id"]))
                lines = list(session.scalars(select(PurchaseItem).where(PurchaseItem.purchase_id == obj.id)))
                paid = Decimal(str(obj.amount_paid or 0)); due = Decimal(str(obj.grand_total or 0)) - paid
                details = f"Purchase: {obj.purchase_number}\nDate: {obj.purchase_date:%d-%m-%Y}\nSupplier: {supplier.name if supplier else ''}\nSupplier invoice: {obj.supplier_invoice_number}\nTaxable: ₹{obj.taxable_total}\nTax: ₹{obj.tax_total}\nGrand total: ₹{obj.grand_total}\nPaid: ₹{paid:.2f}\nDue: ₹{due:.2f}"
                for line in lines:
                    details += f"\n\nProduct: {line.description_snapshot} ({line.sku_snapshot})\nQuantity: {line.quantity}\nUnit cost: ₹{line.unit_cost}\nLine total: ₹{line.line_total}"
                payments = list(session.scalars(select(SupplierPayment).where(SupplierPayment.company_id == self.user["company_id"], SupplierPayment.purchase_id == obj.id).order_by(SupplierPayment.paid_at)))
                if payments:
                    details += "\n\nPayment history:"
                    for payment in payments:
                        date_text = payment.paid_at.strftime("%d-%m-%Y") if payment.paid_at else "—"
                        details += f"\n{date_text} | ₹{payment.amount:.2f} | {payment.method} | {payment.reference or '—'}"
        if entity_type == "customer" and customer_account is not None:
            dialog = CustomerAccountDialog(customer_account, invoice_rows, payment_rows, self)
            dialog.exec()
        else:
            dialog = QDialog(self)
            dialog.setWindowTitle(f"View {entity_type.title()}")
            dialog.resize(620, 480)
            dialog.setStyleSheet("QDialog{background:#F4F7FB;} QLabel{color:#1E293B;} QTextEdit{background:white;border:1px solid #DCE4EF;border-radius:8px;padding:12px;font-size:13px;}")
            layout = QVBoxLayout(dialog)
            heading = QLabel(f"{entity_type.title()} Details")
            heading.setStyleSheet("font-size:20px;font-weight:700;padding:4px;")
            layout.addWidget(heading)
            from PySide6.QtWidgets import QTextEdit
            content = QTextEdit(); content.setReadOnly(True); content.setPlainText(details)
            layout.addWidget(content)
            buttons = QDialogButtonBox(QDialogButtonBox.Close); buttons.rejected.connect(dialog.reject); buttons.accepted.connect(dialog.accept)
            layout.addWidget(buttons)
            dialog.exec()

    def edit_record(self, entity_type, entity_id):
        if entity_type == "purchase":
            self.edit_purchase_record(entity_id)
            return
        models = {"customer": Customer, "product": Product, "supplier": Supplier}
        with SessionLocal() as session:
            obj = session.scalar(select(models[entity_type]).where(models[entity_type].id == int(entity_id), models[entity_type].company_id == self.user["company_id"]))
            if not obj:
                QMessageBox.warning(self, "Not found", "This record no longer exists.")
                return
            values = {"customer": {
                "Name": ("name", "text"), "GSTIN": ("gstin", "text"), "State code": ("state_code", "text"),
                "Phone": ("phone", "text"), "Email": ("email", "text"), "Address": ("address", "text"), "Credit limit (₹)": ("credit_limit", "money")},
                "product": {"SKU": ("sku", "text"), "Product name": ("name", "text"), "HSN/SAC": ("hsn_sac", "text"),
                "Unit": ("unit", "unit"), "Selling price": ("selling_price", "money"), "Purchase price": ("purchase_price", "money"),
                "GST rate (%)": ("gst_rate", "gst"), "Current stock quantity": ("stock_qty", "qty"), "Reorder level": ("reorder_level", "qty")},
                "supplier": {"Name": ("name", "text"), "GSTIN": ("gstin", "text"), "State code": ("state_code", "text"),
                "Phone": ("phone", "text"), "Address": ("address", "text")}}[entity_type]
            original = {attr: getattr(obj, attr) for attr, _kind in values.values()}
        dialog = QDialog(self); dialog.setWindowTitle(f"Edit {entity_type.title()}"); dialog.setMinimumWidth(520)
        form = QFormLayout(); form.setSpacing(10); controls = {}
        for label, (attr, kind) in values.items():
            val = original[attr]
            if kind == "text":
                widget = QLineEdit(str(val or ""))
            elif kind == "unit":
                widget = QComboBox(); widget.addItems(["Nos", "Kg", "Gm", "Ltr", "Mtr", "Box", "Pack"])
                idx = widget.findText(str(val or "Nos")); widget.setCurrentIndex(max(0, idx))
            elif kind == "gst":
                widget = QComboBox(); widget.addItems(["0", "0.1", "0.25", "3", "5", "12", "18", "28"])
                idx = widget.findText(str(val));
                if idx < 0: widget.addItem(str(val)); idx = widget.findText(str(val))
                widget.setCurrentIndex(idx)
            else:
                widget = QDoubleSpinBox(); widget.setRange(0, 999999999); widget.setDecimals(3 if kind == "qty" else 2)
                widget.setValue(float(val or 0))
                if kind == "money": widget.setPrefix("₹ ")
            controls[attr] = widget; form.addRow(label, widget)
        layout = QVBoxLayout(dialog); layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted: return
        updates = {}
        for attr, widget in controls.items():
            if isinstance(widget, QLineEdit): value = widget.text().strip()
            elif isinstance(widget, QComboBox): value = widget.currentText()
            else: value = Decimal(str(widget.value()))
            if attr == "gstin": value = value.upper()
            updates[attr] = value
        if entity_type in ("customer", "supplier") and (not updates.get("name", "").strip() or len(updates.get("state_code", "")) != 2 or not updates["state_code"].isdigit()):
            QMessageBox.warning(self, "Invalid data", "Name and a valid two-digit state code are required."); return
        if entity_type == "product" and (not updates["sku"].strip() or not updates["name"].strip()):
            QMessageBox.warning(self, "Invalid data", "SKU and product name are required."); return
        try:
            with SessionLocal.begin() as session:
                obj = session.scalar(select(models[entity_type]).where(models[entity_type].id == int(entity_id), models[entity_type].company_id == self.user["company_id"]))
                if entity_type == "product":
                    old_stock = Decimal(str(obj.stock_qty)); new_stock = Decimal(str(updates["stock_qty"]))
                    if new_stock < 0: raise ValueError("Stock cannot be negative.")
                    delta = new_stock - old_stock
                else: delta = Decimal("0")
                for attr, value in updates.items(): setattr(obj, attr, value)
                if entity_type == "product" and delta:
                    session.add(StockMovement(company_id=self.user["company_id"], branch_id=self.user["branch_id"], warehouse_id=self.user["warehouse_id"], product_id=obj.id, quantity_delta=delta, reason="stock_adjustment", reference="MANUAL-EDIT", created_by=self.user["username"]))
                session.add(AuditLog(company_id=self.user["company_id"], username=self.user["username"], action=f"{entity_type}_updated", entity_type=entity_type, entity_id=str(obj.id), details=f"Updated {entity_type} record"))
            self.refresh_customers(); self.refresh_products(); self.refresh_suppliers()
            self.refresh_invoice_options(); self.refresh_purchase_options(); self.refresh_dashboard()
        except Exception as exc: show_error(self, exc)

    def edit_purchase_record(self, purchase_id):
        with SessionLocal() as session:
            purchase = session.scalar(select(Purchase).where(Purchase.id == int(purchase_id), Purchase.company_id == self.user["company_id"]))
            if not purchase:
                QMessageBox.warning(self, "Not found", "Purchase not found."); return
            lines = list(session.scalars(select(PurchaseItem).where(PurchaseItem.purchase_id == purchase.id)))
            supplier_id = purchase.supplier_id; old_invoice = purchase.supplier_invoice_number
            old_date = purchase.purchase_date.date()
        dialog = QDialog(self); dialog.setWindowTitle("Edit Purchase"); dialog.setMinimumSize(850, 530)
        root = QVBoxLayout(dialog); form = QFormLayout()
        supplier = QComboBox(); vendor_invoice = QLineEdit(old_invoice)
        purchase_date = QDateEdit(QDate(old_date.year, old_date.month, old_date.day)); purchase_date.setCalendarPopup(True); purchase_date.setDisplayFormat("dd-MM-yyyy")
        with SessionLocal() as session:
            for obj in session.scalars(select(Supplier).where(Supplier.company_id == self.user["company_id"], Supplier.active.is_(True)).order_by(Supplier.name)):
                supplier.addItem(obj.name, obj.id)
            products = list(session.scalars(select(Product).where(Product.company_id == self.user["company_id"]).order_by(Product.name)))
        supplier.setCurrentIndex(max(0, supplier.findData(supplier_id)))
        form.addRow("Supplier", supplier); form.addRow("Supplier invoice number", vendor_invoice); form.addRow("Invoice date", purchase_date)
        root.addLayout(form)
        table = QTableWidget(0, 5); table.setHorizontalHeaderLabels(["Product", "Quantity", "Unit cost", "GST %", ""])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in [(1, 110), (2, 140), (3, 100), (4, 48)]: table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed); table.setColumnWidth(col, width)
        root.addWidget(table); entries = []

        def append_line(product_id=None, quantity=1, unit_cost=0, gst_rate=0):
            row = table.rowCount(); table.insertRow(row)
            product_box = QComboBox()
            for obj in products: product_box.addItem(f"{obj.sku} — {obj.name}", obj.id)
            if product_id is not None: product_box.setCurrentIndex(max(0, product_box.findData(product_id)))
            qty_box = QDoubleSpinBox(); qty_box.setRange(0.001, 999999999); qty_box.setDecimals(3); qty_box.setValue(quantity)
            cost_box = QDoubleSpinBox(); cost_box.setRange(0, 999999999); cost_box.setDecimals(2); cost_box.setPrefix("₹ "); cost_box.setValue(unit_cost)
            gst_box = QDoubleSpinBox(); gst_box.setRange(0, 100); gst_box.setDecimals(2); gst_box.setValue(gst_rate)
            remove = QPushButton("×"); remove.setFixedSize(32, 28)
            entry = {"product": product_box, "quantity": qty_box, "cost": cost_box, "gst": gst_box}
            entries.append(entry)
            for col, widget in enumerate((product_box, qty_box, cost_box, gst_box, remove)): table.setCellWidget(row, col, widget)
            product_box.currentIndexChanged.connect(lambda _=0, p=product_box, g=gst_box: self.set_purchase_product_gst(p, g))
            remove.clicked.connect(lambda checked=False, entry=entry: remove_edit_line(entry))

        def remove_edit_line(entry):
            index = entries.index(entry); table.removeRow(index); entries.pop(index)

        for line in lines:
            append_line(line.product_id, float(line.quantity), float(line.unit_cost), float(line.gst_rate_snapshot))
        add_line = QPushButton("+ Add product line"); add_line.clicked.connect(lambda: append_line())
        root.addWidget(add_line)
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); root.addWidget(buttons)
        if dialog.exec() != QDialog.Accepted: return
        updated_lines = [{"product_id": e["product"].currentData(), "quantity": e["quantity"].value(),
                          "unit_cost": e["cost"].value(), "gst_rate": e["gst"].value()} for e in entries]
        try:
            update_purchase(purchase_id, supplier.currentData(), vendor_invoice.text(), updated_lines,
                            self.user["username"], purchase_date.date().toPython(),
                            company_id=self.user["company_id"])
            self.refresh_purchases(); self.refresh_products(); self.refresh_suppliers(); self.refresh_dashboard()
        except Exception as exc: show_error(self, exc)

    def customers_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(14)

        # Heading and Add button
        header = QHBoxLayout()

        title_box = QVBoxLayout()
        title = QLabel("Customers & Parties")
        title.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #172033;"
        )
        subtitle = QLabel("Manage your customer records.")
        subtitle.setStyleSheet("color: #64748B;")

        title_box.addWidget(title)
        title_box.addWidget(subtitle)

        add_button = QPushButton("+ Add Customer")
        add_button.setMinimumHeight(40)
        add_button.clicked.connect(self.open_customer_dialog)

        header.addLayout(title_box)
        header.addStretch()
        header.addWidget(add_button)
        root.addLayout(header)

        # Only the list is shown by default
        self.customer_table = QTableWidget(0, 7)
        self.customer_table.setHorizontalHeaderLabels([
            "ID", "Name", "GSTIN", "State", "Phone", "Address", "Actions"
        ])
        self.customer_table.setColumnHidden(0, True)
        customer_header = self.customer_table.horizontalHeader()
        customer_header.setSectionResizeMode(QHeaderView.Interactive)
        customer_header.setSectionResizeMode(1, QHeaderView.Stretch)  # Name
        customer_header.setSectionResizeMode(5, QHeaderView.Stretch)  # Address
        self.customer_table.setColumnWidth(1, 180)
        self.customer_table.setColumnWidth(2, 140)
        self.customer_table.setColumnWidth(3, 75)
        self.customer_table.setColumnWidth(4, 145)
        customer_header.setSectionResizeMode(6, QHeaderView.Fixed)
        self.customer_table.setColumnWidth(6, 170)
        self.customer_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.customer_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.customer_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.customer_table.setAlternatingRowColors(True)
        self.customer_table.verticalHeader().setVisible(False)
        self.customer_table.verticalHeader().setDefaultSectionSize(42)
        self.customer_table.setColumnWidth(6, 170)

        root.addWidget(self.customer_table)
        self.refresh_customers()
        return w

    def open_customer_dialog(self):
        self._customer_dialog = QDialog(self)
        self._customer_dialog.setWindowTitle("Add Customer")
        self._customer_dialog.setMinimumWidth(450)

        layout = QVBoxLayout(self._customer_dialog)
        form = QFormLayout()
        form.setSpacing(12)

        self.c_name = QLineEdit()
        self.c_name.setPlaceholderText("Enter customer name")

        self.c_gstin = QLineEdit()
        self.c_gstin.setPlaceholderText("Optional GSTIN")

        self.c_state = QLineEdit("32")
        self.c_state.setMaxLength(2)

        self.c_phone = QLineEdit()
        self.c_phone.setPlaceholderText("Phone number")

        self.c_email = QLineEdit()
        self.c_email.setPlaceholderText("Email address")

        self.c_address = QLineEdit()
        self.c_address.setPlaceholderText("Address")

        self.c_credit_limit = QDoubleSpinBox()
        self.c_credit_limit.setRange(0, 999999999)
        self.c_credit_limit.setDecimals(2)
        self.c_credit_limit.setValue(10000)
        self.c_credit_limit.setPrefix("₹ ")

        form.addRow("Customer name *", self.c_name)
        form.addRow("GSTIN", self.c_gstin)
        form.addRow("State code *", self.c_state)
        form.addRow("Phone", self.c_phone)
        form.addRow("Email", self.c_email)
        form.addRow("Address", self.c_address)
        form.addRow("Credit limit", self.c_credit_limit)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton("Save Customer")
        cancel = QPushButton("Cancel")

        save.clicked.connect(self.save_customer)
        cancel.clicked.connect(self._customer_dialog.reject)

        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._customer_dialog.exec()

    def save_customer(self):
        name = self.c_name.text().strip()
        state = self.c_state.text().strip()

        if not name or len(state) != 2 or not state.isdigit():
            show_error(
                self,
                "Customer name and a valid two-digit state code are required."
            )
            return

        try:
            add_customer(
                name,
                self.c_gstin.text().strip(),
                state,
                self.c_address.text().strip(),
                self.c_phone.text().strip(),
                self.c_email.text().strip(),
                credit_limit=self.c_credit_limit.value(),
                company_id=self.user["company_id"],
            )

            self.refresh_customers()
            self.refresh_invoice_options()

            QMessageBox.information(
                self, "Success", "Customer added successfully."
            )
            self._customer_dialog.accept()

        except Exception as e:
            show_error(self, e)

    def refresh_customers(self):
        with SessionLocal() as s:
            rows = list(s.scalars(select(Customer).where(Customer.company_id == self.user["company_id"], Customer.active.is_(True)).order_by(Customer.name)))
            self.customer_table.setRowCount(len(rows))
            for r, c in enumerate(rows):
                for col, val in enumerate([c.id, c.name, c.gstin, c.state_code, c.phone, c.address]):
                    self.customer_table.setItem(r, col, item(val))
                self.customer_table.setCellWidget(r, 6, self._row_actions("customer", c.id))

    def products_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(18, 18, 18, 18); root.setSpacing(14)
        header = QHBoxLayout(); title_box = QVBoxLayout()
        title = QLabel("Products & Stock"); title.setStyleSheet("font-size:24px;font-weight:700;color:#172033;")
        subtitle = QLabel("Your product catalogue, available stock and reorder levels."); subtitle.setStyleSheet("color:#64748B;font-size:12px;")
        title_box.addWidget(title); title_box.addWidget(subtitle)
        add_button = QPushButton("＋  Add Product"); add_button.setMinimumHeight(42); add_button.clicked.connect(self.open_product_dialog)
        header.addLayout(title_box); header.addStretch(); header.addWidget(add_button); root.addLayout(header)

        metrics = QHBoxLayout(); metrics.setSpacing(12)
        self.product_metric_labels = {}
        for key, label, color in [("products", "ACTIVE PRODUCTS", "#2563EB"), ("low", "LOW STOCK", "#DC2626"),
                                  ("in_stock", "PRODUCTS IN STOCK", "#059669"), ("value", "STOCK VALUE", "#7C3AED")]:
            card, value_label = self._metric_card(label, "—", color)
            self.product_metric_labels[key] = value_label; metrics.addWidget(card, 1)
        root.addLayout(metrics)

        controls = QHBoxLayout(); self.product_search = QLineEdit(); self.product_search.setPlaceholderText("Search by product name or SKU")
        self.product_search.setClearButtonEnabled(True); self.product_search.textChanged.connect(lambda text: self._filter_table(self.product_table, text, (1, 2)))
        controls.addWidget(self.product_search, 1)
        hint = QLabel("Select a row and use View or Edit for details and stock adjustments."); hint.setStyleSheet("color:#64748B;")
        controls.addWidget(hint); root.addLayout(controls)

        self.product_table = QTableWidget(0, 8)
        self.product_table.setHorizontalHeaderLabels([
            "ID", "SKU", "Product", "Price", "GST %", "Stock", "Reorder", "Actions"
        ])
        self.product_table.setColumnHidden(0, True)
        product_header = self.product_table.horizontalHeader()
        product_header.setSectionResizeMode(QHeaderView.Interactive)
        product_header.setSectionResizeMode(2, QHeaderView.Stretch)  # Product
        self.product_table.setColumnWidth(1, 110)  # SKU
        self.product_table.setColumnWidth(3, 110)  # Price
        self.product_table.setColumnWidth(4, 75)   # GST
        self.product_table.setColumnWidth(5, 95)   # Stock
        self.product_table.setColumnWidth(6, 95)   # Reorder
        product_header.setSectionResizeMode(7, QHeaderView.Fixed)
        self.product_table.setColumnWidth(7, 170)
        self.product_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.product_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.product_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.product_table.setAlternatingRowColors(True)
        self.product_table.verticalHeader().setVisible(False)
        self.product_table.verticalHeader().setDefaultSectionSize(42)
        self.product_table.setColumnWidth(7, 170)

        root.addWidget(self.product_table)
        self.refresh_products()
        return w

    def _metric_card(self, title, value, accent):
        card = QFrame(); card.setObjectName("summaryCard")
        card.setStyleSheet(f"QFrame#summaryCard{{background:#FFFFFF;border:1px solid #E3EAF3;border-left:4px solid {accent};border-radius:10px;}}")
        layout = QVBoxLayout(card); layout.setContentsMargins(15, 12, 15, 12); layout.setSpacing(4)
        label = QLabel(title); label.setStyleSheet("color:#64748B;font-size:10px;font-weight:700;letter-spacing:0.5px;")
        value_label = QLabel(value); value_label.setStyleSheet("color:#172033;font-size:21px;font-weight:700;")
        layout.addWidget(label); layout.addWidget(value_label)
        return card, value_label

    def _filter_table(self, table, text, columns, status_column=None, status_value=None):
        query = text.strip().casefold()
        for row in range(table.rowCount()):
            matches_text = not query or any(
                query in (table.item(row, column).text().casefold() if table.item(row, column) else "")
                for column in columns
            )
            matches_status = not status_value or status_value == "All statuses" or (
                table.item(row, status_column).text() if table.item(row, status_column) else ""
            ) == status_value
            table.setRowHidden(row, not (matches_text and matches_status))

    def open_product_dialog(self):
        self._product_dialog = QDialog(self)
        self._product_dialog.setWindowTitle("Add Product")
        self._product_dialog.setMinimumWidth(540)

        layout = QVBoxLayout(self._product_dialog)
        intro = QLabel("Create the product once. For future stock, record a purchase against this product.")
        intro.setWordWrap(True); intro.setStyleSheet("color:#64748B;padding:4px 2px 10px;")
        layout.addWidget(intro)
        form = QFormLayout()
        form.setSpacing(10)

        self.p_sku = QLineEdit()
        self.p_sku.setPlaceholderText("Unique product SKU")

        self.p_name = QLineEdit()
        self.p_name.setPlaceholderText("Product name")

        self.p_hsn = QLineEdit()
        self.p_hsn.setPlaceholderText("HSN/SAC code")

        self.p_unit = QComboBox()
        self.p_unit.addItems([
            "Nos", "Kg", "Gm", "Ltr", "Mtr", "Box", "Pack"
        ])

        self.p_price = QDoubleSpinBox()
        self.p_price.setRange(0, 999999999)
        self.p_price.setDecimals(2)
        self.p_price.setPrefix("₹ ")

        self.p_purchase = QDoubleSpinBox()
        self.p_purchase.setRange(0, 999999999)
        self.p_purchase.setDecimals(2)
        self.p_purchase.setPrefix("₹ ")

        self.p_gst = QComboBox()
        self.p_gst.addItems([
            "0", "0.1", "0.25", "3", "5", "12", "18", "28"
        ])

        self.p_stock = QDoubleSpinBox()
        self.p_stock.setRange(0, 999999999)
        self.p_stock.setDecimals(3)

        self.p_reorder = QDoubleSpinBox()
        self.p_reorder.setRange(0, 999999999)
        self.p_reorder.setDecimals(3)

        form.addRow("SKU *", self.p_sku)
        form.addRow("Product name *", self.p_name)
        form.addRow("HSN/SAC", self.p_hsn)
        form.addRow("Unit", self.p_unit)
        form.addRow("Selling price", self.p_price)
        form.addRow("Last purchase cost", self.p_purchase)
        form.addRow("GST rate (%)", self.p_gst)
        form.addRow("Opening stock (initial quantity)", self.p_stock)
        form.addRow("Low-stock alert at", self.p_reorder)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton("Save Product")
        cancel = QPushButton("Cancel")

        save.clicked.connect(self.save_product)
        cancel.clicked.connect(self._product_dialog.reject)

        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._product_dialog.exec()

    def save_product(self):
        sku = self.p_sku.text().strip()
        name = self.p_name.text().strip()

        if not sku or not name:
            show_error(self, "SKU and product name are required.")
            return

        try:
            add_product(
                sku,
                name,
                self.p_hsn.text().strip(),
                self.p_unit.currentText(),
                self.p_price.value(),
                self.p_purchase.value(),
                self.p_gst.currentText(),
                self.p_stock.value(),
                self.p_reorder.value(),
                company_id=self.user["company_id"],
                branch_id=self.user["branch_id"],
                warehouse_id=self.user["warehouse_id"],
            )

            self.refresh_products()
            self.refresh_invoice_options()
            self.refresh_purchase_options()
            self.refresh_dashboard()

            QMessageBox.information(
                self, "Success", "Product added successfully."
            )
            self._product_dialog.accept()

        except Exception as e:
            show_error(self, e)

    def refresh_products(self):
        with SessionLocal() as s:
            rows = list(s.scalars(select(Product).where(Product.company_id == self.user["company_id"], Product.active.is_(True)).order_by(Product.name)))
            self.product_table.setRowCount(len(rows))
            low_count = 0; in_stock_count = 0; stock_value = Decimal("0.00")
            for r, p in enumerate(rows):
                stock = Decimal(str(p.stock_qty or 0)); reorder = Decimal(str(p.reorder_level or 0))
                in_stock_count += int(stock > 0); stock_value += stock * Decimal(str(p.purchase_price or 0))
                is_low = stock <= reorder
                low_count += int(is_low)
                vals = [p.id, p.sku, p.name, f"₹{p.selling_price:,.2f}", f"{p.gst_rate}%", f"{stock:,.3f}", f"{reorder:,.3f}"]
                for col, val in enumerate(vals):
                    cell = item(val)
                    if col in (3, 5, 6): cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    if col == 5 and is_low: cell.setForeground(QColor("#B91C1C"))
                    self.product_table.setItem(r, col, cell)
                self.product_table.setCellWidget(r, 7, self._row_actions("product", p.id))
            if hasattr(self, "product_metric_labels"):
                self.product_metric_labels["products"].setText(f"{len(rows):,}")
                self.product_metric_labels["low"].setText(f"{low_count:,}")
                self.product_metric_labels["in_stock"].setText(f"{in_stock_count:,}")
                self.product_metric_labels["value"].setText(f"₹{stock_value:,.2f}")
        if hasattr(self, "product_search"):
            self._filter_table(self.product_table, self.product_search.text(), (1, 2))

    def suppliers_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(18, 18, 18, 18); root.setSpacing(14)
        header = QHBoxLayout(); title_box = QVBoxLayout()
        title = QLabel("Suppliers"); title.setStyleSheet("font-size:24px;font-weight:700;color:#172033;")
        subtitle = QLabel("Manage supplier contacts and keep track of purchasing balances."); subtitle.setStyleSheet("color:#64748B;font-size:12px;")
        title_box.addWidget(title); title_box.addWidget(subtitle)
        add_button = QPushButton("＋  Add Supplier"); add_button.setMinimumHeight(42); add_button.clicked.connect(self.open_supplier_dialog)
        header.addLayout(title_box); header.addStretch(); header.addWidget(add_button); root.addLayout(header)

        metrics = QHBoxLayout(); metrics.setSpacing(12); self.supplier_metric_labels = {}
        for key, label, color in [("suppliers", "ACTIVE SUPPLIERS", "#2563EB"), ("bills", "PURCHASE BILLS", "#0891B2"),
                                  ("purchased", "TOTAL PURCHASED", "#7C3AED"), ("due", "OUTSTANDING DUE", "#DC2626")]:
            card, value_label = self._metric_card(label, "—", color); self.supplier_metric_labels[key] = value_label; metrics.addWidget(card, 1)
        root.addLayout(metrics)
        self.supplier_search = QLineEdit(); self.supplier_search.setPlaceholderText("Search suppliers by name, GSTIN or phone")
        self.supplier_search.setClearButtonEnabled(True); self.supplier_search.textChanged.connect(lambda text: self._filter_table(self.supplier_table, text, (1, 2, 4)))
        root.addWidget(self.supplier_search)

        self.supplier_table = QTableWidget(0, 6)
        self.supplier_table.setHorizontalHeaderLabels([
            "ID", "Name", "GSTIN", "State", "Phone", "Actions"
        ])
        self.supplier_table.setColumnHidden(0, True)
        supplier_header = self.supplier_table.horizontalHeader()
        supplier_header.setSectionResizeMode(QHeaderView.Interactive)
        supplier_header.setSectionResizeMode(1, QHeaderView.Stretch)  # Name
        self.supplier_table.setColumnWidth(2, 150)  # GSTIN
        self.supplier_table.setColumnWidth(3, 75)   # State
        self.supplier_table.setColumnWidth(4, 145)  # Phone
        supplier_header.setSectionResizeMode(5, QHeaderView.Fixed)
        self.supplier_table.setColumnWidth(5, 170)
        self.supplier_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.supplier_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.supplier_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.supplier_table.setAlternatingRowColors(True)
        self.supplier_table.verticalHeader().setVisible(False)
        self.supplier_table.verticalHeader().setDefaultSectionSize(42)
        self.supplier_table.setColumnWidth(5, 170)

        root.addWidget(self.supplier_table)
        self.refresh_suppliers()
        return w

    def open_supplier_dialog(self):
        self._supplier_dialog = QDialog(self)
        self._supplier_dialog.setWindowTitle("Add Supplier")
        self._supplier_dialog.setMinimumWidth(520)

        layout = QVBoxLayout(self._supplier_dialog)
        intro = QLabel("Add supplier details here, then select this supplier when recording a bill.")
        intro.setWordWrap(True); intro.setStyleSheet("color:#64748B;padding:4px 2px 10px;")
        layout.addWidget(intro)
        form = QFormLayout()
        form.setSpacing(12)

        self.sup_name = QLineEdit()
        self.sup_name.setPlaceholderText("Supplier name")

        self.sup_gstin = QLineEdit()
        self.sup_gstin.setPlaceholderText("Optional GSTIN")

        self.sup_state = QLineEdit("32")
        self.sup_state.setMaxLength(2)

        self.sup_phone = QLineEdit()
        self.sup_phone.setPlaceholderText("Phone number")

        self.sup_address = QLineEdit()
        self.sup_address.setPlaceholderText("Supplier address")

        form.addRow("Supplier name *", self.sup_name)
        form.addRow("GSTIN", self.sup_gstin)
        form.addRow("State code *", self.sup_state)
        form.addRow("Phone", self.sup_phone)
        form.addRow("Address", self.sup_address)

        layout.addLayout(form)

        buttons = QHBoxLayout()
        save = QPushButton("Save Supplier")
        cancel = QPushButton("Cancel")

        save.clicked.connect(self.save_supplier)
        cancel.clicked.connect(self._supplier_dialog.reject)

        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

        self._supplier_dialog.exec()

    def save_supplier(self):
        name = self.sup_name.text().strip()
        state = self.sup_state.text().strip()

        if not name or len(state) != 2 or not state.isdigit():
            show_error(
                self,
                "Supplier name and a valid two-digit state code are required."
            )
            return

        try:
            add_supplier(
                name,
                self.sup_gstin.text().strip(),
                state,
                self.sup_address.text().strip(),
                self.sup_phone.text().strip(),
                company_id=self.user["company_id"],
            )

            self.refresh_suppliers()
            self.refresh_purchase_options()

            QMessageBox.information(
                self, "Success", "Supplier added successfully."
            )
            self._supplier_dialog.accept()

        except Exception as e:
            show_error(self, e)

    def refresh_suppliers(self):
        if not hasattr(self, "supplier_table"): return
        with SessionLocal() as s:
            rows = list(s.scalars(select(Supplier).where(Supplier.company_id == self.user["company_id"], Supplier.active.is_(True)).order_by(Supplier.name)))
            purchases = list(s.scalars(select(Purchase).where(Purchase.company_id == self.user["company_id"])))
            total_purchased = sum((Decimal(str(p.grand_total or 0)) for p in purchases), Decimal("0.00"))
            total_due = sum((Decimal(str(p.grand_total or 0)) - Decimal(str(p.amount_paid or 0)) for p in purchases), Decimal("0.00"))
            self.supplier_table.setRowCount(len(rows))
            for r, obj in enumerate(rows):
                for c, val in enumerate([obj.id, obj.name, obj.gstin, obj.state_code, obj.phone]):
                    self.supplier_table.setItem(r, c, item(val))
                self.supplier_table.setCellWidget(r, 5, self._row_actions("supplier", obj.id))
            if hasattr(self, "supplier_metric_labels"):
                self.supplier_metric_labels["suppliers"].setText(f"{len(rows):,}")
                self.supplier_metric_labels["bills"].setText(f"{len(purchases):,}")
                self.supplier_metric_labels["purchased"].setText(f"₹{total_purchased:,.2f}")
                self.supplier_metric_labels["due"].setText(f"₹{total_due:,.2f}")
        if hasattr(self, "supplier_search"):
            self._filter_table(self.supplier_table, self.supplier_search.text(), (1, 2, 4))

    def purchases_tab(self):
        w = QWidget(); root = QVBoxLayout(w)
        root.setContentsMargins(18, 18, 18, 18); root.setSpacing(14)
        header = QHBoxLayout(); title_box = QVBoxLayout()
        title = QLabel("Purchases")
        title.setStyleSheet("font-size:24px;font-weight:700;color:#172033;")
        subtitle = QLabel("Supplier bills, stock received and payments due.")
        subtitle.setStyleSheet("color:#64748B;font-size:12px;")
        title_box.addWidget(title); title_box.addWidget(subtitle)
        add_button = QPushButton("＋  Record Purchase"); add_button.setMinimumHeight(42)
        add_button.clicked.connect(self.open_purchase_dialog)
        header.addLayout(title_box); header.addStretch(); header.addWidget(add_button); root.addLayout(header)

        metrics = QHBoxLayout(); metrics.setSpacing(12); self.purchase_metric_labels = {}
        for key, label, color in [("bills", "PURCHASE BILLS", "#2563EB"), ("total", "TOTAL VALUE", "#7C3AED"),
                                  ("paid", "PAID TO SUPPLIERS", "#059669"), ("due", "OUTSTANDING DUE", "#DC2626")]:
            card, value_label = self._metric_card(label, "—", color); self.purchase_metric_labels[key] = value_label; metrics.addWidget(card, 1)
        root.addLayout(metrics)

        controls = QHBoxLayout(); self.purchase_search = QLineEdit()
        self.purchase_search.setPlaceholderText("Search purchase no., supplier or supplier invoice")
        self.purchase_search.setClearButtonEnabled(True)
        self.purchase_status_filter = QComboBox(); self.purchase_status_filter.addItems(["All statuses", "Unpaid", "Partially paid", "Paid"])
        self.purchase_search.textChanged.connect(self.filter_purchases)
        self.purchase_status_filter.currentTextChanged.connect(self.filter_purchases)
        controls.addWidget(self.purchase_search, 1); controls.addWidget(self.purchase_status_filter)
        root.addLayout(controls)
        self.purchase_table = QTableWidget(0, 10)
        self.purchase_table.setHorizontalHeaderLabels(["Purchase ID", "Purchase no.", "Date", "Supplier", "Taxable", "Total incl. tax", "Paid", "Due", "Status", "Actions"])
        self.purchase_table.setColumnHidden(0, True)
        purchase_header = self.purchase_table.horizontalHeader()
        purchase_header.setSectionResizeMode(QHeaderView.Interactive)
        purchase_header.setSectionResizeMode(3, QHeaderView.Stretch)  # Supplier
        self.purchase_table.setColumnWidth(1, 155)  # Purchase no.
        self.purchase_table.setColumnWidth(2, 125)  # Date
        self.purchase_table.setColumnWidth(4, 125)  # Taxable
        self.purchase_table.setColumnWidth(5, 150)  # Total
        purchase_header.setSectionResizeMode(6, QHeaderView.Fixed); self.purchase_table.setColumnWidth(6, 100)
        purchase_header.setSectionResizeMode(7, QHeaderView.Fixed); self.purchase_table.setColumnWidth(7, 100)
        purchase_header.setSectionResizeMode(8, QHeaderView.Fixed); self.purchase_table.setColumnWidth(8, 110)
        purchase_header.setSectionResizeMode(9, QHeaderView.Fixed)
        self.purchase_table.setColumnWidth(9, 250)
        self.purchase_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.purchase_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.purchase_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.purchase_table.setAlternatingRowColors(True); self.purchase_table.verticalHeader().setVisible(False)
        self.purchase_table.verticalHeader().setDefaultSectionSize(42)
        self.purchase_table.setColumnWidth(9, 250)
        root.addWidget(self.purchase_table)
        self.refresh_purchase_options(); self.refresh_purchases()
        return w

    def open_purchase_dialog(self):
        self._purchase_dialog = QDialog(self); self._purchase_dialog.setWindowTitle("Record Purchase")
        self._purchase_dialog.setMinimumSize(920, 700)
        self._purchase_dialog.resize(1040, 760)
        root = QVBoxLayout(self._purchase_dialog); form = QFormLayout(); form.setSpacing(10)
        self.pur_supplier = QComboBox(); self.pur_vendor_invoice = QLineEdit()
        self.pur_date = QDateEdit(QDate.currentDate()); self.pur_date.setCalendarPopup(True); self.pur_date.setDisplayFormat("dd-MM-yyyy")
        for label, widget in [("Supplier", self.pur_supplier), ("Supplier invoice no.", self.pur_vendor_invoice), ("Invoice date", self.pur_date)]: form.addRow(label, widget)
        root.addLayout(form); self.refresh_purchase_options()
        root.addWidget(QLabel("Products on this supplier bill"))
        self.pur_lines = []
        self.pur_line_table = QTableWidget(0, 6)
        self.pur_line_table.setHorizontalHeaderLabels(["Product", "Qty", "Unit cost", "GST %", "Line total", ""])
        self.pur_line_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in [(1, 90), (2, 120), (3, 85), (4, 120), (5, 42)]:
            self.pur_line_table.horizontalHeader().setSectionResizeMode(col, QHeaderView.Fixed)
            self.pur_line_table.setColumnWidth(col, width)
        root.addWidget(self.pur_line_table)
        add_line = QPushButton("+ Add product line"); add_line.clicked.connect(self.add_purchase_line)
        root.addWidget(add_line)
        self.pur_totals = QLabel("Subtotal: ₹0.00    GST: ₹0.00    Total: ₹0.00")
        root.addWidget(self.pur_totals)
        self.add_purchase_line()
        payment_form = QFormLayout()
        self.pur_paid = QDoubleSpinBox(); self.pur_paid.setRange(0, 999999999); self.pur_paid.setDecimals(2); self.pur_paid.setPrefix("₹ ")
        self.pur_paid.valueChanged.connect(self.update_purchase_totals)
        self.pur_method = QComboBox(); self.pur_method.addItems(["Bank transfer", "UPI", "Cash", "Card", "Cheque"])
        self.pur_reference = QLineEdit(); self.pur_reference.setPlaceholderText("Optional payment reference")
        payment_form.addRow("Paid now (optional)", self.pur_paid)
        payment_form.addRow("Payment method", self.pur_method)
        payment_form.addRow("Payment reference", self.pur_reference)
        root.addLayout(payment_form)
        upload_row = QHBoxLayout()
        upload = QPushButton("Upload Bill Photo / PDF and Read")
        upload.clicked.connect(self.read_purchase_bill)
        self.pur_bill_name = QLabel("No bill selected")
        self.pur_bill_name.setWordWrap(True)
        upload_row.addWidget(upload); upload_row.addWidget(self.pur_bill_name, 1)
        root.addLayout(upload_row)
        self.pur_ocr_status = QLabel("OCR suggestions should be checked against the bill before saving.")
        self.pur_ocr_status.setWordWrap(True)
        self.pur_ocr_status.setStyleSheet("color:#64748B;")
        root.addWidget(self.pur_ocr_status)
        buttons = QHBoxLayout(); cancel = QPushButton("Cancel"); save = QPushButton("Save Bill and Update Stock")
        cancel.clicked.connect(self._purchase_dialog.reject); save.clicked.connect(self.save_purchase)
        buttons.addStretch(); buttons.addWidget(cancel); buttons.addWidget(save); root.addLayout(buttons)
        self._purchase_dialog.exec()

    def add_purchase_line(self, product_id=None, quantity=1, unit_cost=0, gst_rate=None):
        row = self.pur_line_table.rowCount()
        self.pur_line_table.insertRow(row)
        product = QComboBox()
        products = []
        with SessionLocal() as session:
            products = list(session.scalars(select(Product).where(Product.company_id == self.user["company_id"], Product.active.is_(True)).order_by(Product.name)))
        for obj in products:
            product.addItem(f"{obj.sku} — {obj.name}", obj.id)
        if product_id is not None:
            index = product.findData(int(product_id))
            if index >= 0: product.setCurrentIndex(index)
        qty_box = QDoubleSpinBox(); qty_box.setRange(0.001, 999999999); qty_box.setDecimals(3); qty_box.setValue(quantity)
        cost_box = QDoubleSpinBox(); cost_box.setRange(0, 999999999); cost_box.setDecimals(2); cost_box.setPrefix("₹ "); cost_box.setValue(unit_cost)
        gst_box = QDoubleSpinBox(); gst_box.setRange(0, 100); gst_box.setDecimals(2)
        selected_product = next((p for p in products if p.id == product.currentData()), None)
        gst_box.setValue(float(gst_rate if gst_rate is not None else (selected_product.gst_rate if selected_product else 0)))
        line_total = QLabel("₹0.00"); line_total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        remove = QPushButton("×"); remove.setFixedSize(30, 28)
        entry = {"product": product, "quantity": qty_box, "cost": cost_box, "gst": gst_box, "total": line_total}
        self.pur_lines.append(entry)
        self.pur_line_table.setCellWidget(row, 0, product); self.pur_line_table.setCellWidget(row, 1, qty_box)
        self.pur_line_table.setCellWidget(row, 2, cost_box); self.pur_line_table.setCellWidget(row, 3, gst_box)
        self.pur_line_table.setCellWidget(row, 4, line_total); self.pur_line_table.setCellWidget(row, 5, remove)
        remove.clicked.connect(lambda checked=False, w=remove: self.remove_purchase_line(w))
        for widget in (qty_box, cost_box, gst_box):
            widget.valueChanged.connect(self.update_purchase_totals)
        product.currentIndexChanged.connect(lambda _=0, p=product, g=gst_box: self.set_purchase_product_gst(p, g))
        self.update_purchase_totals()

    def set_purchase_product_gst(self, product_box, gst_box):
        product_id = product_box.currentData()
        if product_id is None: return
        with SessionLocal() as session:
            product = session.scalar(select(Product).where(Product.id == int(product_id), Product.company_id == self.user["company_id"]))
            if product: gst_box.setValue(float(product.gst_rate))

    def remove_purchase_line(self, button):
        row = next((i for i in range(self.pur_line_table.rowCount()) if self.pur_line_table.cellWidget(i, 5) is button), None)
        if row is None: return
        self.pur_line_table.removeRow(row)
        self.pur_lines.pop(row)
        self.update_purchase_totals()

    def update_purchase_totals(self, *_):
        if not hasattr(self, "pur_lines"):
            return
        subtotal = Decimal("0.00"); tax_total = Decimal("0.00")
        for line in self.pur_lines:
            product_id = line["product"].currentData()
            if product_id is None:
                line_taxable = line_tax = Decimal("0.00")
            else:
                qty_value = Decimal(str(line["quantity"].value()))
                cost = Decimal(str(line["cost"].value()))
                rate = Decimal(str(line["gst"].value()))
                line_taxable = money(qty_value * cost)
                line_tax = money(line_taxable * rate / Decimal("100"))
            subtotal += line_taxable; tax_total += line_tax
            line["total"].setText(f"₹{line_taxable + line_tax:,.2f}")
        total = subtotal + tax_total
        paid = Decimal(str(self.pur_paid.value())) if hasattr(self, "pur_paid") else Decimal("0.00")
        self.pur_totals.setText(f"Subtotal: ₹{subtotal:,.2f}    GST: ₹{tax_total:,.2f}    Total: ₹{total:,.2f}    Paid: ₹{paid:,.2f}    Due: ₹{total - paid:,.2f}")

    def read_purchase_bill(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Choose supplier bill photo or PDF",
            "",
            "Bill files (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)",
        )
        if not path:
            return
        self.pur_bill_name.setText(Path(path).name)
        self.pur_bill_name.setToolTip(path)
        self.pur_ocr_status.setText("Reading bill locally. First use may take longer while OCR models are prepared.")
        QApplication.processEvents()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = read_bill_text(path)
            with SessionLocal() as session:
                suppliers = list(session.scalars(select(Supplier).where(Supplier.company_id == self.user["company_id"], Supplier.active.is_(True)).order_by(Supplier.name)))
                products = list(session.scalars(select(Product).where(Product.company_id == self.user["company_id"], Product.active.is_(True)).order_by(Product.name)))
            suggestions = suggest_purchase_fields(text, suppliers, products)
            if "supplier_id" in suggestions:
                index = self.pur_supplier.findData(suggestions["supplier_id"])
                if index >= 0:
                    self.pur_supplier.setCurrentIndex(index)
            first_line = self.pur_lines[0] if self.pur_lines else None
            if "product_id" in suggestions and first_line:
                index = first_line["product"].findData(suggestions["product_id"])
                if index >= 0:
                    first_line["product"].setCurrentIndex(index)
            if "invoice_number" in suggestions:
                self.pur_vendor_invoice.setText(suggestions["invoice_number"])
            if "purchase_date" in suggestions:
                bill_date = suggestions["purchase_date"]
                self.pur_date.setDate(QDate(bill_date.year, bill_date.month, bill_date.day))
            if "quantity" in suggestions and suggestions["quantity"] > 0 and first_line:
                first_line["quantity"].setValue(suggestions["quantity"])
            if "unit_cost" in suggestions and suggestions["unit_cost"] >= 0 and first_line:
                first_line["cost"].setValue(suggestions["unit_cost"])
            filled = sum(key in suggestions for key in ("supplier_id", "product_id", "invoice_number", "purchase_date", "quantity", "unit_cost"))
            if not text.strip():
                self.pur_ocr_status.setText("No text was detected. Try a clearer, straight-on photo or enter the details manually.")
            else:
                self.pur_ocr_status.setText(f"Read complete: {filled} field(s) matched. Check the supplier, product, date, quantity and cost before saving.")
        except Exception as exc:
            self.pur_ocr_status.setText("Could not read this bill. You can still enter the details manually.")
            show_error(self, f"Bill reading failed: {exc}")
        finally:
            QApplication.restoreOverrideCursor()

    def refresh_purchase_options(self):
        if not hasattr(self, "pur_supplier"): return
        supplier_id = self.pur_supplier.currentData()
        self.pur_supplier.clear()
        with SessionLocal() as s:
            for obj in s.scalars(select(Supplier).where(Supplier.company_id == self.user["company_id"], Supplier.active.is_(True)).order_by(Supplier.name)):
                self.pur_supplier.addItem(obj.name, obj.id)
        if supplier_id is not None:
            i = self.pur_supplier.findData(supplier_id)
            if i >= 0: self.pur_supplier.setCurrentIndex(i)

    def save_purchase(self):
        supplier_id = self.pur_supplier.currentData()
        if supplier_id is None or not self.pur_lines:
            show_error(self, "Add a supplier and at least one product line first."); return
        try:
            items = [{"product_id": line["product"].currentData(), "quantity": line["quantity"].value(),
                      "unit_cost": line["cost"].value(), "gst_rate": line["gst"].value()} for line in self.pur_lines]
            _, number = record_purchase(supplier_id, self.pur_vendor_invoice.text(),
                                        username=self.user["username"], purchase_date=self.pur_date.date().toPython(),
                                        items=items, amount_paid=self.pur_paid.value(),
                                        payment_method=self.pur_method.currentText(),
                                        payment_reference=self.pur_reference.text(),
                                        company_id=self.user["company_id"],
                                        branch_id=self.user["branch_id"],
                                        warehouse_id=self.user["warehouse_id"])
            QMessageBox.information(self, "Purchase saved", f"Purchase {number} recorded and stock updated.")
            self.pur_vendor_invoice.clear(); self.refresh_purchases(); self.refresh_products()
            self.refresh_suppliers()
            self.refresh_invoice_options(); self.refresh_dashboard()
            if hasattr(self, "_purchase_dialog"): self._purchase_dialog.accept()
        except Exception as e: show_error(self, e)

    def filter_purchases(self, *_):
        if hasattr(self, "purchase_table"):
            self._filter_table(self.purchase_table, self.purchase_search.text(), (1, 3),
                               status_column=8, status_value=self.purchase_status_filter.currentText())

    def refresh_purchases(self):
        if not hasattr(self, "purchase_table"): return
        with SessionLocal() as s:
            rows = list(s.scalars(select(Purchase).where(Purchase.company_id == self.user["company_id"]).order_by(Purchase.id.desc())))
            total = sum((Decimal(str(p.grand_total or 0)) for p in rows), Decimal("0.00"))
            paid_total = sum((Decimal(str(p.amount_paid or 0)) for p in rows), Decimal("0.00"))
            self.purchase_table.setRowCount(len(rows))
            for r, obj in enumerate(rows):
                supplier = s.scalar(select(Supplier).where(Supplier.id == obj.supplier_id, Supplier.company_id == self.user["company_id"]))
                vals = [obj.id, obj.purchase_number, obj.purchase_date.strftime("%d-%m-%Y"),
                        supplier.name if supplier else "", f"{obj.taxable_total:.2f}", f"{obj.grand_total:.2f}"]
                for c, val in enumerate(vals): self.purchase_table.setItem(r, c, item(val))
                paid = Decimal(str(obj.amount_paid or 0)); due = Decimal(str(obj.grand_total or 0)) - paid
                status = "Paid" if due <= 0 else ("Partially paid" if paid > 0 else "Unpaid")
                for c, val in enumerate([f"₹{paid:,.2f}", f"₹{due:,.2f}", status], start=6):
                    cell = item(val)
                    cell.setTextAlignment((Qt.AlignCenter if c == 8 else Qt.AlignRight) | Qt.AlignVCenter)
                    if c == 8:
                        color = "#047857" if status == "Paid" else ("#B45309" if status == "Partially paid" else "#B91C1C")
                        cell.setForeground(QColor(color))
                    self.purchase_table.setItem(r, c, cell)
                self.purchase_table.setCellWidget(r, 9, self._purchase_row_actions(obj.id, due))
            if hasattr(self, "purchase_metric_labels"):
                self.purchase_metric_labels["bills"].setText(f"{len(rows):,}")
                self.purchase_metric_labels["total"].setText(f"₹{total:,.2f}")
                self.purchase_metric_labels["paid"].setText(f"₹{paid_total:,.2f}")
                self.purchase_metric_labels["due"].setText(f"₹{total-paid_total:,.2f}")
        self.filter_purchases()


    def start_invoice_for_customer(self, customer_id):
        """Open the existing billing workflow with the selected customer pre-filled."""
        try:
            self.refresh_invoice_options()
            customer_index = self.i_customer.findData(int(customer_id))
            if customer_index < 0:
                QMessageBox.warning(self, "Customer unavailable", "This customer is inactive or could not be found.")
                return
            self.i_customer.setCurrentIndex(customer_index)
            self.invoice_lines.setRowCount(0)
            self.i_payment.setValue(0)
            self.i_reference.clear()
            method_index = self.i_method.findText("UPI")
            if method_index >= 0:
                self.i_method.setCurrentIndex(method_index)
            self.i_qty.setValue(1)
            self.i_discount.setValue(0)
            self.refresh_invoice_preview()
            self.navigation.setCurrentRow(5)
            self.invoices_workspace_tabs.setCurrentIndex(1)
        except Exception as exc:
            show_error(self, exc)

    def invoice_workspace_tab(self):
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.setMovable(False)
        self.invoices_workspace_tabs = tabs
        tabs.addTab(self.invoice_register_tab(), "Invoice List & Payments")
        tabs.addTab(self.invoice_tab(), "Create Invoice")
        return tabs

    def open_create_invoice_tab(self):
        self.navigation.setCurrentRow(5)
        self.invoices_workspace_tabs.setCurrentIndex(1)

    def invoice_tab(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(14, 12, 14, 14)
        root.setSpacing(14)

        top = QHBoxLayout()
        back = QPushButton("←  Invoices")
        back.setObjectName("secondaryButton")
        back.clicked.connect(lambda: self.invoices_workspace_tabs.setCurrentIndex(0))
        title_col = QVBoxLayout()
        heading = QLabel("Create Invoice")
        heading.setStyleSheet("font-size:24px;font-weight:700;color:#172033;")
        subtitle = QLabel("Add items, check GST and payment details, then issue the invoice.")
        subtitle.setWordWrap(True)
        subtitle.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        subtitle.setStyleSheet("color:#64748B;")
        title_col.addWidget(heading)
        title_col.addWidget(subtitle)
        top.addWidget(back, 0, Qt.AlignTop)
        top.addLayout(title_col)
        top.addStretch()
        issue_btn = QPushButton("Review and Issue")
        issue_btn.setMinimumHeight(38)
        issue_btn.clicked.connect(self.issue_invoice)
        top.addWidget(issue_btn, 0, Qt.AlignTop)
        root.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(14)
        right = QVBoxLayout()
        right.setSpacing(14)

        def card(title_text):
            frame = QFrame()
            frame.setObjectName("invoiceEditorCard")
            frame.setStyleSheet("QFrame#invoiceEditorCard { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:10px; }")
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(16, 14, 16, 14)
            layout.setSpacing(10)
            title_label = QLabel(title_text)
            title_label.setWordWrap(True)
            title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            title_label.setStyleSheet("font-size:15px;font-weight:700;color:#172033;")
            layout.addWidget(title_label)
            return frame, layout

        with SessionLocal() as session:
            settings = session.scalar(select(BusinessSettings).where(BusinessSettings.company_id == self.user["company_id"]).limit(1))
            business_name = settings.legal_name if settings else "Business details not set"
            business_gstin = settings.gstin if settings else ""
            business_address = settings.address if settings else ""
        business_card, business_layout = card("From")
        business_label = QLabel("<b>{}</b>{}<br>{}".format(
            business_name,
            f"<br>GSTIN: {business_gstin}" if business_gstin else "",
            business_address or "Add your address in Business Settings"
        ))
        business_label.setTextFormat(Qt.RichText)
        business_label.setWordWrap(True)
        business_label.setStyleSheet("color:#475569;")
        business_layout.addWidget(business_label)
        left.addWidget(business_card)

        invoice_card, invoice_layout = card("Invoice Items")
        meta = QLabel("Invoice number will be assigned when issued")
        meta.setWordWrap(True)
        meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        meta.setStyleSheet("color:#64748B;font-size:10pt;")
        invoice_layout.addWidget(meta)

        self.invoice_lines = QTableWidget(0, 12)
        self.invoice_lines.setHorizontalHeaderLabels([
            "Product ID", "SKU", "Product", "Qty", "Price", "Discount",
            "Taxable", "GST %", "CGST", "SGST", "IGST", "Line Total"
        ])
        for hidden_column in (0, 1, 6, 8, 9, 10):
            self.invoice_lines.setColumnHidden(hidden_column, True)
        self.invoice_lines.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.invoice_lines.setSelectionMode(QAbstractItemView.SingleSelection)
        self.invoice_lines.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.invoice_lines.setAlternatingRowColors(True)
        self.invoice_lines.verticalHeader().setVisible(False)
        self.invoice_lines.verticalHeader().setDefaultSectionSize(38)
        self.invoice_lines.setMinimumHeight(230)
        self.invoice_lines.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        line_header = self.invoice_lines.horizontalHeader()
        line_header.setSectionResizeMode(QHeaderView.ResizeToContents)
        line_header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.invoice_lines.setColumnWidth(3, 72)
        self.invoice_lines.setColumnWidth(4, 100)
        self.invoice_lines.setColumnWidth(5, 95)
        self.invoice_lines.setColumnWidth(7, 70)
        self.invoice_lines.setColumnWidth(11, 115)
        invoice_layout.addWidget(self.invoice_lines, 1)

        self.i_product = QComboBox()
        self.i_product.setMinimumWidth(170)
        self.i_product.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.i_product.setMinimumContentsLength(18)
        self.i_qty = QDoubleSpinBox()
        self.i_qty.setRange(0.001, 999999)
        self.i_qty.setDecimals(3)
        self.i_qty.setValue(1)
        self.i_discount = QDoubleSpinBox()
        self.i_discount.setRange(0, 999999999)
        self.i_discount.setDecimals(2)
        self.i_discount.setPrefix("₹ ")
        self.i_add_line = QPushButton("+ Add Item")
        self.i_add_line.clicked.connect(self.add_invoice_line)
        self.i_remove_line = QPushButton("Remove Selected")
        self.i_remove_line.setObjectName("secondaryButton")
        self.i_remove_line.clicked.connect(self.remove_invoice_line)
        controls = QHBoxLayout()
        controls.addWidget(self.i_product, 3)
        controls.addWidget(self.i_qty, 1)
        controls.addWidget(self.i_discount, 1)
        controls.addWidget(self.i_add_line)
        controls.addWidget(self.i_remove_line)
        invoice_layout.addLayout(controls)
        left.addWidget(invoice_card, 1)
        body.addLayout(left, 3)

        payment_card, payment_layout = card("Invoice Information & Payment")
        self.i_customer = QComboBox()
        self.i_customer.setMinimumWidth(0)
        self.i_customer.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.i_customer.setMinimumContentsLength(18)
        self.i_payment = QDoubleSpinBox()
        self.i_payment.setRange(0, 999999999)
        self.i_payment.setDecimals(2)
        self.i_payment.setPrefix("₹ ")
        self.i_method = QComboBox()
        self.i_method.addItems(["UPI", "Cash", "Card", "Bank transfer", "Credit"])
        self.i_reference = QLineEdit()
        self.i_reference.setPlaceholderText("Optional payment reference")
        info_form = QFormLayout()
        info_form.setVerticalSpacing(10)
        info_form.setRowWrapPolicy(QFormLayout.WrapAllRows)
        info_form.addRow("Send To", self.i_customer)
        info_form.addRow("Initial Payment", self.i_payment)
        info_form.addRow("Payment Method", self.i_method)
        info_form.addRow("Reference", self.i_reference)
        invoice_date = QLabel(__import__("datetime").date.today().strftime("%d-%m-%Y"))
        invoice_date.setStyleSheet("color:#475569;")
        info_form.addRow("Issue Date", invoice_date)
        payment_layout.addLayout(info_form)
        right.addWidget(payment_card)

        summary_card, summary_layout = card("Invoice Summary")
        summary_card.setStyleSheet("QFrame#invoiceEditorCard { background:#FFFFFF; border:1px solid #E2E8F0; border-radius:10px; }")
        self.invoice_summary = QLabel("Select a customer and add products to see the subtotal, GST and total.")
        self.invoice_summary.setWordWrap(True)
        self.invoice_summary.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.invoice_summary.setStyleSheet("color:#334155;font-size:10pt;line-height:1.5;")
        summary_layout.addWidget(self.invoice_summary)
        right.addWidget(summary_card)
        right.addStretch()
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        self.i_customer.currentIndexChanged.connect(self.refresh_invoice_preview)
        self.refresh_invoice_options()
        return page
    def refresh_invoice_options(self):
        if not hasattr(self, "i_customer"): return
        current_customer = self.i_customer.currentData()
        current_product = self.i_product.currentData()
        self.i_customer.clear(); self.i_product.clear()
        with SessionLocal() as s:
            for c in s.scalars(select(Customer).where(Customer.company_id == self.user["company_id"], Customer.active.is_(True)).order_by(Customer.name)):
                self.i_customer.addItem(f"{c.name} (state {c.state_code})", c.id)
            for p in s.scalars(select(Product).where(Product.company_id == self.user["company_id"], Product.active.is_(True)).order_by(Product.name)):
                self.i_product.addItem(f"{p.sku} — {p.name} | ₹{p.selling_price} | stock {p.stock_qty}", p.id)
        if current_customer is not None:
            idx = self.i_customer.findData(current_customer)
            if idx >= 0: self.i_customer.setCurrentIndex(idx)
        if current_product is not None:
            idx = self.i_product.findData(current_product)
            if idx >= 0: self.i_product.setCurrentIndex(idx)


    def add_invoice_line(self):
        product_id = self.i_product.currentData()

        if product_id is None:
            show_error(self, "Add a product first.")
            return

        quantity_to_add = self.i_qty.value()
        new_discount = self.i_discount.value()

        with SessionLocal() as s:
            p = s.get(Product, product_id)

            if not p:
                show_error(self, "Product not found.")
                return

            # Check if the same product is already in the invoice
            existing_row = None

            for row in range(self.invoice_lines.rowCount()):
                existing_id_item = self.invoice_lines.item(row, 0)

                if (
                    existing_id_item
                    and existing_id_item.text() == str(product_id)
                ):
                    existing_row = row
                    break

            if existing_row is not None:
                # Increase quantity instead of creating a duplicate row
                qty_item = self.invoice_lines.item(existing_row, 3)

                try:
                    existing_qty = float(qty_item.text())
                except (ValueError, AttributeError):
                    show_error(
                        self,
                        "Could not read the existing product quantity."
                    )
                    return

                updated_qty = existing_qty + quantity_to_add

                qty_item.setText(f"{updated_qty:.3f}")

                # Keep the existing discount unchanged.
                if new_discount > 0:
                    QMessageBox.information(
                        self,
                        "Product already added",
                        "The product quantity has been increased. "
                        "The new discount was not applied; "
                        "the existing row discount is unchanged."
                    )

            else:
                r = self.invoice_lines.rowCount()
                self.invoice_lines.insertRow(r)

                values = [
                    p.id,
                    p.sku,
                    p.name,
                    f"{quantity_to_add:.3f}",
                    f"{p.selling_price:.2f}",
                    f"{new_discount:.2f}",
                    "", "", "", "", "", ""
                ]

                for col, val in enumerate(values):
                    self.invoice_lines.setItem(r, col, item(val))

        self.i_discount.setValue(0)
        self.refresh_invoice_preview()


    def remove_invoice_line(self):
        row = self.invoice_lines.currentRow()

        if row >= 0:
            self.invoice_lines.removeRow(row)
            self.refresh_invoice_preview()

    def refresh_invoice_preview(self, *_):
        if not hasattr(self, "invoice_summary"):
            return

        customer_id = self.i_customer.currentData()

        if customer_id is None or self.invoice_lines.rowCount() == 0:
            self.invoice_summary.setText(
                "Invoice preview: Select a customer and add products."
            )
            return

        lines = []

        for r in range(self.invoice_lines.rowCount()):
            lines.append({
                "product_id": int(self.invoice_lines.item(r, 0).text()),
                "quantity": self.invoice_lines.item(r, 3).text(),
                "discount_amount": self.invoice_lines.item(r, 5).text()
            })

        try:
            preview = calculate_invoice_preview(
                customer_id, lines,
                company_id=self.user["company_id"],
                branch_id=self.user["branch_id"],
                warehouse_id=self.user["warehouse_id"],
            )

            for r, line in enumerate(preview["lines"]):
                values = [
                    f'{line["taxable_value"]:.2f}',
                    f'{line["gst_rate"]:.2f}%',
                    f'{line["cgst_amount"]:.2f}',
                    f'{line["sgst_amount"]:.2f}',
                    f'{line["igst_amount"]:.2f}',
                    f'{line["line_total"]:.2f}'
                ]

                for offset, val in enumerate(values, start=6):
                    self.invoice_lines.setItem(r, offset, item(val))

            supply_type = (
                "Interstate — IGST"
                if preview["is_interstate"]
                else "Intrastate — CGST + SGST"
            )

            self.invoice_summary.setText(
                f'Customer: {preview["customer_name"]}\n'
                f'Supply type: {supply_type}\n'
                f'Place of supply state code: '
                f'{preview["place_of_supply_state_code"]}\n'
                f'Taxable value: ₹{preview["taxable_total"]:.2f} | '
                f'CGST: ₹{preview["cgst_total"]:.2f} | '
                f'SGST: ₹{preview["sgst_total"]:.2f} | '
                f'IGST: ₹{preview["igst_total"]:.2f}\n'
                f'GRAND TOTAL: ₹{preview["grand_total"]:.2f}'
            )

        except Exception as e:
            for r in range(self.invoice_lines.rowCount()):
                for col in range(6, 12):
                    self.invoice_lines.setItem(r, col, item("—"))

            self.invoice_summary.setText(
                f"Cannot calculate invoice preview: {e}"
            )


    def issue_invoice(self):
        customer_id = self.i_customer.currentData()

        if customer_id is None or self.invoice_lines.rowCount() == 0:
            show_error(
                self,
                "Select a customer and add at least one product."
            )
            return

        lines = []

        for r in range(self.invoice_lines.rowCount()):
            product_item = self.invoice_lines.item(r, 0)
            quantity_item = self.invoice_lines.item(r, 3)
            discount_item = self.invoice_lines.item(r, 5)

            if not product_item or not quantity_item or not discount_item:
                show_error(
                    self,
                    f"Invoice row {r + 1} contains incomplete data."
                )
                return

            try:
                lines.append({
                    "product_id": int(product_item.text()),
                    "quantity": quantity_item.text(),
                    "discount_amount": discount_item.text()
                })
            except (ValueError, TypeError):
                show_error(
                    self,
                    f"Invalid product or quantity in row {r + 1}."
                )
                return

        try:
            # Recalculate and validate stock before confirming
            preview = calculate_invoice_preview(customer_id, lines)

            # Currency is rounded to two decimal places
            paid = Decimal(str(self.i_payment.value())).quantize(
                Decimal("0.01")
            )
            grand_total = Decimal(
                str(preview["grand_total"])
            ).quantize(Decimal("0.01"))

            if paid < Decimal("0.00"):
                show_error(self, "Payment cannot be negative.")
                return

            if paid > grand_total:
                show_error(
                    self,
                    f"Initial payment cannot exceed the invoice total "
                    f"of ₹{grand_total:.2f}."
                )
                return

            allow_credit_override = False
            with SessionLocal() as session:
                customer = session.scalar(select(Customer).where(Customer.id == int(customer_id), Customer.company_id == self.user["company_id"]))
                current_due = session.scalar(select(func.coalesce(func.sum(Invoice.grand_total - Invoice.amount_paid), 0)).where(Invoice.company_id == self.user["company_id"], Invoice.customer_id == int(customer_id), Invoice.status == "issued")) or 0
                credit_limit = Decimal(str(customer.credit_limit or 0))
                projected_due = Decimal(str(current_due)) + grand_total - paid
            if projected_due > credit_limit:
                answer_limit = QMessageBox.warning(
                    self, "Customer Credit Limit Exceeded",
                    f"Customer: {customer.name}\nCredit limit: ₹{credit_limit:.2f}\nCurrent due: ₹{Decimal(str(current_due)):.2f}\nDue after this invoice: ₹{projected_due:.2f}\n\nDo you want to allow this invoice anyway?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No
                )
                if answer_limit != QMessageBox.Yes:
                    return
                allow_credit_override = True

            if grand_total <= Decimal("0.00"):
                show_error(
                    self,
                    "Invoice total must be greater than zero."
                )
                return

            supply_type = (
                "Interstate (IGST)"
                if preview["is_interstate"]
                else "Intrastate (CGST + SGST)"
            )

            balance = grand_total - paid

            message = (
                "Please review the invoice before issuing.\n\n"
                f'Customer: {preview["customer_name"]}\n'
                f'Supply type: {supply_type}\n'
                f'Taxable value: ₹{preview["taxable_total"]:.2f}\n'
                f'CGST: ₹{preview["cgst_total"]:.2f}\n'
                f'SGST: ₹{preview["sgst_total"]:.2f}\n'
                f'IGST: ₹{preview["igst_total"]:.2f}\n'
                f'Grand total: ₹{grand_total:.2f}\n\n'
                f'Initial payment: ₹{paid:.2f}\n'
                f'Balance due: ₹{balance:.2f}\n\n'
                "Do you want to issue this invoice?"
            )

            answer = QMessageBox.question(
                self,
                "Confirm Invoice",
                message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if answer != QMessageBox.Yes:
                return

            # Create the invoice using the existing service
            invoice_id, number = create_invoice(
                customer_id,
                lines,
                self.user["username"],
                float(paid),
                self.i_method.currentText(),
                self.i_reference.text().strip(),
                allow_credit_override=allow_credit_override,
                company_id=self.user["company_id"],
                branch_id=self.user["branch_id"],
                warehouse_id=self.user["warehouse_id"],
            )

            # Ask where to save the PDF
            path, _ = QFileDialog.getSaveFileName(
                self,
                "Save Invoice PDF",
                f"{number}.pdf",
                "PDF files (*.pdf)"
            )

            if path:
                try:
                    generate_invoice_pdf(invoice_id, path)
                    QMessageBox.information(
                        self,
                        "Invoice Issued",
                        f"Invoice {number} was issued successfully.\n\n"
                        f"PDF saved to:\n{path}"
                    )
                except Exception as pdf_error:
                    QMessageBox.warning(
                        self,
                        "Invoice Issued — PDF Error",
                        f"Invoice {number} was issued successfully, "
                        f"but the PDF could not be generated.\n\n"
                        f"Error: {pdf_error}"
                    )
            else:
                QMessageBox.information(
                    self,
                    "Invoice Issued",
                    f"Invoice {number} was issued successfully.\n"
                    "PDF saving was cancelled."
                )

            email_now = QMessageBox.question(
                self,
                "Email invoice to customer?",
                f"Invoice {number} is saved. Would you like to email its PDF to the customer's saved email address now?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if email_now == QMessageBox.Yes:
                self.email_invoice(invoice_id)

            # Clear invoice form after successful creation
            self.invoice_lines.setRowCount(0)
            self.i_payment.setValue(0)
            self.i_reference.clear()
            self.i_discount.setValue(0)

            self.refresh_invoice_preview()
            self.refresh_products()
            self.refresh_invoice_options()
            self.refresh_invoice_register()
            self.refresh_dashboard()

        except Exception as e:
            error_message = str(e)
            if "insufficient stock" in error_message.lower():
                show_error(
                    self,
                    "Insufficient stock. Please reduce the quantity "
                    "or record a purchase before issuing this invoice.\n\n"
                    + error_message
                )
            else:
                show_error(self, error_message)


    def invoice_register_tab(self):
        w = QWidget()
        root = QVBoxLayout(w)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(14)

        heading = QLabel("Invoices")
        heading.setStyleSheet(
            "font-size: 22px; font-weight: 700; color: #172033;"
        )

        subtitle = QLabel(
            "Create invoices, record payments, and track customer balances."
        )
        subtitle.setStyleSheet("color: #64748B; font-size: 10pt;")

        page_header = QHBoxLayout()
        title_column = QVBoxLayout()
        title_column.addWidget(heading)
        title_column.addWidget(subtitle)
        page_header.addLayout(title_column)
        page_header.addStretch()
        self.invoice_period_filter = QComboBox()
        self.invoice_period_filter.addItems(["This month", "Last month", "All time"])
        self.invoice_period_filter.currentIndexChanged.connect(self.refresh_invoice_register)
        create_invoice = QPushButton("+ Create Invoice")
        create_invoice.clicked.connect(self.open_create_invoice_tab)
        page_header.addWidget(self.invoice_period_filter)
        page_header.addWidget(create_invoice)
        root.addLayout(page_header)

        # Summary cards
        cards = QHBoxLayout()
        cards.setSpacing(12)

        self.register_total_card = self.create_dashboard_card(
            "TOTAL INVOICED", "₹0.00", "#2563EB"
        )
        self.register_paid_card = self.create_dashboard_card(
            "PAYMENTS RECEIVED", "₹0.00", "#059669"
        )
        self.register_balance_card = self.create_dashboard_card(
            "BALANCE DUE", "₹0.00", "#D97706"
        )
        self.register_unpaid_card = self.create_dashboard_card(
            "UNPAID INVOICES", "0", "#DC2626"
        )

        for card in (
            self.register_total_card,
            self.register_paid_card,
            self.register_balance_card,
            self.register_unpaid_card,
        ):
            cards.addWidget(card)

        root.addLayout(cards)

        # Search and filter
        filters = QHBoxLayout()

        self.invoice_search = QLineEdit()
        self.invoice_search.setPlaceholderText(
            "Search by invoice number or customer..."
        )
        self.invoice_search.textChanged.connect(
            self.refresh_invoice_register
        )

        self.invoice_status_filter = QComboBox()
        self.invoice_status_filter.addItems([
            "All invoices",
            "Paid",
            "Partially paid",
            "Unpaid",
        ])
        self.invoice_status_filter.currentIndexChanged.connect(
            self.refresh_invoice_register
        )

        self.invoice_customer_filter = QComboBox()
        self.invoice_customer_filter.addItem("All customers", None)
        with SessionLocal() as session:
            for customer in session.scalars(select(Customer).where(Customer.company_id == self.user["company_id"], Customer.active.is_(True)).order_by(Customer.name)):
                self.invoice_customer_filter.addItem(customer.name, customer.id)
        self.invoice_customer_filter.currentIndexChanged.connect(self.refresh_invoice_register)

        filters.addWidget(self.invoice_search, 3)
        filters.addWidget(self.invoice_status_filter, 1)
        filters.addWidget(self.invoice_customer_filter, 1)

        root.addLayout(filters)

        # Action buttons
        buttons = QHBoxLayout()

        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_invoice_register)

        pdf = QPushButton("Export Selected PDF")
        pdf.clicked.connect(self.export_selected_invoice)

        payment = QPushButton("Record Payment")
        payment.clicked.connect(self.add_payment_dialog)

        email_invoice = QPushButton("Email Invoice to Customer")
        email_invoice.clicked.connect(self.email_selected_invoice)

        buttons.addWidget(refresh)
        buttons.addWidget(pdf)
        buttons.addWidget(payment)
        buttons.addWidget(email_invoice)
        buttons.addStretch()

        root.addLayout(buttons)

        # Invoice table
        self.invoice_table = QTableWidget(0, 9)
        self.invoice_table.setHorizontalHeaderLabels([
            "ID",
            "Invoice",
            "Date",
            "Customer",
            "Taxable",
            "Total",
            "Paid",
            "Balance Due",
            "Status",
        ])

        self.invoice_table.setColumnHidden(0, True)
        self.invoice_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.invoice_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.Stretch
        )

        self.invoice_table.setSelectionBehavior(
            QAbstractItemView.SelectRows
        )
        self.invoice_table.setSelectionMode(
            QAbstractItemView.SingleSelection
        )
        self.invoice_table.setEditTriggers(
            QAbstractItemView.NoEditTriggers
        )
        self.invoice_table.setAlternatingRowColors(True)
        self.invoice_table.verticalHeader().setVisible(False)
        self.invoice_table.verticalHeader().setDefaultSectionSize(34)

        root.addWidget(self.invoice_table, 1)

        self.refresh_invoice_register()
        return w

    def refresh_invoice_register(self, *_):
        if not hasattr(self, "invoice_table"):
            return

        search_text = (
            self.invoice_search.text().strip().lower()
            if hasattr(self, "invoice_search")
            else ""
        )

        status_filter = (
            self.invoice_status_filter.currentText()
            if hasattr(self, "invoice_status_filter")
            else "All invoices"
        )
        customer_filter = self.invoice_customer_filter.currentData() if hasattr(self, "invoice_customer_filter") else None
        period_filter = self.invoice_period_filter.currentText() if hasattr(self, "invoice_period_filter") else "All time"
        today = date.today()
        period_start = period_end = None
        if period_filter == "This month":
            period_start = today.replace(day=1)
            next_month = (period_start.replace(day=28) + timedelta(days=4)).replace(day=1)
            period_end = next_month - timedelta(days=1)
        elif period_filter == "Last month":
            period_end = today.replace(day=1) - timedelta(days=1)
            period_start = period_end.replace(day=1)

        total_invoiced = Decimal("0.00")
        total_paid = Decimal("0.00")
        total_balance = Decimal("0.00")
        unpaid_count = 0
        display_rows = []

        with SessionLocal() as s:
            invoices = list(
                s.scalars(
                    select(Invoice).where(Invoice.company_id == self.user["company_id"]).order_by(Invoice.id.desc())
                )
            )

            for inv in invoices:
                if inv.status != "issued":
                    continue
                invoice_day = inv.invoice_date.date()
                if period_start and not period_start <= invoice_day <= period_end:
                    continue
                if customer_filter is not None and inv.customer_id != int(customer_filter):
                    continue

                customer = s.scalar(select(Customer).where(Customer.id == inv.customer_id, Customer.company_id == self.user["company_id"]))
                customer_name = customer.name if customer else ""

                grand_total = Decimal(str(inv.grand_total))
                paid_amount = Decimal(str(inv.amount_paid))
                balance = max(
                    Decimal("0.00"),
                    grand_total - paid_amount
                )

                total_invoiced += grand_total
                total_paid += paid_amount
                total_balance += balance

                if balance <= Decimal("0.00"):
                    status = "Paid"
                elif paid_amount > Decimal("0.00"):
                    status = "Partially paid"
                else:
                    status = "Unpaid"

                if balance > Decimal("0.00"):
                    unpaid_count += 1

                # Search filter
                searchable = (
                    str(inv.invoice_number).lower()
                    + " "
                    + customer_name.lower()
                )

                if search_text and search_text not in searchable:
                    continue

                # Status filter
                if status_filter != "All invoices":
                    if status != status_filter:
                        continue

                display_rows.append((
                    inv.id,
                    inv.invoice_number,
                    inv.invoice_date.strftime("%d-%m-%Y"),
                    customer_name,
                    f"₹{Decimal(str(inv.taxable_total)):,.2f}",
                    f"₹{grand_total:,.2f}",
                    f"₹{paid_amount:,.2f}",
                    f"₹{balance:,.2f}",
                    status,
                ))

        # Summary cards show all issued invoices, regardless of search filter
        self.register_total_card.value_label.setText(
            f"₹{total_invoiced:,.2f}"
        )
        self.register_paid_card.value_label.setText(
            f"₹{total_paid:,.2f}"
        )
        self.register_balance_card.value_label.setText(
            f"₹{total_balance:,.2f}"
        )
        self.register_unpaid_card.value_label.setText(
            str(unpaid_count)
        )

        self.invoice_table.setRowCount(len(display_rows))

        for row, values in enumerate(display_rows):
            for col, value in enumerate(values):
                cell = item(value)
                self.invoice_table.setItem(row, col, cell)

            status_cell = self.invoice_table.item(row, 8)

            if status_cell:
                if values[8] == "Paid":
                    status_cell.setForeground(
                        QColor("#15803D")
                    )
                elif values[8] == "Partially paid":
                    status_cell.setForeground(
                        QColor("#B45309")
                    )
                else:
                    status_cell.setForeground(
                        QColor("#B91C1C")
                    )

                font = status_cell.font()
                font.setBold(True)
                status_cell.setFont(font)

    def selected_invoice_id(self):
        row = self.invoice_table.currentRow()

        if row < 0:
            return None

        id_cell = self.invoice_table.item(row, 0)

        if id_cell is None:
            return None

        try:
            return int(id_cell.text())
        except (ValueError, TypeError):
            return None

    def export_selected_invoice(self):
        invoice_id = self.selected_invoice_id()
        if not invoice_id:
            show_error(self, "Select an invoice first."); return
        self.export_invoice_pdf(invoice_id)

    def export_invoice_pdf(self, invoice_id):
        with SessionLocal() as s:
            inv = s.get(Invoice, int(invoice_id))
            if not inv:
                show_error(self, "Invoice not found.")
                return
            number = inv.invoice_number
        fmt, ok = QInputDialog.getItem(self, "Invoice output", "Choose layout:", ["A4 invoice", "80mm thermal receipt", "58mm thermal receipt"], 0, False)
        if not ok: return
        path, _ = QFileDialog.getSaveFileName(self, "Save invoice PDF", f"{number}.pdf", "PDF files (*.pdf)")
        if path:
            try:
                if fmt == "A4 invoice": generate_invoice_pdf(invoice_id, path)
                else: generate_thermal_receipt(invoice_id, path, 80 if fmt.startswith("80") else 58)
                QMessageBox.information(self, "PDF created", f"Saved to {path}\nPrint at actual size; disable fit-to-page for thermal receipts.")
            except Exception as e: show_error(self, e)

    def email_selected_invoice(self):
        invoice_id = self.selected_invoice_id()
        if not invoice_id:
            show_error(self, "Select an invoice first.")
            return
        self.email_invoice(invoice_id)

    def email_invoice(self, invoice_id):
        with SessionLocal() as session:
            invoice = session.scalar(select(Invoice).where(Invoice.id == int(invoice_id), Invoice.company_id == self.user["company_id"]))
            if not invoice:
                show_error(self, "Invoice not found.")
                return
            customer = session.scalar(select(Customer).where(Customer.id == invoice.customer_id, Customer.company_id == self.user["company_id"]))
            settings = session.scalar(select(BusinessSettings).where(BusinessSettings.company_id == self.user["company_id"]).limit(1))
            if not customer or not customer.email.strip():
                show_error(self, "Add an email address to this customer record before sending the invoice.")
                return
            recipient = customer.email.strip()
            recipient_address = parseaddr(recipient)[1]
            if "@" not in recipient_address or "." not in recipient_address.rsplit("@", 1)[-1]:
                show_error(self, f"The customer's email address does not look valid: {recipient}")
                return
            if not settings or not settings.smtp_email.strip() or not settings.smtp_host.strip():
                QMessageBox.information(
                    self, "Set up invoice email",
                    "Enter your sender email and SMTP server in Business Settings, then try again.\n\n"
                    "For Gmail, use smtp.gmail.com, port 587, and a Google App Password.",
                )
                return
            number = invoice.invoice_number
            total = Decimal(str(invoice.grand_total))
            paid = Decimal(str(invoice.amount_paid))
            host = settings.smtp_host.strip()
            port = int(settings.smtp_port or 587)
            sender = settings.smtp_email.strip()

        password, ok = QInputDialog.getText(
            self, "Email invoice", f"SMTP password or app password for {sender}:\nFor Gmail, paste the 16-character App Password; spaces are optional.", QLineEdit.Password
        )
        if not ok:
            return
        if not password:
            show_error(self, "Enter the SMTP password or app password.")
            return
        try:
            password = normalize_smtp_password(host, password)
        except ValueError as exc:
            show_error(self, exc)
            return

        balance = max(Decimal("0.00"), total - paid)
        message = EmailMessage()
        message["Subject"] = f"Invoice {number}"
        message["From"] = sender
        message["To"] = recipient
        message.set_content(
            f"Dear {customer.name},\n\n"
            f"Please find invoice {number} attached.\n"
            f"Invoice total: INR {total:,.2f}\n"
            f"Amount received: INR {paid:,.2f}\n"
            f"Balance due: INR {balance:,.2f}\n\n"
            "Thank you."
        )
        smtp = None
        stage = "connecting to the SMTP server"
        accepted_by_server = False
        send_error = None
        try:
            with tempfile.TemporaryDirectory(prefix="gst_invoice_email_") as temp_dir:
                pdf_path = Path(temp_dir) / f"{number}.pdf"
                generate_invoice_pdf(invoice_id, pdf_path)
                message.add_attachment(
                    pdf_path.read_bytes(), maintype="application", subtype="pdf",
                    filename=pdf_path.name,
                )
                context = ssl.create_default_context()
                if port == 465:
                    smtp = smtplib.SMTP_SSL(host, port, timeout=25, context=context)
                else:
                    smtp = smtplib.SMTP(host, port, timeout=25)
                if port != 465:
                    stage = "starting the secure TLS connection"
                    smtp.ehlo()
                    smtp.starttls(context=context)
                    smtp.ehlo()
                stage = "authenticating the sender account"
                smtp.login(sender, password)
                stage = "sending the invoice message"
                smtp.send_message(message)
                accepted_by_server = True
        except Exception as exc:
            send_error = exc
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    # Some providers close the connection after accepting DATA;
                    # a QUIT failure must not turn an accepted email into a false failure.
                    try:
                        smtp.close()
                    except Exception:
                        pass

        if accepted_by_server:
            QMessageBox.information(self, "Invoice emailed", f"Invoice {number} was accepted by the SMTP server for {recipient}.")
        elif send_error:
            show_error(self, f"Invoice email failed while {stage}. Check the SMTP settings and App Password.\n\n{send_error}")

    def add_payment_dialog(self):
        invoice_id = self.selected_invoice_id()
        if not invoice_id:
            show_error(self, "Select an invoice first."); return
        self.open_invoice_payment(invoice_id)

    def open_invoice_payment(self, invoice_id):
        with SessionLocal() as s:
            inv = s.get(Invoice, int(invoice_id))
            if not inv:
                show_error(self, "Invoice not found.")
                return False
            invoice_number = inv.invoice_number
            balance = max(Decimal("0.00"), Decimal(str(inv.grand_total)) - Decimal(str(inv.amount_paid)))
        if balance <= 0:
            QMessageBox.information(self, "Invoice already paid", f"{invoice_number} has no outstanding balance.")
            return False
        dialog = PaymentDialog(invoice_number, balance, self)
        if dialog.exec() != QDialog.Accepted:
            return False
        try:
            record_payment(
                invoice_id,
                dialog.amount.value(),
                dialog.method.currentText(),
                dialog.reference.text().strip(),
                self.user["username"],
                company_id=self.user["company_id"],
            )
            self.refresh_invoice_register(); self.refresh_dashboard()
            QMessageBox.information(self, "Payment saved", "Payment recorded successfully.")
            return True
        except Exception as e:
            show_error(self, e)
            return False

    def reports_tab(self):
        w = QWidget(); root = QVBoxLayout(w)
        self.report_label = QLabel()
        refresh = QPushButton("Refresh report"); refresh.clicked.connect(self.refresh_reports)
        export = QPushButton("Export invoice register CSV"); export.clicked.connect(self.export_csv)
        root.addWidget(QLabel("<h2>Sales & GST Summary</h2>")); root.addWidget(self.report_label)
        root.addWidget(refresh); root.addWidget(export); root.addStretch()
        self.refresh_reports()
        return w

    def refresh_reports(self):
        with SessionLocal() as s:
            invoices = list(s.scalars(select(Invoice).where(Invoice.company_id == self.user["company_id"], Invoice.status == "issued")))
            taxable = sum((Decimal(i.taxable_total) for i in invoices), Decimal("0"))
            cgst = sum((Decimal(i.cgst_total) for i in invoices), Decimal("0"))
            sgst = sum((Decimal(i.sgst_total) for i in invoices), Decimal("0"))
            igst = sum((Decimal(i.igst_total) for i in invoices), Decimal("0"))
            total = sum((Decimal(i.grand_total) for i in invoices), Decimal("0"))
            paid = sum((Decimal(i.amount_paid) for i in invoices), Decimal("0"))
            self.report_label.setText(
                f"<h3>All-time issued invoices: {len(invoices)}</h3>"
                f"<p>Taxable sales: ₹{taxable:.2f}</p><p>CGST: ₹{cgst:.2f}</p>"
                f"<p>SGST: ₹{sgst:.2f}</p><p>IGST: ₹{igst:.2f}</p>"
                f"<p>Invoice value: ₹{total:.2f}</p><p>Payments received: ₹{paid:.2f}</p>"
                f"<p>Outstanding: ₹{total-paid:.2f}</p>"
            )

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export invoice register", "invoice_register.csv", "CSV files (*.csv)")
        if not path: return
        import csv
        with SessionLocal() as s, open(path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(["Invoice", "Date", "Customer", "Taxable", "CGST", "SGST", "IGST", "Total", "Paid", "Balance"])
            for inv in s.scalars(select(Invoice).where(Invoice.company_id == self.user["company_id"]).order_by(Invoice.invoice_date)):
                c = s.scalar(select(Customer).where(Customer.id == inv.customer_id, Customer.company_id == self.user["company_id"]))
                writer.writerow([inv.invoice_number, inv.invoice_date.isoformat(), c.name if c else "",
                                 inv.taxable_total, inv.cgst_total, inv.sgst_total, inv.igst_total,
                                 inv.grand_total, inv.amount_paid, Decimal(inv.grand_total)-Decimal(inv.amount_paid)])
        QMessageBox.information(self, "Export complete", f"CSV saved to {path}")

    def users_tab(self):
        w = QWidget(); root = QVBoxLayout(w)
        root.setContentsMargins(18, 18, 18, 18); root.setSpacing(14)
        header = QHBoxLayout(); title_group = QVBoxLayout()
        title = QLabel("User Management"); title.setStyleSheet("font-size:24px;font-weight:700;color:#172033;")
        subtitle = QLabel("Manage sign-in accounts, access roles and passwords."); subtitle.setStyleSheet("color:#64748B;")
        title_group.addWidget(title); title_group.addWidget(subtitle)
        header.addLayout(title_group); header.addStretch()
        create_button = QPushButton("+  Create User"); create_button.setMinimumHeight(42)
        create_button.clicked.connect(self.open_create_user_dialog); header.addWidget(create_button)
        root.addLayout(header)

        list_panel = QFrame(); list_panel.setObjectName("userPanel")
        list_panel.setStyleSheet("QFrame#userPanel{background:#FFFFFF;border:1px solid #E3EAF3;border-radius:10px;}")
        list_layout = QVBoxLayout(list_panel); list_layout.setContentsMargins(16, 14, 16, 14); list_layout.setSpacing(10)
        list_header = QHBoxLayout(); list_title = QLabel("User accounts"); list_title.setStyleSheet("font-size:18px;font-weight:700;color:#172033;")
        self.user_search = QLineEdit(); self.user_search.setPlaceholderText("Search users")
        self.user_search.setClearButtonEnabled(True); self.user_search.textChanged.connect(self.filter_users)
        list_header.addWidget(list_title); list_header.addStretch(); list_header.addWidget(self.user_search); list_layout.addLayout(list_header)
        self.user_table = QTableWidget(0, 4); self.user_table.setHorizontalHeaderLabels(["Username", "Role", "Status", "Actions"])
        user_header = self.user_table.horizontalHeader()
        user_header.setSectionResizeMode(0, QHeaderView.Stretch)
        user_header.setSectionResizeMode(1, QHeaderView.Fixed); self.user_table.setColumnWidth(1, 150)
        user_header.setSectionResizeMode(2, QHeaderView.Fixed); self.user_table.setColumnWidth(2, 130)
        user_header.setSectionResizeMode(3, QHeaderView.Fixed); self.user_table.setColumnWidth(3, 190)
        user_header.setDefaultAlignment(Qt.AlignCenter)
        self.user_table.verticalHeader().setVisible(False)
        self.user_table.verticalHeader().setDefaultSectionSize(48)
        self.user_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.user_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.user_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.user_table.setAlternatingRowColors(True)
        self.user_table.setMinimumHeight(220)
        list_layout.addWidget(self.user_table)
        root.addWidget(list_panel, 1)
        self.refresh_users()
        return w

    def open_create_user_dialog(self):
        self._user_create_dialog = QDialog(self)
        self._user_create_dialog.setWindowTitle("Create User")
        self._user_create_dialog.setMinimumWidth(520)
        layout = QVBoxLayout(self._user_create_dialog); layout.setContentsMargins(22, 20, 22, 18); layout.setSpacing(12)
        heading = QLabel("Create a user account"); heading.setStyleSheet("font-size:21px;font-weight:700;color:#172033;")
        note = QLabel("Usernames need at least 3 characters. Passwords can be any length and can be changed after sign-in.")
        note.setWordWrap(True); note.setStyleSheet("color:#64748B;")
        layout.addWidget(heading); layout.addWidget(note)
        form = QFormLayout(); form.setHorizontalSpacing(16); form.setVerticalSpacing(12)
        self.u_name = QLineEdit(); self.u_name.setPlaceholderText("Enter a username"); self.u_name.setMinimumHeight(40)
        self.u_password = QLineEdit(); self.u_password.setPlaceholderText("Set a temporary password")
        self.u_password.setEchoMode(QLineEdit.Password); self.u_password.setMinimumHeight(40)
        show_password = QCheckBox("Show password")
        show_password.toggled.connect(lambda visible: self.u_password.setEchoMode(QLineEdit.Normal if visible else QLineEdit.Password))
        password_box = QWidget(); password_layout = QVBoxLayout(password_box); password_layout.setContentsMargins(0, 0, 0, 0)
        password_layout.addWidget(self.u_password); password_layout.addWidget(show_password)
        self.u_role = QComboBox(); self.u_role.addItems(["staff", "viewer", "admin"]); self.u_role.setMinimumHeight(40)
        form.addRow("Username", self.u_name); form.addRow("Temporary password", password_box); form.addRow("Role", self.u_role)
        layout.addLayout(form)
        footer = QHBoxLayout(); footer.addStretch()
        cancel = QPushButton("Cancel"); cancel.setObjectName("secondaryButton"); cancel.clicked.connect(self._user_create_dialog.reject)
        create = QPushButton("Create User"); create.setMinimumWidth(140); create.clicked.connect(self.create_user)
        footer.addWidget(cancel); footer.addWidget(create); layout.addLayout(footer)
        self.u_name.setFocus()
        self._user_create_dialog.exec()

    def filter_users(self, text=""):
        if hasattr(self, "user_table"):
            self._filter_table(self.user_table, text, (0, 1, 2))

    def create_user(self):
        username = self.u_name.text().strip()
        password = self.u_password.text()
        if len(username) < 3:
            show_error(self, "Username must be at least 3 characters."); return
        if not password:
            show_error(self, "Enter a temporary password."); return
        try:
            with SessionLocal.begin() as s:
                if s.scalar(select(User.id).where(User.username == username)):
                    show_error(self, "That username already exists. Choose a different username."); return
                new_user = User(
                    username=username,
                    password_hash=hash_password(password),
                    role=self.u_role.currentText(),
                    active=True,
                )
                s.add(new_user)
                s.flush()
                # New accounts receive only the company and branch currently
                # selected by the administrator. Additional access is granted
                # explicitly through a future access-management screen.
                s.add(UserCompanyAccess(
                    user_id=new_user.id,
                    company_id=self.user["company_id"],
                    is_default=True,
                ))
                s.add(BranchAccess(
                    user_id=new_user.id,
                    branch_id=self.user["branch_id"],
                ))
                s.add(AuditLog(
                    company_id=self.user["company_id"],
                    username=self.user["username"],
                    action="user_created",
                    entity_type="user",
                    entity_id=str(new_user.id),
                    details=f"Created {new_user.username} with access to current company and branch",
                ))
            username_created = username
            self.refresh_users()
            self._user_create_dialog.accept()
            QMessageBox.information(self, "User created", f"{username_created} can now sign in and change their password.")
        except Exception as e: show_error(self, e)

    def change_own_password(self):
        dialog = PasswordChangeDialog(self.user["username"], require_current=True, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        current, new, confirmation = dialog.current.text(), dialog.new.text(), dialog.confirm.text()
        if not new:
            show_error(self, "Enter a new password."); return
        if new != confirmation:
            show_error(self, "The new passwords do not match."); return
        with SessionLocal.begin() as s:
            user = s.scalar(select(User).where(User.username == self.user["username"]))
            if not user or not verify_password(current, user.password_hash):
                show_error(self, "Current password is incorrect."); return
            user.password_hash = hash_password(new)
            s.add(AuditLog(username=self.user["username"], action="password_changed", entity_type="user",
                           entity_id=str(user.id), details="User changed own password"))
        QMessageBox.information(self, "Password changed", "Your password has been updated.")

    def reset_user_password(self, user_id):
        with SessionLocal() as s:
            target = s.scalar(
                select(User)
                .join(UserCompanyAccess, UserCompanyAccess.user_id == User.id)
                .where(User.id == user_id, UserCompanyAccess.company_id == self.user["company_id"])
            )
            if not target:
                show_error(self, "User was not found."); return
            username = target.username
        dialog = PasswordChangeDialog(username, require_current=False, parent=self)
        if dialog.exec() != QDialog.Accepted:
            return
        new, confirmation = dialog.new.text(), dialog.confirm.text()
        if not new:
            show_error(self, "Enter a new password."); return
        if new != confirmation:
            show_error(self, "The new passwords do not match."); return
        with SessionLocal.begin() as s:
            target = s.scalar(
                select(User)
                .join(UserCompanyAccess, UserCompanyAccess.user_id == User.id)
                .where(User.id == user_id, UserCompanyAccess.company_id == self.user["company_id"])
            )
            if not target:
                show_error(self, "User was not found."); return
            target.password_hash = hash_password(new)
            s.add(AuditLog(
                company_id=self.user["company_id"],
                username=self.user["username"],
                action="password_reset",
                entity_type="user",
                entity_id=str(target.id),
                details=f"Password reset for {target.username}",
            ))
        QMessageBox.information(self, "Password updated", f"Password updated for {username}.")

    def refresh_users(self):
        with SessionLocal() as s:
            rows = list(s.scalars(
                select(User)
                .join(UserCompanyAccess, UserCompanyAccess.user_id == User.id)
                .where(UserCompanyAccess.company_id == self.user["company_id"])
                .order_by(User.username)
            ))
            self.user_table.setRowCount(len(rows))
            for r, u in enumerate(rows):
                for col, val in enumerate([u.username, u.role.title(), "Active" if u.active else "Inactive"]):
                    self.user_table.setItem(r, col, item(val))
                cell = QWidget()
                cell_layout = QHBoxLayout(cell)
                cell_layout.setContentsMargins(2, 2, 2, 2)
                cell_layout.setAlignment(Qt.AlignCenter)
                reset = QPushButton("Set Password")
                reset.setObjectName("userPasswordButton")
                reset.setFixedSize(138, 32)
                reset.clicked.connect(lambda checked=False, uid=u.id: self.reset_user_password(uid))
                cell_layout.addWidget(reset)
                self.user_table.setCellWidget(r, 3, cell)
        self.filter_users(self.user_search.text() if hasattr(self, "user_search") else "" )

    def settings_tab(self):
        w = QWidget(); root = QVBoxLayout(w); form = QFormLayout()
        with SessionLocal() as s:
            settings = s.scalar(select(BusinessSettings).where(BusinessSettings.company_id == self.user["company_id"]).limit(1))
            values = [settings.legal_name, settings.gstin, settings.state_code, settings.address,
                      settings.phone, settings.invoice_prefix, settings.logo_path or "",
                      settings.smtp_host or "smtp.gmail.com", str(settings.smtp_port or 587), settings.smtp_email or ""]
        self.s_name = QLineEdit(values[0]); self.s_gstin = QLineEdit(values[1]); self.s_state = QLineEdit(values[2])
        self.s_address = QLineEdit(values[3]); self.s_phone = QLineEdit(values[4]); self.s_prefix = QLineEdit(values[5])
        self.s_logo_path = QLineEdit(values[6]); self.s_logo_path.setReadOnly(True)
        self.s_smtp_host = QLineEdit(values[7]); self.s_smtp_host.setPlaceholderText("smtp.gmail.com")
        self.s_smtp_port = QLineEdit(values[8]); self.s_smtp_port.setPlaceholderText("587")
        self.s_smtp_email = QLineEdit(values[9]); self.s_smtp_email.setPlaceholderText("you@example.com")
        self.s_logo_preview = QLabel()
        self.s_logo_preview.setMinimumSize(150, 68); self.s_logo_preview.setMaximumSize(180, 80)
        self.s_logo_preview.setAlignment(Qt.AlignCenter)
        self.s_logo_preview.setStyleSheet("background:#F1F5F9;border:1px dashed #CBD5E1;border-radius:8px;color:#64748B;padding:6px;")
        self.update_business_logo_preview()
        choose_logo = QPushButton("Choose Logo"); choose_logo.clicked.connect(self.choose_business_logo)
        clear_logo = QPushButton("Remove"); clear_logo.setObjectName("secondaryButton"); clear_logo.clicked.connect(self.clear_business_logo)
        logo_controls = QHBoxLayout(); logo_controls.addWidget(self.s_logo_preview); logo_controls.addWidget(self.s_logo_path, 1)
        logo_controls.addWidget(choose_logo); logo_controls.addWidget(clear_logo)
        logo_widget = QWidget(); logo_widget.setLayout(logo_controls)
        for label, widget in [("Legal business name", self.s_name), ("Seller GSTIN", self.s_gstin),
                              ("Seller state code (2 digits)", self.s_state), ("Address", self.s_address),
                              ("Phone", self.s_phone), ("Invoice prefix", self.s_prefix),
                              ("Invoice logo (PNG/JPG)", logo_widget)]:
            form.addRow(label, widget)
        email_note = QLabel("Invoice PDFs are attached to outgoing emails. The SMTP app password is requested when you send and is not saved.")
        email_note.setWordWrap(True); email_note.setStyleSheet("color:#64748B;padding:4px 0;")
        form.addRow(QLabel("Invoice email (SMTP)"), email_note)
        form.addRow("SMTP server", self.s_smtp_host)
        form.addRow("SMTP port", self.s_smtp_port)
        form.addRow("Sender email", self.s_smtp_email)
        save = QPushButton("Save business settings"); save.clicked.connect(self.save_settings)
        test_mail = QPushButton("Test SMTP Login"); test_mail.setObjectName("secondaryButton")
        test_mail.clicked.connect(self.test_smtp_settings)
        mail_actions = QHBoxLayout(); mail_actions.addWidget(save); mail_actions.addWidget(test_mail); mail_actions.addStretch()
        root.addLayout(form); root.addLayout(mail_actions); root.addStretch()
        return w

    def test_smtp_settings(self):
        host = self.s_smtp_host.text().strip()
        sender = self.s_smtp_email.text().strip()
        try:
            port = int(self.s_smtp_port.text().strip())
            if not host or not sender or not 1 <= port <= 65535:
                raise ValueError
        except ValueError:
            show_error(self, "Enter a valid SMTP server, port, and sender email first.")
            return
        password, ok = QInputDialog.getText(
            self, "Test SMTP Login", f"SMTP password or app password for {sender}:\nFor Gmail, enter the 16-character App Password without spaces or separators.", QLineEdit.Password
        )
        if not ok:
            return
        if not password:
            show_error(self, "Enter the SMTP password or app password.")
            return
        try:
            password = normalize_smtp_password(host, password)
        except ValueError as exc:
            show_error(self, exc)
            return

        smtp = None
        stage = "connecting to the SMTP server"
        error = None
        try:
            context = ssl.create_default_context()
            smtp = (smtplib.SMTP_SSL(host, port, timeout=25, context=context)
                    if port == 465 else smtplib.SMTP(host, port, timeout=25))
            if port != 465:
                stage = "starting the secure TLS connection"
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
            stage = "authenticating the sender account"
            smtp.login(sender, password)
        except Exception as exc:
            error = exc
        finally:
            if smtp is not None:
                try:
                    smtp.quit()
                except Exception:
                    try:
                        smtp.close()
                    except Exception:
                        pass
        if error:
            show_error(self, f"SMTP login test failed while {stage}. Check the sender email and App Password.\n\n{error}")
        else:
            QMessageBox.information(self, "SMTP login successful", "SMTP authentication succeeded. No email was sent.")

    def update_business_logo_preview(self):
        logo_path = self.s_logo_path.text().strip()
        pixmap = QPixmap(logo_path) if logo_path else QPixmap()
        if not pixmap.isNull():
            self.s_logo_preview.setPixmap(pixmap.scaled(150, 62, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.s_logo_preview.setToolTip(logo_path)
        else:
            self.s_logo_preview.setPixmap(QPixmap())
            self.s_logo_preview.setText("No logo selected")

    def choose_business_logo(self):
        source, _ = QFileDialog.getOpenFileName(self, "Choose business logo", "", "Image files (*.png *.jpg *.jpeg)")
        if not source:
            return
        pixmap = QPixmap(source)
        if pixmap.isNull():
            show_error(self, "This image could not be opened. Choose a PNG or JPEG logo.")
            return
        try:
            assets = Path(__file__).resolve().parent.parent / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            suffix = Path(source).suffix.lower()
            target = assets / f"business_logo{suffix}"
            shutil.copy2(source, target)
            self.s_logo_path.setText(str(target))
            self.update_business_logo_preview()
        except Exception as exc:
            show_error(self, f"Could not save the logo: {exc}")

    def clear_business_logo(self):
        self.s_logo_path.clear()
        self.update_business_logo_preview()

    def save_settings(self):
        if len(self.s_state.text().strip()) != 2 or not self.s_prefix.text().strip():
            show_error(self, "Enter a two-digit state code and invoice prefix."); return
        try:
            smtp_port = int(self.s_smtp_port.text().strip())
            if not 1 <= smtp_port <= 65535:
                raise ValueError
        except ValueError:
            show_error(self, "SMTP port must be a number from 1 to 65535."); return
        with SessionLocal.begin() as s:
            settings = s.scalar(select(BusinessSettings).where(BusinessSettings.company_id == self.user["company_id"]).limit(1))
            settings.legal_name = self.s_name.text().strip()
            settings.gstin = self.s_gstin.text().strip().upper()
            settings.state_code = self.s_state.text().strip()
            settings.address = self.s_address.text().strip()
            settings.phone = self.s_phone.text().strip()
            settings.invoice_prefix = self.s_prefix.text().strip()
            settings.logo_path = self.s_logo_path.text().strip()
            settings.smtp_host = self.s_smtp_host.text().strip() or "smtp.gmail.com"
            settings.smtp_port = smtp_port
            settings.smtp_email = self.s_smtp_email.text().strip()
        QMessageBox.information(self, "Saved", "Business settings saved.")
