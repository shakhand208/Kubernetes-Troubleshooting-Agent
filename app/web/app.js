const loginBtn = document.getElementById("login-btn");
const loginStatus = document.getElementById("login-status");
const clusterSection = document.getElementById("cluster-section");
const clusterList = document.getElementById("cluster-list");
const clusterStatus = document.getElementById("cluster-status");
const investigationSection = document.getElementById("investigation-section");
const progressSection = document.getElementById("progress-section");
const diagnosisSection = document.getElementById("diagnosis-section");
const historySection = document.getElementById("history-section");
const form = document.getElementById("investigation-form");
const statusEl = document.getElementById("status");
const progressEl = document.getElementById("progress");
const rootCauseEl = document.getElementById("root-cause");
const confidenceEl = document.getElementById("confidence");
const fixesEl = document.getElementById("fixes");
const preventionEl = document.getElementById("prevention");
const historyBody = document.getElementById("history-body");

let socket = null;
let selectedCluster = null;

function setList(element, items) {
  element.innerHTML = "";
  (items || []).forEach((item) => {
    const li = document.createElement("li");
    li.textContent = item;
    element.appendChild(li);
  });
}

async function loadHistory() {
  const res = await fetch("/api/investigations");
  const rows = await res.json();
  historyBody.innerHTML = "";

  rows.forEach((row) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${new Date(row.created_at).toLocaleString()}</td>
      <td>${row.request.incident_name}</td>
      <td>${row.status}</td>
      <td>${row.report?.root_cause || "—"}</td>
      <td>${row.report?.confidence ?? "—"}</td>
    `;
    historyBody.appendChild(tr);
  });
}

// User must explicitly click login button - no auto-load
loginBtn.addEventListener("click", async () => {
  console.log("Login button clicked");
  loginStatus.textContent = "Checking authentication...";
  try {
    const res = await fetch("/api/auth/status");
    const data = await res.json();
    console.log("Auth status after click:", data);
    if (data.authenticated) {
      showClusterPicker();
    } else {
      loginStatus.textContent = "Not authenticated. Please run 'az login' in a terminal first.";
    }
  } catch (err) {
    console.error("Failed to check auth:", err);
    loginStatus.textContent = "Error checking authentication";
  }
});

async function showClusterPicker() {
  document.getElementById("login-section").style.display = "none";
  clusterSection.style.display = "block";
  clusterStatus.textContent = "Loading clusters...";

  try {
    const res = await fetch("/api/clusters");
    if (res.status === 401) {
      clusterStatus.textContent = "Not authenticated. Run 'az login' first";
      location.reload();
      return;
    }

    const data = await res.json();
    clusterList.innerHTML = "";

    if (!data.clusters || data.clusters.length === 0) {
      clusterStatus.textContent = "No AKS clusters found";
      return;
    }

    data.clusters.forEach((cluster) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "cluster-btn";
      btn.textContent = `${cluster.name} (${cluster.location})`;
      btn.addEventListener("click", () => connectToCluster(cluster));
      clusterList.appendChild(btn);
    });

    clusterStatus.textContent = "";
  } catch (err) {
    clusterStatus.textContent = `Error loading clusters: ${err.message}`;
  }
}

async function connectToCluster(cluster) {
  clusterStatus.textContent = `Connecting to ${cluster.name}...`;

  try {
    const params = new URLSearchParams({
      resource_group: cluster.resource_group,
    });
    const res = await fetch(`/api/clusters/${cluster.name}/connect?${params}`, {
      method: "POST",
    });

    if (!res.ok) {
      const err = await res.json();
      clusterStatus.textContent = `Failed to connect: ${err.detail}`;
      return;
    }

    selectedCluster = cluster;
    clusterStatus.textContent = `Connected to ${cluster.name}`;
    clusterSection.style.display = "block";
    investigationSection.style.display = "block";
    historySection.style.display = "block";
    loadHistory();
    await loadNamespaces();
  } catch (err) {
    clusterStatus.textContent = `Error: ${err.message}`;
  }
}

async function loadNamespaces() {
  try {
    console.log("Loading namespaces...");
    const res = await fetch("/api/namespaces");
    if (!res.ok) throw new Error(`Failed to load namespaces: ${res.status}`);
    
    const data = await res.json();
    console.log("Namespaces data:", data);
    const nsSelect = document.getElementById("namespace");
    
    if (!nsSelect) {
      console.error("Namespace select element not found!");
      return;
    }
    
    nsSelect.innerHTML = "";
    
    if (!data.namespaces || data.namespaces.length === 0) {
      nsSelect.innerHTML = '<option value="">No namespaces found</option>';
      return;
    }
    
    data.namespaces.forEach((ns) => {
      const option = document.createElement("option");
      option.value = ns.name;
      option.textContent = ns.name;
      nsSelect.appendChild(option);
    });
    
    // Select "default" if available
    if (Array.from(nsSelect.options).some(o => o.value === "default")) {
      nsSelect.value = "default";
      await loadWorkloads("default");
    } else if (nsSelect.options.length > 0) {
      nsSelect.value = nsSelect.options[0].value;
      await loadWorkloads(nsSelect.options[0].value);
    }
  } catch (err) {
    console.error("Failed to load namespaces:", err);
    document.getElementById("namespace").innerHTML = '<option value="">Error loading namespaces</option>';
  }
}

async function loadWorkloads(namespace) {
  try {
    const res = await fetch(`/api/namespaces/${namespace}/workloads`);
    if (!res.ok) throw new Error(`Failed to load workloads: ${res.status}`);
    
    const workloads = await res.json();
    const workloadsList = document.getElementById("workloads-list");
    
    if (!workloads || Object.values(workloads).every(w => w.length === 0)) {
      workloadsList.innerHTML = "<p style='color: var(--text-muted);'>No workloads found in this namespace</p>";
      return;
    }
    
    let html = "<div style='display: grid; gap: 10px;'>";
    
    const typeFilter = document.getElementById("workload_type").value;
    let buttonCount = 0;
    
    for (const [type, items] of Object.entries(workloads)) {
      if (items.length === 0) continue;
      if (typeFilter && typeFilter !== type) continue;
      
      html += `<div><strong>${type.charAt(0).toUpperCase() + type.slice(1)}:</strong>`;
      html += "<div style='margin: 5px 0; display: flex; flex-wrap: wrap; gap: 8px;'>";
      items.forEach((item) => {
        buttonCount++;
        const btnClass = document.getElementById("target").value === item.name ? "workload-btn-selected" : "workload-btn";
        // Create buttons with onclick that calls global function
        // Escape single quotes in item.name to prevent script injection
        const escapedName = item.name.replace(/'/g, "\\'");
        const escapedType = type.replace(/'/g, "\\'");
        html += `<button type="button" class="${btnClass}" id="workload-btn-${buttonCount}" 
                 data-workload-name="${item.name}" 
                 data-workload-type="${type}"
                 onclick="selectWorkloadGlobal('${escapedName}', '${escapedType}')">
                 ${item.name}<br><small style="font-size: 0.8em;">${item.status}</small></button>`;
      });
      html += "</div></div>";
    }
    
    html += "</div>";
    workloadsList.innerHTML = html;
    
    console.log(`[WORKLOADS_LOADED] ✓ Rendered ${buttonCount} workload buttons with onclick handlers`);
    console.log(`[WORKLOADS_LOADED] Global function selectWorkloadGlobal is available: ${typeof window.selectWorkloadGlobal === 'function'}`);
    
  } catch (err) {
    console.error("Failed to load workloads:", err);
    document.getElementById("workloads-list").innerHTML = `<p style='color: var(--error);'>Error loading workloads: ${err.message}</p>`;
  }
}

let selectedWorkloadInfo = {
  name: null,
  type: null,
};

// Direct handler for button clicks - GLOBAL function guaranteed to work
window.selectWorkloadGlobal = function(workloadName, workloadType) {
  console.log(`[SELECTWORKLOAD_GLOBAL] ✓ Button clicked for: "${workloadName}" (type: ${workloadType})`);
  
  // Update the target field (the pod/deployment name)
  // This is what gets sent to the backend as "target"
  document.getElementById("target").value = workloadName;
  console.log(`[SELECTWORKLOAD_GLOBAL] Set #target field to: "${workloadName}"`);
  
  // IMPORTANT: The workload_type dropdown value is preserved!
  // The form submission will read the dropdown value directly
  const currentDropdownValue = document.getElementById("workload_type").value;
  console.log(`[SELECTWORKLOAD_GLOBAL] Current #workload_type dropdown value: "${currentDropdownValue}"`);
  
  // Update button styling
  document.querySelectorAll("[id^='workload-btn-']").forEach(btn => {
    btn.classList.remove("workload-btn-selected");
    btn.classList.add("workload-btn");
  });
  
  const selectedBtn = document.querySelector(`[data-workload-name="${workloadName}"]`);
  if (selectedBtn) {
    selectedBtn.classList.remove("workload-btn");
    selectedBtn.classList.add("workload-btn-selected");
  }
};

function selectWorkload(btn, workloadName, workloadType) {
  console.log(`[SELECTWORKLOAD] ✓ Function called for: ${workloadName} (type: ${workloadType})`);
  
  // Update the form fields
  const targetField = document.getElementById("target");
  targetField.value = workloadName;
  console.log(`[SELECTWORKLOAD] Set target field to: ${workloadName}`);
  
  // Store workload type in localStorage
  localStorage.setItem("selectedWorkloadType", workloadType);
  console.log(`[SELECTWORKLOAD] Stored in localStorage: "${workloadType}"`);
  console.log(`[SELECTWORKLOAD] Verify read from localStorage: "${localStorage.getItem("selectedWorkloadType")}"`);
  
  // Update button styling - select buttons with class "workload-btn" OR "workload-btn-selected"
  document.querySelectorAll("[id^='workload-btn-']").forEach(b => {
    b.classList.remove("workload-btn-selected");
    b.classList.add("workload-btn");
  });
  btn.classList.remove("workload-btn");
  btn.classList.add("workload-btn-selected");
  console.log(`[SELECTWORKLOAD] Updated button styling`);
}

// Wait for DOM to be ready before adding event listeners
window.addEventListener("DOMContentLoaded", () => {
  const namespaceSelect = document.getElementById("namespace");
  if (namespaceSelect) {
    namespaceSelect.addEventListener("change", async (e) => {
      if (e.target.value) {
        // Clear workload selection when namespace changes
        document.getElementById("target").value = "";
        document.getElementById("investigation-form").dataset.selectedWorkloadType = "";
        localStorage.removeItem("selectedWorkloadType");
        console.log("[UI] Cleared workload selection due to namespace change");
        await loadWorkloads(e.target.value);
      }
    });
  }
  
  const workloadTypeSelect = document.getElementById("workload_type");
  if (workloadTypeSelect) {
    workloadTypeSelect.addEventListener("change", async (e) => {
      const namespace = document.getElementById("namespace").value;
      const selectedValue = e.target.value;
      
      // IMPORTANT: Update the hidden form field with the selected workload_type
      const formField = document.getElementById("form_workload_type");
      if (formField) {
        formField.value = selectedValue;
        console.log(`[UI] Updated form hidden field form_workload_type to: "${selectedValue}"`);
      }
      
      if (namespace) {
        // Clear the target (selected workload) but keep dropdown value
        document.getElementById("target").value = "";
        console.log(`[UI] Cleared target workload, keeping workload_type: "${selectedValue}"`);
        await loadWorkloads(namespace);
      }
    });
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  if (socket) {
    socket.close();
    socket = null;
  }

  progressEl.innerHTML = "";
  rootCauseEl.textContent = "Root Cause: —";
  confidenceEl.textContent = "Confidence: —";
  fixesEl.innerHTML = "";
  preventionEl.innerHTML = "";

  // Get workload_type from the HIDDEN FORM FIELD (which was synced from dropdown)
  const formWorkloadTypeField = document.getElementById("form_workload_type");
  const workloadTypeValue = formWorkloadTypeField ? formWorkloadTypeField.value : "";
  
  console.log(`[FORM_SUBMIT] form_workload_type hidden field value: "${workloadTypeValue}"`);
  console.log(`[FORM_SUBMIT] Also checking dropdown value: "${document.getElementById("workload_type").value}"`);
  
  // Use the hidden field value, fallback to dropdown, then null
  const workloadTypeToSend = (workloadTypeValue && workloadTypeValue !== "") ? workloadTypeValue : null;
  console.log(`[FORM_SUBMIT] workload_type to send: "${workloadTypeToSend}"`);
  
  const payload = {
    incident_name: document.getElementById("incident_name").value,
    namespace: document.getElementById("namespace").value,
    target: document.getElementById("target").value || null,
    workload_type: workloadTypeToSend,
  };
  
  console.log(`[FORM_SUBMIT] ✓ Final payload:`);
  console.log(JSON.stringify(payload, null, 2));

  progressSection.style.display = "block";
  diagnosisSection.style.display = "block";
  statusEl.textContent = "Status: submitting...";

  const res = await fetch("/api/investigations", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    try {
      const errorData = await res.json();
      const errorMsg = errorData.detail || errorData.message || "Unknown error";
      statusEl.textContent = `Status: failed to start (${res.status}) - ${errorMsg}`;
      console.error(`[ERROR] API returned ${res.status}:`, errorData);
    } catch (e) {
      statusEl.textContent = `Status: failed to start (${res.status})`;
      console.error(`[ERROR] API returned ${res.status}:`, res.statusText);
    }
    return;
  }

  const created = await res.json();
  statusEl.textContent = `Status: ${created.status}`;
  progressEl.innerHTML = "";
  const li = document.createElement("li");
  li.textContent = "✓ Investigation queued";
  progressEl.appendChild(li);

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/api/investigations/${created.id}/stream`);

  socket.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    statusEl.textContent = `Status: ${event.status}`;

    if (event.progress) {
      const li = document.createElement("li");
      li.textContent = `✓ ${event.progress.detail}`;
      progressEl.appendChild(li);
    }

    if (event.report) {
      rootCauseEl.textContent = `Root Cause: ${event.report.root_cause}`;
      confidenceEl.textContent = `Confidence: ${event.report.confidence}%`;
      setList(fixesEl, event.report.recommended_fixes);
      setList(preventionEl, event.report.prevention);
      statusEl.classList.add("status-completed");
      loadHistory();
    }

    if (event.error) {
      const li = document.createElement("li");
      li.textContent = `✗ ${event.error}`;
      progressEl.appendChild(li);
    }
  };

  socket.onerror = () => {
    const li = document.createElement("li");
    li.textContent = "✗ WebSocket error during realtime updates";
    progressEl.appendChild(li);
  };
});
