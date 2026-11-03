(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const state = { accessToken: null, refreshToken: null, tenant: null, user: null, profile: null };
  const stateOptions = [
    ["01","Jammu and Kashmir"],["02","Himachal Pradesh"],["03","Punjab"],["04","Chandigarh"],
    ["05","Uttarakhand"],["06","Haryana"],["07","Delhi"],["08","Rajasthan"],["09","Uttar Pradesh"],
    ["10","Bihar"],["11","Sikkim"],["12","Arunachal Pradesh"],["13","Nagaland"],["14","Manipur"],
    ["15","Mizoram"],["16","Tripura"],["17","Meghalaya"],["18","Assam"],["19","West Bengal"],
    ["20","Jharkhand"],["21","Odisha"],["22","Chhattisgarh"],["23","Madhya Pradesh"],
    ["24","Gujarat"],["26","Dadra and Nagar Haveli and Daman and Diu"],["27","Maharashtra"],
    ["29","Karnataka"],["30","Goa"],["31","Lakshadweep"],["32","Kerala"],["33","Tamil Nadu"],
    ["34","Puducherry"],["35","Andaman and Nicobar Islands"],["36","Telangana"],["37","Andhra Pradesh"],
    ["38","Ladakh"],["97","Other Territory"]
  ];

  function notice(message, kind = "error") {
    const el = $("notice");
    el.textContent = message;
    el.className = "notice " + kind;
    el.hidden = false;
    el.scrollIntoView({behavior:"smooth", block:"nearest"});
  }
  function clearNotice() { $("notice").hidden = true; }
  async function api(path, options = {}) {
    const headers = {"Content-Type":"application/json", ...(options.headers || {})};
    if (state.accessToken) headers.Authorization = "Bearer " + state.accessToken;
    const response = await fetch(path, {...options, headers});
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(body.detail || "Request failed. Please try again.");
    return body;
  }
  function show(view) {
    ["auth-view","onboarding-view","complete-view","dashboard-view","module-view"].forEach(id => { const el=$(id); if(el) el.hidden = id !== view; });
    const nav=$("module-nav");
    // Keep navigation available after sign-in, including while editing Business Setup.
    if(nav) nav.style.display = view === "auth-view" ? "none" : "";
    $("page-label").textContent = view === "auth-view" ? "Get started" : view === "onboarding-view" ? "Business setup" : view === "dashboard-view" ? "Dashboard" : view === "module-view" ? $("module-title").textContent : "Workspace";
  }
  function setBusy(form, busy, label) {
    const button = form.querySelector('button[type="submit"]');
    if (!button) return;
    if (busy) { button.dataset.label = button.innerHTML; button.disabled = true; button.textContent = label; }
    else { button.disabled = false; button.innerHTML = button.dataset.label || button.innerHTML; }
  }
  function setSession(data) {
    state.accessToken = data.access_token;
    state.tenant = data.tenant;
    state.user = data.user;
    $("workspace-label").textContent = data.tenant.name;
    $("workspace-code").textContent = data.tenant.slug;
    $("login-form").elements.namedItem("tenant_slug").value = data.tenant.slug;
    $("user-label").textContent = data.user.name;
    $("avatar").textContent = (data.user.name || "E").trim().charAt(0).toUpperCase();
  }
  function selectTab(tab) {
    const login = tab === "login";
    $("login-tab").classList.toggle("active", login);
    $("register-tab").classList.toggle("active", !login);
    $("login-tab").setAttribute("aria-selected", String(login));
    $("register-tab").setAttribute("aria-selected", String(!login));
    $("login-form").hidden = !login;
    $("register-form").hidden = login;
    clearNotice();
  }
  function fillProfile(profile) {
    const form = $("business-form");
    Object.entries(profile).forEach(([key,value]) => {
      const field = form.elements.namedItem(key);
      if (field && value !== null && value !== undefined) field.value = value;
    });
    $("gstin").required = $("gst-type").value !== "unregistered";
    $("gst-required-label").textContent = $("gstin").required ? "Required for selected type" : "Not required";
  }
  function renderComplete(profile) {
    state.profile = profile;
    $("complete-summary").textContent = profile.trade_name + " is saved in " + state.tenant.name + ".";
    const entries = [
      ["Workspace code",state.tenant.slug],["Business",profile.trade_name],["GSTIN",profile.gstin || "Unregistered"],
      ["State",stateOptions.find(x => x[0] === profile.state_code)?.[1] || profile.state_code],
      ["Branch",profile.first_branch_name],["Warehouse",profile.first_warehouse_name],
      ...(profile.erp_setup ? [
        ["ERP company ID",String(profile.erp_setup.company.id)],
        ["ERP branch ID",String(profile.erp_setup.branch.id)],
        ["ERP warehouse ID",String(profile.erp_setup.warehouse.id)]
      ] : []),
      ["Financial year",profile.financial_year_start_month === 4 ? "April – March" : "January – December"]
    ];
    $("complete-details").replaceChildren(...entries.map(([label,value]) => {
      const cell = document.createElement("div"); cell.className = "detail-cell";
      const small = document.createElement("small"); small.textContent = label;
      const strong = document.createElement("strong"); strong.textContent = value;
      cell.append(small,strong); return cell;
    }));
    show("dashboard-view");
    loadDashboard();
  }
  async function enterWorkspace() {
    show("onboarding-view");
    try {
      const profile = await api("/onboarding/business");
      fillProfile(profile); renderComplete(profile);
    } catch (error) {
      if (error.message.includes("not been saved")) {
        $("business-form").reset();
        $("business-form").elements.namedItem("first_branch_name").value = "Main Branch";
        $("business-form").elements.namedItem("first_warehouse_name").value = "Main Warehouse";
        $("state-code").value = "";
        $("gstin").required = true;
      } else notice(error.message);
    }
  }

  stateOptions.forEach(([code,name]) => {
    const option = document.createElement("option"); option.value = code; option.textContent = code + " · " + name;
    $("state-code").append(option);
  });
  $("login-tab").addEventListener("click", () => selectTab("login"));
  $("register-tab").addEventListener("click", () => selectTab("register"));
  $("gst-type").addEventListener("change", () => {
    const required = $("gst-type").value !== "unregistered";
    $("gstin").required = required;
    $("gst-required-label").textContent = required ? "Required for selected type" : "Not required";
  });
  $("gstin").addEventListener("input", event => { event.target.value = event.target.value.toUpperCase().replace(/[^0-9A-Z]/g,"").slice(0,15); });
  $("state-code").addEventListener("change", () => {
    const gstin = $("gstin").value;
    if (gstin.length === 15 && gstin.slice(0,2) !== $("state-code").value) notice("The GSTIN state code does not match the selected state.");
    else clearNotice();
  });

  $("register-form").addEventListener("submit", async event => {
    event.preventDefault(); clearNotice();
    const form = event.currentTarget; setBusy(form,true,"Creating workspace…");
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await api("/auth/register",{method:"POST",body:JSON.stringify(data)});
      setSession(result);
      notice("Workspace created. Now add your business details.", "success");
      await enterWorkspace();
    } catch(error) { notice(error.message); }
    finally { setBusy(form,false); }
  });
  $("login-form").addEventListener("submit", async event => {
    event.preventDefault(); clearNotice();
    const form = event.currentTarget; setBusy(form,true,"Signing in…");
    const data = Object.fromEntries(new FormData(form).entries());
    try {
      const result = await api("/auth/login",{method:"POST",body:JSON.stringify(data)});
      setSession(result); await enterWorkspace();
    } catch(error) { notice(error.message); }
    finally { setBusy(form,false); }
  });
  $("business-form").addEventListener("submit", async event => {
    event.preventDefault(); clearNotice();
    const form = event.currentTarget; setBusy(form,true,"Saving business setup…");
    const data = Object.fromEntries(new FormData(form).entries());
    data.financial_year_start_month = Number(data.financial_year_start_month);
    data.gstin = (data.gstin || "").toUpperCase().trim();
    try {
      const profile = await api("/onboarding/business",{method:"PUT",body:JSON.stringify(data)});
      renderComplete(profile); notice("Business profile saved successfully.", "success");
    } catch(error) { notice(error.message); }
    finally { setBusy(form,false); }
  });
  $("edit-setup-button").addEventListener("click", () => {
    fillProfile(state.profile); show("onboarding-view"); clearNotice();
  });
  async function signOut() {
    try {
      await fetch("/auth/logout",{method:"POST",credentials:"same-origin"});
    } finally {
      state.accessToken = null; state.tenant = null; state.user = null; state.profile = null;
      $("user-label").textContent = "Not signed in"; $("avatar").textContent = "E"; $("workspace-label").textContent = "Your workspace";
      selectTab("login"); show("auth-view"); notice("You have signed out.", "success");
    }
  }
  $("signout-button").addEventListener("click", signOut);
  $("signout-complete-button").addEventListener("click", signOut);

  const money = v => new Intl.NumberFormat("en-IN",{style:"currency",currency:"INR",maximumFractionDigits:2}).format(Number(v||0));
  const esc = v => String(v??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const meta={sales:["SALES","Sales & invoices","Invoices and customer receipts"],purchases:["PROCUREMENT","Purchases","Supplier bills and stock inward"],inventory:["INVENTORY","Products & stock","Product master records"],customers:["RELATIONSHIPS","Customers","Customer master records"],suppliers:["RELATIONSHIPS","Suppliers","Supplier master records"],accounting:["FINANCE","Accounting","Chart of accounts and trial balance"],reports:["INSIGHTS","Financial reports","Profit & Loss, Balance Sheet and cash/bank summary"],business:["SETUP","Business setup","Workspace business profile"]};
  async function loadDashboard(){
    if(!state.accessToken)return;
    $("welcome-title").textContent="Welcome back, "+(state.user?.name||"there");
    $("dash-title").textContent=state.tenant?.name||"Business dashboard";
    $("dash-subtitle").textContent=(state.profile?.trade_name||"Your business")+" · Workspace overview";
    const urls=["/erp/sales/invoices","/erp/purchases/bills","/erp/products","/erp/customers","/erp/suppliers"];
    const vals=await Promise.all(urls.map(u=>api(u).catch(()=>({items:[]}))));
    const [sales,purchases,products,customers,suppliers]=vals.map(v=>v.items||[]);
    const cards=[["Sales invoices",sales.length,"↗","violet"],["Purchase bills",purchases.length,"↙","blue"],["Products",products.length,"◇","purple"],["Customers",customers.length,"♙","green"]];
    $("kpi-grid").innerHTML=cards.map(x=>'<article class="kpi-card '+x[3]+'"><span class="kpi-icon">'+x[2]+'</span><div><small>'+x[0]+'</small><strong>'+x[1]+'</strong><em>Records in this workspace</em></div></article>').join("");
    $("recent-sales").innerHTML=sales.length?sales.slice(-5).reverse().map(r=>'<div class="data-row"><div><strong>'+esc(r.invoice_number||("Invoice #"+r.id))+'</strong><small>'+esc(r.customer_name||"Sales invoice")+'</small></div><b>'+money(r.grand_total)+'</b></div>').join(""):'<div class="empty-state">No sales invoices yet. Start from the Sales module.</div>';
    $("workspace-snapshot").innerHTML=[["Products",products.length],["Customers",customers.length],["Suppliers",suppliers.length],["Purchase bills",purchases.length]].map(x=>'<div class="snapshot-item"><small>'+x[0]+'</small><strong>'+x[1]+'</strong></div>').join("");
    const today=new Date().toISOString().slice(0,10),start=today.slice(0,4)+"-01-01";
    try{const cash=await api("/erp/accounting/cash-flow?from_date="+start+"&to_date="+today);$("cash-summary").innerHTML='<div class="snapshot-item"><small>Net cash & bank movement</small><strong>'+money(cash.net_cash_bank_movement)+'</strong></div>'+(cash.accounts||[]).map(a=>'<div class="snapshot-item"><small>'+esc(a.name)+'</small><strong>'+money(a.net_movement)+'</strong></div>').join("");}catch(e){$("cash-summary").innerHTML='<div class="empty-state">No cash/bank summary available.</div>';}
  }
  function makeTable(headers,rows){return rows.length?'<div class="table-wrap"><table class="module-table"><thead><tr>'+headers.map(x=>'<th>'+esc(x)+'</th>').join("")+'</tr></thead><tbody>'+rows.map(r=>'<tr>'+r.map(x=>'<td>'+esc(x)+'</td>').join("")+'</tr>').join("")+'</tbody></table></div>':'<div class="module-empty"><div class="module-empty-icon">＋</div><h3>No records yet</h3><p>This workspace is new, so there are no records in this section. Once you add your first record, it will appear here.</p><small>Next: create forms and connect them to the ERP APIs.</small></div>';}

  let activeModule="dashboard", moduleCache={};
  function formField(label,name,type="text",required=true,extra=""){return '<label class="erp-field"><span>'+label+'</span><input name="'+name+'" type="'+type+'" '+(required?"required":"")+' '+extra+'></label>';}
  function selectField(label,name,options){return '<label class="erp-field"><span>'+label+'</span><select name="'+name+'" required>'+options.map(o=>'<option value="'+esc(o[0])+(String(o[0])===String(state.profile?.state_code) ? '" selected>' : '">')+esc(o[1])+'</option>').join("")+'</select></label>';}
  function showCreateForm(key){
    const data=moduleCache;
    const customerOptions=(data.customers||[]).map(x=>[x.id,x.name]);
    const supplierOptions=(data.suppliers||[]).map(x=>[x.id,x.name]);
    const productOptions=(data.products||[]).map(x=>[x.id,x.sku+" · "+x.name]);
    let title="",fields="";
    if(key==="customers"){title="Add customer";fields=formField("Customer name","name")+formField("GSTIN","gstin", "text",false)+selectField("State", "state_code",stateOptions)+formField("Phone","phone","tel",false)+formField("Email","email","email",false)+formField("Address","address","text",false);}
    if(key==="suppliers"){title="Add supplier";fields=formField("Supplier name","name")+formField("GSTIN","gstin","text",false)+selectField("State","state_code",stateOptions)+formField("Phone","phone","tel",false)+formField("Address","address","text",false);}
    if(key==="inventory"){title="Add product";fields=formField("SKU","sku")+formField("Product name","name")+formField("HSN / SAC","hsn_sac","text",false)+formField("Unit","unit","text",true,'value="Nos"')+formField("Selling price (₹)","selling_price","number",true,'min="0" step="0.01"')+formField("Purchase price (₹)","purchase_price","number",true,'min="0" step="0.01" value="0"')+formField("GST rate (%)","gst_rate","number",true,'min="0" max="100" step="0.01" value="18"')+formField("Opening stock","opening_stock","number",true,'min="0" step="0.001" value="0"')+formField("Reorder level","reorder_level","number",true,'min="0" step="0.001" value="0"');}
    if(key==="sales"){title="Create sales invoice";if(!customerOptions.length||!productOptions.length){notice("Add at least one customer and one product before creating an invoice.");return;}fields=selectField("Customer","customer_id",customerOptions)+formField("Invoice date","invoice_date","date",true,'value="'+new Date().toISOString().slice(0,10)+'"')+selectField("Product","product_id",productOptions)+formField("Quantity","quantity","number",true,'min="0.001" step="0.001" value="1"')+formField("Unit price (₹)","unit_price","number",false,'min="0" step="0.01"')+formField("Discount (₹)","discount_amount","number",false,'min="0" step="0.01" value="0"');}
    if(key==="purchases"){title="Create purchase bill";if(!supplierOptions.length||!productOptions.length){notice("Add at least one supplier and one product before creating a purchase bill.");return;}fields=selectField("Supplier","supplier_id",supplierOptions)+formField("Supplier invoice number","supplier_invoice_number","text",false)+formField("Purchase date","purchase_date","date",true,'value="'+new Date().toISOString().slice(0,10)+'"')+selectField("Product","product_id",productOptions)+formField("Quantity","quantity","number",true,'min="0.001" step="0.001" value="1"')+formField("Unit cost (₹)","unit_cost","number",true,'min="0" step="0.01"')+formField("Discount (₹)","discount_amount","number",false,'min="0" step="0.01" value="0"');}
    if(!fields)return;
    $("module-content").innerHTML='<div class="form-panel"><div class="form-panel-head"><div><span class="eyebrow">NEW RECORD</span><h2>'+title+'</h2><p>Saved directly to this workspace and its company records.</p></div><button type="button" class="secondary-button" id="cancel-create">Cancel</button></div><form id="module-create-form" class="erp-form-grid">'+fields+'<div class="form-submit"><button class="primary-button" type="submit">Save '+(key==="sales"?"invoice":key==="purchases"?"bill":"record")+'</button></div></form></div>';
    $("cancel-create").addEventListener("click",()=>openModule(key));
    $("module-create-form").addEventListener("submit",async e=>{
      e.preventDefault();const form=e.currentTarget;const v=Object.fromEntries(new FormData(form).entries());
      const btn=form.querySelector('[type=submit]');btn.disabled=true;btn.textContent="Saving…";
      try{
        let path="/erp/"+key,body=v;
        if(key==="sales"){path="/erp/sales/invoices";body={customer_id:Number(v.customer_id),invoice_date:v.invoice_date,items:[{product_id:Number(v.product_id),quantity:v.quantity,unit_price:v.unit_price? v.unit_price:null,discount_amount:v.discount_amount||"0"}]};}
        if(key==="purchases"){path="/erp/purchases/bills";body={supplier_id:Number(v.supplier_id),supplier_invoice_number:v.supplier_invoice_number||"",purchase_date:v.purchase_date,items:[{product_id:Number(v.product_id),quantity:v.quantity,unit_cost:v.unit_cost,discount_amount:v.discount_amount||"0"}]};}
        const result=await api(path,{method:"POST",body:JSON.stringify(body)});
        notice((result.invoice_number||result.purchase_number||result.name||result.sku||"Record")+" saved successfully.","success");
        await openModule(key);
      }catch(err){notice(err.message);btn.disabled=false;btn.textContent="Try again";}
    });
  }
  async function openModule(key){
    activeModule=key;
    if(key==="dashboard"){show("dashboard-view");await loadDashboard();return;}
    if(key==="business"){show("onboarding-view");$("page-label").textContent="Business setup";try{const profile=await api("/onboarding/business");state.profile=profile;fillProfile(profile);}catch(e){notice("Could not load business setup: "+e.message);}return;}
    if(!meta[key])return;
    show("module-view");$("module-eyebrow").textContent=meta[key][0];$("module-title").textContent=meta[key][1];$("module-description").textContent=meta[key][2];
    const create=$("module-create-action");const createLabels={customers:"＋ Add customer",suppliers:"＋ Add supplier",inventory:"＋ Add product",sales:"＋ New invoice",purchases:"＋ New purchase bill"};
    create.hidden=!createLabels[key];create.textContent=createLabels[key]||"＋ Create new";create.onclick=()=>showCreateForm(key);
    $("module-content").innerHTML='<div class="loading-state">Loading workspace data…</div>';
    try{
      if(key==="accounting"){
        const [a,t,j]=await Promise.all([api("/erp/accounting/accounts"),api("/erp/accounting/trial-balance"),api("/erp/accounting/journals?limit=20")]);
        $("module-content").innerHTML='<div class="report-summary"><div><small>Debits</small><strong>'+money(t.total_debit)+'</strong></div><div><small>Credits</small><strong>'+money(t.total_credit)+'</strong></div><div><small>Trial balance</small><strong>'+(t.balanced?"Balanced":"Review")+'</strong></div></div><h3 class="section-heading">Chart of accounts</h3>'+makeTable(["Code","Account","Type"],a.items.map(x=>[x.code,x.name,x.account_type]))+'<h3 class="section-heading">Recent journal entries</h3>'+makeTable(["Journal","Date","Narration","Status"],j.items.map(x=>[x.journal_number,x.entry_date,x.narration,x.status]));return;
      }
      if(key==="reports"){
        const today=new Date().toISOString().slice(0,10),start=today.slice(0,4)+"-01-01";
        const [p,b,c]=await Promise.all([api("/erp/accounting/profit-loss?from_date="+start+"&to_date="+today),api("/erp/accounting/balance-sheet?as_of="+today),api("/erp/accounting/cash-flow?from_date="+start+"&to_date="+today)]);
        $("module-content").innerHTML='<div class="report-summary">'+[["Income",p.total_income],["Expenses",p.total_expenses],["Net profit",p.net_profit],["Assets",b.total_assets],["Liabilities",b.total_liabilities],["Equity",b.total_equity],["Cash & bank movement",c.net_cash_bank_movement]].map(x=>'<div><small>'+x[0]+'</small><strong>'+money(x[1])+'</strong></div>').join("")+'</div><p class="report-note">Based on posted journals. Cash & bank is a ledger movement summary, not a statutory cash flow statement.</p>';return;
      }
      const map={sales:["/erp/sales/invoices",["Invoice","Date","Customer","Total","Paid","Balance","Status"],r=>[r.invoice_number,r.invoice_date,r.customer_name,money(r.grand_total),money(r.amount_paid),money(r.balance_due),r.status]],purchases:["/erp/purchases/bills",["Bill","Date","Supplier","Total","Paid","Balance","Status"],r=>[r.purchase_number,r.purchase_date,r.supplier_name,money(r.grand_total),money(r.amount_paid),money(r.balance_due),r.status]],inventory:["/erp/products",["SKU","Product","Unit","Selling price","GST","Stock","Reorder"],r=>[r.sku,r.name,r.unit,money(r.selling_price),r.gst_rate+"%",r.stock_qty||"0",r.reorder_level||"0"]],customers:["/erp/customers",["Customer","GSTIN","State","Phone","Email"],r=>[r.name,r.gstin||"—",r.state_code||"—",r.phone||"—",r.email||"—"]],suppliers:["/erp/suppliers",["Supplier","GSTIN","State","Phone"],r=>[r.name,r.gstin||"—",r.state_code||"—",r.phone||"—"]]};
      const [url,heads,fn]=map[key],data=await api(url);moduleCache[key]=data.items||[];
      if(key==="sales")moduleCache.customers=(await api("/erp/customers")).items||[];
      if(key==="purchases")moduleCache.suppliers=(await api("/erp/suppliers")).items||[];
      if(["sales","purchases"].includes(key))moduleCache.products=(await api("/erp/products")).items||[];
      $("module-content").innerHTML=makeTable(heads,(data.items||[]).map(fn));
    }catch(e){$("module-content").innerHTML='<div class="empty-state">'+esc(e.message)+'</div>';}
  }
  $("module-nav").addEventListener("click",e=>{const a=e.target.closest("[data-page]");if(!a)return;e.preventDefault();$("module-nav").querySelectorAll(".nav-item").forEach(n=>n.classList.toggle("active",n===a));openModule(a.dataset.page);});
  document.querySelectorAll("[data-go]").forEach(b=>b.addEventListener("click",()=>openModule(b.dataset.go)));
  $("refresh-dashboard").addEventListener("click",loadDashboard);$("module-refresh").addEventListener("click",()=>openModule(location.hash.slice(1)||"dashboard"));

  show("auth-view");
  // Restore the session after a reload by rotating the HttpOnly refresh cookie.
  (async () => {
    try {
      const restored = await api("/auth/refresh", {method:"POST", credentials:"same-origin"});
      setSession(restored);
      await enterWorkspace();
    } catch (_) {
      // No valid cookie means this is a signed-out browser; keep the login screen.
    }
  })();
})();
