
from decimal import Decimal, ROUND_HALF_UP
from datetime import date, datetime, time

from sqlalchemy import select, func

from .db import (
    SessionLocal,
    BusinessSettings,
    Customer,
    Product,
    Invoice,
    InvoiceItem,
    Payment,
    StockMovement,
    AuditLog,
    Supplier,
    Purchase,
    PurchaseItem,
    SupplierPayment,
    ProductStock,
    Company,
    Branch,
    Warehouse,
    User,
    money,
    qty,
)

from .access import validate_user_context

def round_money(value):
    return Decimal(str(value)).quantize(
        Decimal("0.01"),
        rounding=ROUND_HALF_UP,
    )


def audit(
    session,
    username,
    action,
    entity_type="",
    entity_id="",
    details="",
    company_id=1,
):
    session.add(
        AuditLog(
            username=username,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
            company_id=company_id,
        )
    )



def _authorize_user_context(session, user_id, company_id, branch_id, warehouse_id):
    """Require an active user and an explicitly assigned active ERP context."""
    if user_id is None:
        raise PermissionError("A signed-in user is required for this operation.")
    user = session.get(User, int(user_id))
    if not user or not user.active:
        raise PermissionError("This user account is unavailable or inactive.")
    return validate_user_context(
        session,
        int(user_id),
        int(company_id),
        int(branch_id),
        int(warehouse_id),
    )


def _company_context(session, company_id, branch_id=None, warehouse_id=None):
    company = session.get(Company, int(company_id))
    if not company or not company.active:
        raise ValueError("Select a valid active company.")
    branch = None
    warehouse = None
    if branch_id is not None:
        branch = session.get(Branch, int(branch_id))
        if not branch or not branch.active or branch.company_id != company.id:
            raise ValueError("Selected branch does not belong to this company.")
    if warehouse_id is not None:
        warehouse = session.get(Warehouse, int(warehouse_id))
        if (not warehouse or not warehouse.active or warehouse.company_id != company.id
                or (branch is not None and warehouse.branch_id != branch.id)):
            raise ValueError("Selected warehouse does not belong to this company and branch.")
    return company, branch, warehouse


def _company_settings(session, company_id):
    settings = session.scalar(
        select(BusinessSettings).where(BusinessSettings.company_id == int(company_id)).order_by(BusinessSettings.id).limit(1)
    )
    if not settings:
        raise ValueError("Business settings are not configured for this company.")
    return settings


def _company_product(session, product_id, company_id):
    product = session.scalar(select(Product).where(
        Product.id == int(product_id), Product.company_id == int(company_id)
    ))
    if not product or not product.active:
        raise ValueError("Selected product is unavailable in this company.")
    return product


def _company_customer(session, customer_id, company_id):
    customer = session.scalar(select(Customer).where(
        Customer.id == int(customer_id), Customer.company_id == int(company_id)
    ))
    if not customer or not customer.active:
        raise ValueError("Selected customer is unavailable in this company.")
    return customer


def _company_supplier(session, supplier_id, company_id):
    supplier = session.scalar(select(Supplier).where(
        Supplier.id == int(supplier_id), Supplier.company_id == int(company_id)
    ))
    if not supplier or not supplier.active:
        raise ValueError("Selected supplier is unavailable in this company.")
    return supplier


def _stock_row(session, product, warehouse_id, company_id):
    row = session.scalar(select(ProductStock).where(
        ProductStock.product_id == product.id,
        ProductStock.warehouse_id == int(warehouse_id),
        ProductStock.company_id == int(company_id),
    ))
    if row is None:
        row = ProductStock(
            product_id=product.id, warehouse_id=int(warehouse_id),
            company_id=int(company_id), quantity=product.stock_qty or 0,
            reorder_level=product.reorder_level or 0,
        )
        session.add(row)
        session.flush()
    return row


def add_customer(
    name,
    gstin="",
    state_code="32",
    address="",
    phone="",
    email="",
    credit_limit="10000",
    *,
    user_id,
    company_id,
    branch_id,
    warehouse_id,
):
    with SessionLocal.begin() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        obj = Customer(
            company_id=int(company_id),
            name=name.strip(),
            gstin=gstin.strip().upper(),
            state_code=state_code.strip(),
            address=address.strip(),
            phone=phone.strip(),
            email=email.strip(),
            credit_limit=money(credit_limit),
        )

        s.add(obj)
        s.flush()

        audit(
            s,
            "admin",
            "customer_created",
            "customer",
            obj.id,
            obj.name,
            company_id=company_id,
        )

        return obj.id


def add_product(
    sku,
    name,
    hsn_sac="",
    unit="Nos",
    selling_price="0",
    purchase_price="0",
    gst_rate="18",
    opening_stock="0",
    reorder_level="0",
    *,
    user_id,
    company_id,
    branch_id,
    warehouse_id,
):
    with SessionLocal.begin() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        obj = Product(
            company_id=int(company_id),
            sku=sku.strip(),
            name=name.strip(),
            hsn_sac=hsn_sac.strip(),
            unit=unit.strip(),
            selling_price=money(selling_price),
            purchase_price=money(purchase_price),
            gst_rate=money(gst_rate),
            stock_qty=qty(opening_stock),
            reorder_level=qty(reorder_level),
        )

        s.add(obj)
        s.flush()

        opening_qty = qty(opening_stock)

        stock = _stock_row(s, obj, warehouse_id, company_id)
        stock.quantity = opening_qty
        stock.reorder_level = qty(reorder_level)
        if opening_qty != 0:
            s.add(
                StockMovement(
                    company_id=int(company_id), branch_id=int(branch_id),
                    warehouse_id=int(warehouse_id), product_id=obj.id,
                    quantity_delta=opening_qty,
                    reason="opening_stock",
                    reference="OPENING",
                    created_by="admin",
                )
            )

        audit(
            s,
            "admin",
            "product_created",
            "product",
            obj.id,
            obj.name,
            company_id=company_id,
        )

        return obj.id


def _prepare_invoice_preview(
    session,
    settings,
    customer,
    line_items,
    company_id,
    warehouse_id,
):
    """Calculate invoice totals and validate company-owned products and warehouse stock."""

    if not line_items:
        raise ValueError("Add at least one product.")

    interstate = settings.state_code != customer.state_code

    lines = []
    stock_requested = {}

    taxable_total = Decimal("0.00")
    cgst_total = Decimal("0.00")
    sgst_total = Decimal("0.00")
    igst_total = Decimal("0.00")
    grand_total = Decimal("0.00")

    for line in line_items:
        product = _company_product(session, line["product_id"], company_id)

        quantity = qty(line["quantity"])
        discount = money(line.get("discount_amount", "0"))

        if quantity <= 0:
            raise ValueError(
                f"Quantity must be greater than zero for {product.name}."
            )

        stock_requested[product.id] = (
            stock_requested.get(product.id, qty("0")) + quantity
        )

        gross = round_money(
            quantity * Decimal(str(product.selling_price))
        )

        if discount < 0 or discount > gross:
            raise ValueError(
                f"Invalid discount for {product.name}."
            )

        taxable = round_money(gross - discount)

        rate = Decimal(str(product.gst_rate)) / Decimal("100")
        tax_total = round_money(taxable * rate)

        if interstate:
            cgst = Decimal("0.00")
            sgst = Decimal("0.00")
            igst = tax_total
        else:
            cgst = round_money(tax_total / 2)
            sgst = tax_total - cgst
            igst = Decimal("0.00")

        line_total = taxable + cgst + sgst + igst

        lines.append(
            {
                "product_id": product.id,
                "sku": product.sku,
                "product_name": product.name,
                "quantity": quantity,
                "unit_price": money(product.selling_price),
                "discount_amount": discount,
                "taxable_value": taxable,
                "gst_rate": money(product.gst_rate),
                "cgst_amount": cgst,
                "sgst_amount": sgst,
                "igst_amount": igst,
                "line_total": line_total,
            }
        )

        taxable_total += taxable
        cgst_total += cgst
        sgst_total += sgst
        igst_total += igst
        grand_total += line_total

    # Validate cumulative quantities. This prevents the same product
    # from being oversold when it appears on multiple invoice lines.
    for product_id, requested_qty in stock_requested.items():
        product = _company_product(session, product_id, company_id)
        stock = _stock_row(session, product, warehouse_id, company_id)
        if stock.quantity < requested_qty:
            raise ValueError(
                f"Insufficient stock for {product.name}. "
                f"Available: {stock.quantity}, requested: {requested_qty}"
            )

    return {
        "customer_name": customer.name,
        "is_interstate": interstate,
        "place_of_supply_state_code": customer.state_code,
        "lines": lines,
        "taxable_total": money(taxable_total),
        "cgst_total": money(cgst_total),
        "sgst_total": money(sgst_total),
        "igst_total": money(igst_total),
        "grand_total": money(grand_total),
    }


def calculate_invoice_preview(customer_id, line_items, *, user_id, company_id, branch_id, warehouse_id):
    """Calculate invoice totals without saving an invoice."""

    with SessionLocal() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        settings = _company_settings(s, company_id)
        customer = _company_customer(s, customer_id, company_id)

        if not settings or not customer:
            raise ValueError(
                "Select a valid business configuration and customer."
            )

        return _prepare_invoice_preview(
            s, settings, customer, line_items, company_id, warehouse_id
        )


def create_invoice(
    customer_id,
    line_items,
    username="admin",
    payment_amount="0",
    payment_method="UPI",
    payment_reference="",
    allow_credit_override=False,
    *,
    user_id,
    company_id,
    branch_id,
    warehouse_id,
):
    """
    Create an invoice and update stock.

    line_items:
        [
            {
                "product_id": int,
                "quantity": decimal_or_string,
                "discount_amount": decimal_or_string,
            }
        ]

    Selling prices and GST rates are copied from product master
    when the invoice is issued.
    """

    if not line_items:
        raise ValueError("Add at least one product.")

    with SessionLocal.begin() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        settings = _company_settings(s, company_id)
        customer = _company_customer(s, customer_id, company_id)

        if not settings or not customer:
            raise ValueError(
                "Select a valid business configuration and customer."
            )

        # Revalidate stock and calculate totals inside the same
        # transaction that saves the invoice.
        preview = _prepare_invoice_preview(
            s,
            settings, customer, line_items, company_id, warehouse_id
        )

        paid = money(payment_amount)
        grand_total = preview["grand_total"]

        if paid < 0 or paid > grand_total:
            raise ValueError(
                "Payment must be between zero and invoice total."
            )

        outstanding = s.scalar(
            select(func.coalesce(func.sum(Invoice.grand_total - Invoice.amount_paid), 0))
            .where(Invoice.company_id == int(company_id), Invoice.customer_id == customer.id, Invoice.status == "issued")
        ) or 0
        projected_due = money(Decimal(str(outstanding)) + grand_total - paid)
        limit_amount = money(customer.credit_limit or 0)
        if projected_due > limit_amount and not allow_credit_override:
            raise ValueError(
                f"Credit limit exceeded for {customer.name}. "
                f"Current due: ₹{money(outstanding):.2f}; "
                f"new due after this invoice: ₹{projected_due:.2f}; "
                f"credit limit: ₹{limit_amount:.2f}. "
                "Confirm the override in the invoice screen to proceed."
            )

        invoice_number = (
            f"{settings.invoice_prefix}-C{int(company_id)}-"
            f"{settings.next_invoice_number:06d}"
        )

        settings.next_invoice_number += 1

        inv = Invoice(
            company_id=int(company_id), branch_id=int(branch_id), warehouse_id=int(warehouse_id),
            invoice_number=invoice_number,
            customer_id=customer.id,
            seller_state_code=settings.state_code,
            place_of_supply_state_code=customer.state_code,
            is_interstate=preview["is_interstate"],
            created_by=username,
        )

        s.add(inv)
        s.flush()

        for line in preview["lines"]:
            product = _company_product(s, line["product_id"], company_id)

            # The aggregate stock check above has already validated
            # the total quantity for each product.
            quantity = line["quantity"]

            s.add(
                InvoiceItem(
                    invoice_id=inv.id,
                    product_id=product.id,
                    sku_snapshot=product.sku,
                    description_snapshot=product.name,
                    hsn_sac_snapshot=product.hsn_sac,
                    unit_snapshot=product.unit,
                    quantity=quantity,
                    unit_price=line["unit_price"],
                    discount_amount=line["discount_amount"],
                    gst_rate_snapshot=line["gst_rate"],
                    taxable_value=line["taxable_value"],
                    cgst_amount=line["cgst_amount"],
                    sgst_amount=line["sgst_amount"],
                    igst_amount=line["igst_amount"],
                    line_total=line["line_total"],
                )
            )

            stock = _stock_row(s, product, warehouse_id, company_id)
            stock.quantity = qty(stock.quantity - quantity)
            product.stock_qty = qty(product.stock_qty - quantity)

            s.add(
                StockMovement(
                    company_id=int(company_id), branch_id=int(branch_id),
                    warehouse_id=int(warehouse_id), product_id=product.id,
                    quantity_delta=-quantity,
                    reason="sale",
                    reference=invoice_number,
                    created_by=username,
                )
            )

        inv.taxable_total = preview["taxable_total"]
        inv.cgst_total = preview["cgst_total"]
        inv.sgst_total = preview["sgst_total"]
        inv.igst_total = preview["igst_total"]
        inv.grand_total = grand_total
        inv.amount_paid = paid

        if paid:
            s.add(
                Payment(
                    company_id=int(company_id),
                    invoice_id=inv.id,
                    amount=paid,
                    method=payment_method,
                    reference=payment_reference,
                    recorded_by=username,
                )
            )

        audit(
            s,
            username,
            "invoice_issued",
            "invoice",
            inv.id,
            invoice_number,
            company_id=company_id,
        )

        return inv.id, invoice_number


def record_payment(
    invoice_id,
    amount,
    method,
    reference="",
    username="admin",
    *,
    user_id,
    branch_id,
    warehouse_id,
    company_id,
):
    amount = money(amount)

    if amount <= 0:
        raise ValueError(
            "Payment amount must be greater than zero."
        )

    with SessionLocal.begin() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        inv = s.scalar(select(Invoice).where(
            Invoice.id == int(invoice_id), Invoice.company_id == int(company_id)
        ))
        if not inv:
            raise ValueError("Invoice not found in this company.")

        balance = money(
            inv.grand_total - inv.amount_paid
        )

        if amount > balance:
            raise ValueError(
                f"Payment exceeds outstanding balance of ₹{balance}."
            )

        s.add(
            Payment(
                company_id=int(company_id),
                invoice_id=inv.id,
                amount=amount,
                method=method,
                reference=reference,
                recorded_by=username,
            )
        )

        inv.amount_paid = money(
            inv.amount_paid + amount
        )

        audit(
            s,
            username,
            "payment_recorded",
            "invoice",
            inv.id,
            f"{amount} via {method}",
            company_id=company_id,
        )

        return money(
            inv.grand_total - inv.amount_paid
        )


def add_supplier(
    name,
    gstin="",
    state_code="32",
    address="",
    phone="",
    *,
    user_id,
    branch_id,
    warehouse_id,
    company_id,
):
    if not name.strip() or len(state_code.strip()) != 2:
        raise ValueError(
            "Supplier name and two-digit state code are required."
        )

    with SessionLocal.begin() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        obj = Supplier(
            company_id=int(company_id),
            name=name.strip(),
            gstin=gstin.strip().upper(),
            state_code=state_code.strip(),
            address=address.strip(),
            phone=phone.strip(),
        )

        s.add(obj)
        s.flush()

        audit(
            s,
            "admin",
            "supplier_created",
            "supplier",
            obj.id,
            obj.name,
            company_id=company_id,
        )

        return obj.id


def record_purchase(
    supplier_id,
    supplier_invoice_number,
    product_id=None,
    quantity=None,
    unit_cost=None,
    username="admin",
    purchase_date=None,
    *,
    items=None,
    amount_paid=0,
    payment_method="Bank transfer",
    payment_reference="",
    user_id,
    company_id,
    branch_id,
    warehouse_id,
):
    if items is None:
        items = [{"product_id": product_id, "quantity": quantity, "unit_cost": unit_cost}]
    if not items:
        raise ValueError("Add at least one product to this purchase.")

    with SessionLocal.begin() as s:
        _authorize_user_context(s, user_id, company_id, branch_id, warehouse_id)
        supplier = _company_supplier(s, supplier_id, company_id)

        prepared = []
        taxable_total = Decimal("0.00")
        tax_total = Decimal("0.00")
        paid = money(amount_paid)
        if paid < 0:
            raise ValueError("Payment cannot be negative.")
        for raw in items:
            line_product = _company_product(s, raw["product_id"], company_id)
            line_qty = qty(raw["quantity"])
            line_cost = money(raw["unit_cost"])
            gst_rate = money(raw.get("gst_rate", line_product.gst_rate if line_product else 0))
            if not line_product or not line_product.active:
                raise ValueError("Select a valid active product for every purchase line.")
            if line_qty <= 0 or line_cost < 0 or gst_rate < 0:
                raise ValueError("Quantity must be positive; cost and GST cannot be negative.")
            taxable = round_money(line_qty * line_cost)
            tax = round_money(taxable * gst_rate / Decimal("100"))
            taxable_total += taxable
            tax_total += tax
            prepared.append((line_product, line_qty, line_cost, gst_rate, taxable, tax))

        settings = _company_settings(s, company_id)

        prefix = (
            settings.invoice_prefix if settings else "INV"
        ) + "-PUR"

        purchase_count = s.scalar(select(func.count()).select_from(Purchase).where(
            Purchase.company_id == int(company_id)
        )) or 0
        purchase_number = f"{prefix}-C{int(company_id)}-{purchase_count + 1:06d}"

        grand_total = taxable_total + tax_total
        if paid > grand_total:
            raise ValueError("Payment cannot exceed the purchase total.")

        if isinstance(purchase_date, date) and not isinstance(purchase_date, datetime):
            purchase_date = datetime.combine(purchase_date, time.min)

        purchase = Purchase(
            company_id=int(company_id), branch_id=int(branch_id), warehouse_id=int(warehouse_id),
            purchase_number=purchase_number,
            supplier_id=supplier.id,
            supplier_invoice_number=supplier_invoice_number.strip(),
            purchase_date=purchase_date or datetime.now(),
            created_by=username,
            taxable_total=taxable_total,
            tax_total=tax_total,
            grand_total=grand_total,
            amount_paid=paid,
        )

        s.add(purchase)
        s.flush()

        for line_product, line_qty, line_cost, gst_rate, taxable, tax in prepared:
            s.add(PurchaseItem(
                purchase_id=purchase.id,
                product_id=line_product.id,
                sku_snapshot=line_product.sku,
                description_snapshot=line_product.name,
                hsn_sac_snapshot=line_product.hsn_sac,
                quantity=line_qty,
                unit_cost=line_cost,
                gst_rate_snapshot=gst_rate,
                taxable_value=taxable,
                tax_amount=tax,
                line_total=taxable + tax,
            ))
            stock = _stock_row(s, line_product, warehouse_id, company_id)
            stock.quantity = qty(stock.quantity + line_qty)
            line_product.stock_qty = qty(line_product.stock_qty + line_qty)
            line_product.purchase_price = line_cost
            s.add(StockMovement(company_id=int(company_id), branch_id=int(branch_id),
                                warehouse_id=int(warehouse_id), product_id=line_product.id,
                                quantity_delta=line_qty, reason="purchase",
                                reference=purchase_number, created_by=username))

        if paid > 0:
            s.add(SupplierPayment(company_id=int(company_id), purchase_id=purchase.id, amount=paid,
                                  method=payment_method, reference=payment_reference.strip(),
                                  recorded_by=username))

        audit(
            s,
            username,
            "purchase_recorded",
            "purchase",
            purchase.id,
            purchase_number,
            company_id=company_id,
        )

        return purchase.id, purchase_number


def record_supplier_payment(purchase_id, amount, method="Bank transfer", reference="", username="admin", *, user_id, company_id, branch_id, warehouse_id):
    amount = money(amount)
    if amount <= 0:
        raise ValueError("Payment must be greater than zero.")
    with SessionLocal.begin() as session:
        _authorize_user_context(session, user_id, company_id, branch_id, warehouse_id)
        purchase = session.scalar(select(Purchase).where(
            Purchase.id == int(purchase_id), Purchase.company_id == int(company_id)
        ))
        if not purchase:
            raise ValueError("Purchase not found in this company.")
        due = money(Decimal(str(purchase.grand_total)) - Decimal(str(purchase.amount_paid or 0)))
        if amount > due:
            raise ValueError(f"Payment exceeds the outstanding balance of ₹{due:.2f}.")
        purchase.amount_paid = money(Decimal(str(purchase.amount_paid or 0)) + amount)
        payment = SupplierPayment(company_id=int(company_id), purchase_id=purchase.id, amount=amount, method=method,
                                  reference=reference.strip(), recorded_by=username)
        session.add(payment)
        audit(session, username, "supplier_payment_recorded", "purchase", purchase.id,
              f"Payment {amount:.2f} {method}", company_id=company_id)
        return purchase.amount_paid, money(Decimal(str(purchase.grand_total)) - Decimal(str(purchase.amount_paid)))


def update_purchase(purchase_id, supplier_id, supplier_invoice_number, items, username="admin", purchase_date=None, *, user_id, company_id, branch_id, warehouse_id):
    if not items:
        raise ValueError("Add at least one product to this purchase.")
    with SessionLocal.begin() as session:
        _authorize_user_context(session, user_id, company_id, branch_id, warehouse_id)
        purchase = session.scalar(select(Purchase).where(
            Purchase.id == int(purchase_id), Purchase.company_id == int(company_id)
        ))
        supplier = _company_supplier(session, supplier_id, company_id)
        if not purchase:
            raise ValueError("Select a valid purchase in this company.")
        old_lines = list(session.scalars(select(PurchaseItem).where(PurchaseItem.purchase_id == purchase.id)))
        stock_delta = {}
        for line in old_lines:
            stock_delta[line.product_id] = stock_delta.get(line.product_id, Decimal("0")) - Decimal(str(line.quantity))
        prepared = []
        taxable_total = tax_total = Decimal("0.00")
        for raw in items:
            product = _company_product(session, raw["product_id"], company_id)
            quantity = qty(raw["quantity"]); unit_cost = money(raw["unit_cost"])
            gst_rate = money(raw.get("gst_rate", product.gst_rate if product else 0))
            if not product or not product.active:
                raise ValueError("Select a valid active product for every purchase line.")
            if quantity <= 0 or unit_cost < 0 or gst_rate < 0:
                raise ValueError("Quantity must be positive; cost and GST cannot be negative.")
            taxable = round_money(quantity * unit_cost)
            tax = round_money(taxable * gst_rate / Decimal("100"))
            taxable_total += taxable; tax_total += tax
            stock_delta[product.id] = stock_delta.get(product.id, Decimal("0")) + quantity
            prepared.append((product, quantity, unit_cost, gst_rate, taxable, tax))
        grand_total = taxable_total + tax_total
        if grand_total < Decimal(str(purchase.amount_paid or 0)):
            raise ValueError("Updated purchase total cannot be lower than payments already recorded.")
        for product_id, delta in stock_delta.items():
            product = _company_product(session, product_id, company_id)
            stock = _stock_row(session, product, purchase.warehouse_id, company_id)
            if Decimal(str(stock.quantity)) + delta < 0:
                raise ValueError(f"Cannot reduce this purchase: stock for {product.name} has already been sold or adjusted.")
            stock.quantity = qty(Decimal(str(stock.quantity)) + delta)
            product.stock_qty = qty(Decimal(str(product.stock_qty)) + delta)
            session.add(StockMovement(company_id=int(company_id), branch_id=purchase.branch_id,
                                      warehouse_id=purchase.warehouse_id, product_id=product_id,
                                      quantity_delta=delta, reason="purchase_edit",
                                      reference=purchase.purchase_number, created_by=username))
        for line in old_lines:
            session.delete(line)
        purchase.supplier_id = supplier.id
        purchase.supplier_invoice_number = supplier_invoice_number.strip()
        if purchase_date is not None:
            if isinstance(purchase_date, date) and not isinstance(purchase_date, datetime):
                purchase_date = datetime.combine(purchase_date, time.min)
            purchase.purchase_date = purchase_date
        purchase.taxable_total = taxable_total; purchase.tax_total = tax_total; purchase.grand_total = grand_total
        for product, quantity, unit_cost, gst_rate, taxable, tax in prepared:
            session.add(PurchaseItem(purchase_id=purchase.id, product_id=product.id,
                                     sku_snapshot=product.sku, description_snapshot=product.name,
                                     hsn_sac_snapshot=product.hsn_sac, quantity=quantity, unit_cost=unit_cost,
                                     gst_rate_snapshot=gst_rate, taxable_value=taxable, tax_amount=tax,
                                     line_total=taxable + tax))
            product.purchase_price = unit_cost
        audit(session, username, "purchase_updated", "purchase", purchase.id,
              f"Purchase updated with {len(prepared)} product lines", company_id=company_id)
