"""Admin workspace for company, branch, warehouse and user access setup."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QTabWidget, QLabel,
    QLineEdit, QPushButton, QMessageBox, QTableWidget, QTableWidgetItem,
    QComboBox, QHeaderView, QAbstractItemView
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import (
    SessionLocal, Company, Branch, Warehouse, User, UserCompanyAccess,
    BranchAccess, BusinessSettings, AuditLog,
)


def _cell(value):
    return QTableWidgetItem(str(value if value is not None else ""))


class CompanyManagementPage(QWidget):
    """Company setup and explicit user-to-company/branch assignment UI."""

    def __init__(self, user, parent=None):
        super().__init__(parent)
        self.user = user
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(12)
        heading = QLabel("Company & Access Management")
        heading.setStyleSheet("font-size:21px;font-weight:700;color:#172033;")
        note = QLabel(
            "Create companies, organize branches and warehouses, and grant users "
            "explicit access. Existing company records are not modified."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#64748B;")
        root.addWidget(heading)
        root.addWidget(note)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_companies_tab()
        self._build_branches_tab()
        self._build_warehouses_tab()
        self._build_access_tab()
        self.refresh_all()

    def _message_error(self, exc):
        QMessageBox.critical(self, "Unable to complete action", str(exc))

    def _build_companies_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.company_name = QLineEdit()
        self.company_name.setPlaceholderText("Company display name")
        self.company_legal = QLineEdit()
        self.company_gstin = QLineEdit()
        self.company_state = QLineEdit("32")
        self.company_state.setMaxLength(2)
        self.company_address = QLineEdit()
        self.company_phone = QLineEdit()
        self.company_email = QLineEdit()
        for label, field in [
            ("Company name *", self.company_name),
            ("Legal name", self.company_legal),
            ("GSTIN", self.company_gstin),
            ("State code", self.company_state),
            ("Address", self.company_address),
            ("Phone", self.company_phone),
            ("Email", self.company_email),
        ]:
            form.addRow(label, field)
        layout.addLayout(form)
        add = QPushButton("Create Company")
        add.clicked.connect(self.create_company)
        layout.addWidget(add, 0, Qt.AlignLeft)
        self.company_table = QTableWidget(0, 5)
        self.company_table.setHorizontalHeaderLabels(
            ["ID", "Company", "GSTIN", "State", "Status"]
        )
        self._prepare_table(self.company_table)
        layout.addWidget(self.company_table, 1)
        self.tabs.addTab(page, "Companies")

    def _build_branches_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.branch_company = QComboBox()
        self.branch_name = QLineEdit()
        self.branch_code = QLineEdit()
        self.branch_address = QLineEdit()
        self.branch_phone = QLineEdit()
        form.addRow("Company", self.branch_company)
        form.addRow("Branch name *", self.branch_name)
        form.addRow("Branch code *", self.branch_code)
        form.addRow("Address", self.branch_address)
        form.addRow("Phone", self.branch_phone)
        layout.addLayout(form)
        add = QPushButton("Add Branch")
        add.clicked.connect(self.create_branch)
        layout.addWidget(add, 0, Qt.AlignLeft)
        self.branch_table = QTableWidget(0, 5)
        self.branch_table.setHorizontalHeaderLabels(
            ["ID", "Company", "Branch", "Code", "Status"]
        )
        self._prepare_table(self.branch_table)
        layout.addWidget(self.branch_table, 1)
        self.tabs.addTab(page, "Branches")

    def _build_warehouses_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.warehouse_company = QComboBox()
        self.warehouse_branch = QComboBox()
        self.warehouse_name = QLineEdit()
        self.warehouse_code = QLineEdit()
        self.warehouse_address = QLineEdit()
        form.addRow("Company", self.warehouse_company)
        form.addRow("Branch", self.warehouse_branch)
        form.addRow("Warehouse name *", self.warehouse_name)
        form.addRow("Warehouse code *", self.warehouse_code)
        form.addRow("Address", self.warehouse_address)
        layout.addLayout(form)
        self.warehouse_company.currentIndexChanged.connect(
            self.refresh_warehouse_branches
        )
        add = QPushButton("Add Warehouse")
        add.clicked.connect(self.create_warehouse)
        layout.addWidget(add, 0, Qt.AlignLeft)
        self.warehouse_table = QTableWidget(0, 5)
        self.warehouse_table.setHorizontalHeaderLabels(
            ["ID", "Company", "Branch", "Warehouse", "Code"]
        )
        self._prepare_table(self.warehouse_table)
        layout.addWidget(self.warehouse_table, 1)
        self.tabs.addTab(page, "Warehouses")

    def _build_access_tab(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        form = QFormLayout()
        self.access_user = QComboBox()
        self.access_company = QComboBox()
        self.access_branch = QComboBox()
        form.addRow("User", self.access_user)
        form.addRow("Company", self.access_company)
        form.addRow("Branch", self.access_branch)
        layout.addLayout(form)
        self.access_company.currentIndexChanged.connect(self.refresh_access_branches)
        add = QPushButton("Grant Company & Branch Access")
        add.clicked.connect(self.grant_access)
        layout.addWidget(add, 0, Qt.AlignLeft)
        self.access_table = QTableWidget(0, 4)
        self.access_table.setHorizontalHeaderLabels(
            ["Username", "Company", "Branch", "Default company"]
        )
        self._prepare_table(self.access_table)
        layout.addWidget(self.access_table, 1)
        self.tabs.addTab(page, "User Access")

    @staticmethod
    def _prepare_table(table):
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _accessible_companies(self, session):
        return session.scalars(
            select(Company)
            .join(UserCompanyAccess, UserCompanyAccess.company_id == Company.id)
            .where(
                UserCompanyAccess.user_id == self.user["id"],
                Company.active.is_(True),
            )
            .order_by(Company.name)
        ).all()

    @staticmethod
    def _set_combo(combo, rows, label_fn):
        previous = combo.currentData()
        combo.blockSignals(True)
        combo.clear()
        for row in rows:
            combo.addItem(label_fn(row), row.id)
        if previous is not None:
            index = combo.findData(previous)
            if index >= 0:
                combo.setCurrentIndex(index)
        combo.blockSignals(False)

    def refresh_all(self):
        with SessionLocal() as session:
            companies = self._accessible_companies(session)
            company_ids = [company.id for company in companies]
            self._set_combo(
                self.branch_company, companies, lambda c: c.name
            )
            self._set_combo(
                self.warehouse_company, companies, lambda c: c.name
            )
            self._set_combo(
                self.access_company, companies, lambda c: c.name
            )
            self._set_combo(
                self.access_user,
                session.scalars(select(User).where(User.active.is_(True)).order_by(User.username)).all(),
                lambda u: u.username,
            )

            self.company_table.setRowCount(len(companies))
            for row, company in enumerate(companies):
                values = [company.id, company.name, company.gstin, company.state_code,
                          "Active" if company.active else "Inactive"]
                for col, value in enumerate(values):
                    self.company_table.setItem(row, col, _cell(value))

            branches = session.scalars(
                select(Branch).where(Branch.company_id.in_(company_ids)).order_by(Branch.name)
            ).all() if company_ids else []
            company_names = {c.id: c.name for c in companies}
            self.branch_table.setRowCount(len(branches))
            for row, branch in enumerate(branches):
                values = [branch.id, company_names.get(branch.company_id, ""),
                          branch.name, branch.code, "Active" if branch.active else "Inactive"]
                for col, value in enumerate(values):
                    self.branch_table.setItem(row, col, _cell(value))

            warehouses = session.scalars(
                select(Warehouse).where(Warehouse.company_id.in_(company_ids)).order_by(Warehouse.name)
            ).all() if company_ids else []
            branch_names = {b.id: b.name for b in branches}
            self.warehouse_table.setRowCount(len(warehouses))
            for row, warehouse in enumerate(warehouses):
                values = [warehouse.id, company_names.get(warehouse.company_id, ""),
                          branch_names.get(warehouse.branch_id, ""), warehouse.name, warehouse.code]
                for col, value in enumerate(values):
                    self.warehouse_table.setItem(row, col, _cell(value))

            access_rows = session.execute(
                select(User.username, Company.name, Branch.name, UserCompanyAccess.is_default)
                .join(UserCompanyAccess, UserCompanyAccess.user_id == User.id)
                .join(Company, Company.id == UserCompanyAccess.company_id)
                .join(BranchAccess, BranchAccess.user_id == User.id)
                .join(Branch, Branch.id == BranchAccess.branch_id)
                .where(Company.id.in_(company_ids), Branch.company_id == Company.id)
                .order_by(User.username, Company.name, Branch.name)
            ).all() if company_ids else []
            self.access_table.setRowCount(len(access_rows))
            for row, record in enumerate(access_rows):
                values = [record[0], record[1], record[2],
                          "Yes" if record[3] else "No"]
                for col, value in enumerate(values):
                    self.access_table.setItem(row, col, _cell(value))

        self.refresh_warehouse_branches()
        self.refresh_access_branches()

    def create_company(self):
        name = self.company_name.text().strip()
        if len(name) < 2:
            self._message_error("Enter a company name with at least 2 characters.")
            return
        state = self.company_state.text().strip()
        if len(state) != 2 or not state.isdigit():
            self._message_error("State code must contain exactly two digits.")
            return
        try:
            with SessionLocal.begin() as session:
                company = Company(
                    name=name,
                    legal_name=self.company_legal.text().strip() or name,
                    gstin=self.company_gstin.text().strip().upper(),
                    state_code=state,
                    address=self.company_address.text().strip(),
                    phone=self.company_phone.text().strip(),
                    email=self.company_email.text().strip(),
                )
                session.add(company)
                session.flush()
                branch = Branch(
                    company_id=company.id, name="Main Branch", code="MAIN"
                )
                session.add(branch)
                session.flush()
                warehouse = Warehouse(
                    company_id=company.id, branch_id=branch.id,
                    name="Main Warehouse", code="MAIN"
                )
                session.add(warehouse)
                session.add(BusinessSettings(
                    company_id=company.id,
                    legal_name=company.legal_name,
                    gstin=company.gstin,
                    state_code=company.state_code,
                    address=company.address,
                    phone=company.phone,
                ))
                session.add(UserCompanyAccess(
                    user_id=self.user["id"], company_id=company.id, is_default=False
                ))
                session.add(BranchAccess(
                    user_id=self.user["id"], branch_id=branch.id
                ))
                session.add(AuditLog(
                    company_id=company.id, username=self.user["username"],
                    action="company_created", entity_type="company",
                    entity_id=str(company.id), details=f"Created company {name}",
                ))
            for field in (self.company_name, self.company_legal, self.company_gstin,
                          self.company_address, self.company_phone, self.company_email):
                field.clear()
            self.company_state.setText("32")
            self.refresh_all()
            QMessageBox.information(
                self, "Company created",
                "Company, Main Branch, Main Warehouse and initial business settings were created. "
                "Your administrator account has been granted access; sign in again to select it.",
            )
        except Exception as exc:
            self._message_error(exc)

    def create_branch(self):
        company_id = self.branch_company.currentData()
        name, code = self.branch_name.text().strip(), self.branch_code.text().strip().upper()
        if not company_id or not name or not code:
            self._message_error("Select a company and enter branch name and code.")
            return
        try:
            with SessionLocal.begin() as session:
                branch = Branch(
                    company_id=int(company_id), name=name, code=code,
                    address=self.branch_address.text().strip(),
                    phone=self.branch_phone.text().strip(),
                )
                session.add(branch)
                session.flush()
                session.add(BranchAccess(
                    user_id=self.user["id"], branch_id=branch.id
                ))
                session.add(AuditLog(
                    company_id=int(company_id), username=self.user["username"],
                    action="branch_created", entity_type="branch",
                    entity_id=str(branch.id), details=f"Created branch {name} ({code})",
                ))
            self.branch_name.clear()
            self.branch_code.clear()
            self.branch_address.clear()
            self.branch_phone.clear()
            self.refresh_all()
        except Exception as exc:
            self._message_error(exc)

    def refresh_warehouse_branches(self):
        company_id = self.warehouse_company.currentData()
        with SessionLocal() as session:
            rows = session.scalars(
                select(Branch).where(
                    Branch.company_id == company_id, Branch.active.is_(True)
                ).order_by(Branch.name)
            ).all() if company_id else []
        self._set_combo(self.warehouse_branch, rows, lambda b: b.name)

    def create_warehouse(self):
        company_id = self.warehouse_company.currentData()
        branch_id = self.warehouse_branch.currentData()
        name, code = self.warehouse_name.text().strip(), self.warehouse_code.text().strip().upper()
        if not company_id or not branch_id or not name or not code:
            self._message_error("Select a company and branch, then enter warehouse name and code.")
            return
        try:
            with SessionLocal.begin() as session:
                branch = session.scalar(select(Branch).where(
                    Branch.id == int(branch_id), Branch.company_id == int(company_id)
                ))
                if not branch:
                    raise ValueError("Selected branch does not belong to the selected company.")
                warehouse = Warehouse(
                    company_id=int(company_id), branch_id=int(branch_id),
                    name=name, code=code, address=self.warehouse_address.text().strip(),
                )
                session.add(warehouse)
                session.flush()
                session.add(AuditLog(
                    company_id=int(company_id), username=self.user["username"],
                    action="warehouse_created", entity_type="warehouse",
                    entity_id=str(warehouse.id), details=f"Created warehouse {name} ({code})",
                ))
            self.warehouse_name.clear()
            self.warehouse_code.clear()
            self.warehouse_address.clear()
            self.refresh_all()
        except Exception as exc:
            self._message_error(exc)

    def refresh_access_branches(self):
        company_id = self.access_company.currentData()
        with SessionLocal() as session:
            rows = session.scalars(
                select(Branch).where(
                    Branch.company_id == company_id, Branch.active.is_(True)
                ).order_by(Branch.name)
            ).all() if company_id else []
        self._set_combo(self.access_branch, rows, lambda b: b.name)

    def grant_access(self):
        user_id = self.access_user.currentData()
        company_id = self.access_company.currentData()
        branch_id = self.access_branch.currentData()
        if not user_id or not company_id or not branch_id:
            self._message_error("Select a user, company and branch.")
            return
        try:
            with SessionLocal.begin() as session:
                branch = session.scalar(select(Branch).where(
                    Branch.id == int(branch_id), Branch.company_id == int(company_id)
                ))
                target_user = session.get(User, int(user_id))
                if not branch or not target_user or not target_user.active:
                    raise ValueError("Selected user or branch is unavailable.")
                company_access = session.scalar(select(UserCompanyAccess).where(
                    UserCompanyAccess.user_id == int(user_id),
                    UserCompanyAccess.company_id == int(company_id),
                ))
                if not company_access:
                    session.add(UserCompanyAccess(
                        user_id=int(user_id), company_id=int(company_id), is_default=False
                    ))
                branch_access = session.scalar(select(BranchAccess).where(
                    BranchAccess.user_id == int(user_id),
                    BranchAccess.branch_id == int(branch_id),
                ))
                if not branch_access:
                    session.add(BranchAccess(
                        user_id=int(user_id), branch_id=int(branch_id)
                    ))
                session.add(AuditLog(
                    company_id=int(company_id), username=self.user["username"],
                    action="user_access_granted", entity_type="user",
                    entity_id=str(user_id),
                    details=f"Granted {target_user.username} access to branch {branch.name}",
                ))
            self.refresh_all()
            QMessageBox.information(self, "Access granted", "Company and branch access saved.")
        except Exception as exc:
            self._message_error(exc)
