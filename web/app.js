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
    ["auth-view","onboarding-view","complete-view"].forEach(id => $(id).hidden = id !== view);
    $("page-label").textContent = view === "auth-view" ? "Get started" : view === "onboarding-view" ? "Business setup" : "Setup saved";
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
    show("complete-view");
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
