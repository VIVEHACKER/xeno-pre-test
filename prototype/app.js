// 동적 처방 대시보드. 백엔드: cpa_first.api.main (같은 호스트로 fetch).

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const API_BASE = ""; // 같은 호스트(FastAPI가 정적도 서빙)

const inputs = {
  months: $("#monthsInput"),
  accounting: $("#accountingInput"),
  tax: $("#taxInput"),
  hours: $("#hoursInput"),
  stage: $("#stageInput"),
  acctTime: $("#acctTimeInput"),
  taxTime: $("#taxTimeInput"),
};

const slidersWithOutput = {
  accounting: { input: $("#accountingInput"), output: $("#accountingOutput") },
  tax: { input: $("#taxInput"), output: $("#taxOutput") },
  acctTime: { input: $("#acctTimeInput"), output: $("#acctTimeOutput") },
  taxTime: { input: $("#taxTimeInput"), output: $("#taxTimeOutput") },
};

function updateSliderOutputs() {
  for (const { input, output } of Object.values(slidersWithOutput)) {
    if (input && output) output.textContent = `${input.value}%`;
  }
}

function collectRiskTags() {
  return $$('.risk-tags input[type="checkbox"]:checked').map((cb) => cb.dataset.tag);
}

function buildPayload() {
  const months = Number(inputs.months.value);
  const days = Math.max(1, Math.round(months * 30));
  const tags = collectRiskTags();
  return {
    user_id: "ui-user",
    target_exam: "CPA_1",
    days_until_exam: days,
    available_hours_per_day: Number(inputs.hours.value),
    current_stage: inputs.stage.value,
    subject_states: [
      {
        subject: "accounting",
        accuracy: Number(inputs.accounting.value) / 100,
        time_overrun_rate: Number(inputs.acctTime.value) / 100,
        risk_tags: tags,
      },
      {
        subject: "tax",
        accuracy: Number(inputs.tax.value) / 100,
        time_overrun_rate: Number(inputs.taxTime.value) / 100,
        risk_tags: tags,
      },
    ],
  };
}

async function postDiagnose(payload) {
  const res = await fetch(`${API_BASE}/diagnose`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`diagnose ${res.status}: ${await res.text()}`);
  return res.json();
}

const RISK_LABEL_KO = { high: "높음", moderate: "중간", low: "관리 가능" };

function renderMetrics(rx) {
  const d = rx.diagnosis;
  $("#riskLabel").textContent = RISK_LABEL_KO[d.risk_level] ?? d.risk_level;
  $("#riskReason").textContent = d.summary;

  $("#weeklyGoal").textContent = rx.weekly_goal.goal_text;
  $("#weeklyMetric").textContent = rx.weekly_goal.verification_metric;

  $("#matchCount").textContent = String(rx.triggered_rule_keys.length);
  $("#matchRules").textContent = rx.triggered_rule_keys.length
    ? rx.triggered_rule_keys.join(", ")
    : "매칭된 의사결정 규칙이 없습니다.";
}

function renderPriority(rx) {
  const concepts = rx.concepts_to_review;
  if (!concepts.length) {
    $("#priorityList").innerHTML = `<p class="muted-note">우선순위 개념이 없습니다.</p>`;
    return;
  }
  // 단순 시각화: 첫 항목 100, 마지막 50 사이를 보간
  $("#priorityList").innerHTML = concepts
    .map((concept, i) => {
      const width = Math.max(50, Math.round(100 - i * (50 / Math.max(1, concepts.length - 1))));
      return `
        <div class="priority-row">
          <strong>${escapeHtml(concept)}</strong>
          <div class="bar-track" aria-hidden="true">
            <div class="bar-fill" style="width:${width}%"></div>
          </div>
          <span>${width}</span>
        </div>
      `;
    })
    .join("");
}

const SUBJECT_LABEL = { accounting: "회계", tax: "세법", mixed: "혼합" };

function renderTasks(rx) {
  $("#planSummary").textContent = `${rx.daily_tasks.length}개 처방`;
  $("#taskList").innerHTML = rx.daily_tasks
    .map((task) => {
      const subj = SUBJECT_LABEL[task.subject] ?? task.subject;
      const min = task.estimated_minutes ? ` · ${task.estimated_minutes}분` : "";
      return `<li><strong>[${subj}${min}]</strong> ${escapeHtml(task.task_text)}</li>`;
    })
    .join("");
}

const REF_TYPE_LABEL = {
  decision_rule: "의사결정 규칙",
  problem_intelligence: "문제 지능",
  user_state: "사용자 상태",
  success_case: "합격수기",
  extracted_signal: "추출 신호",
};

function renderEvidence(rx) {
  const list = $("#evidenceList");
  $("#evidenceSummary").textContent = `${rx.evidence_refs.length}개 근거. 클릭해서 원본 조회.`;
  list.innerHTML = rx.evidence_refs
    .map(
      (ref, i) => `
        <li>
          <button class="evidence-card" data-ref-type="${ref.ref_type}" data-ref-id="${escapeAttr(ref.ref_id)}" data-idx="${i}">
            <span class="evidence-type">${REF_TYPE_LABEL[ref.ref_type] ?? ref.ref_type}</span>
            <strong>${escapeHtml(ref.ref_id)}</strong>
            <small>${escapeHtml(ref.note ?? "")}</small>
          </button>
        </li>
      `,
    )
    .join("");
  $("#evidenceDetail").hidden = true;
}

async function loadEvidenceDetail(refType, refId) {
  const detail = $("#evidenceDetail");
  detail.hidden = false;
  detail.textContent = `${refType}/${refId} 로딩 중…`;
  try {
    const res = await fetch(`${API_BASE}/evidence/${refType}/${encodeURIComponent(refId)}`);
    if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
    const data = await res.json();
    detail.textContent = JSON.stringify(data.data, null, 2);
  } catch (err) {
    detail.textContent = `오류: ${err.message}`;
  }
}

function render(rx) {
  renderMetrics(rx);
  renderPriority(rx);
  renderTasks(rx);
  renderEvidence(rx);
}

let inflight = null;
let debounceTimer = null;

async function triggerDiagnose() {
  const payload = buildPayload();
  if (inflight) inflight.aborted = true;
  const ticket = { aborted: false };
  inflight = ticket;
  try {
    const body = await postDiagnose(payload);
    if (ticket.aborted) return;
    render(body.prescription);
    $("#apiStatus").textContent = "처방 엔진 연결됨";
  } catch (err) {
    $("#apiStatus").textContent = `오류: ${err.message}`;
  }
}

function scheduleDiagnose() {
  updateSliderOutputs();
  if (debounceTimer) clearTimeout(debounceTimer);
  debounceTimer = setTimeout(triggerDiagnose, 300);
}

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[c]);
}

function escapeAttr(s) {
  return escapeHtml(s);
}

// ----- 이벤트 -----

$$(".nav-item").forEach((button) => {
  button.addEventListener("click", () => {
    $$(".nav-item").forEach((item) => item.classList.remove("active"));
    $$(".view").forEach((view) => view.classList.remove("active"));
    button.classList.add("active");
    $(`#${button.dataset.view}`).classList.add("active");
  });
});

$$(".question-bank button").forEach((button) => {
  button.addEventListener("click", () => {
    $("#selectedQuestion").textContent = button.dataset.question;
  });
});

// 모든 진단 입력에 디바운스 fetch 연결
Object.values(inputs).forEach((input) => {
  if (input) input.addEventListener("input", scheduleDiagnose);
});
$$('.risk-tags input[type="checkbox"]').forEach((cb) =>
  cb.addEventListener("change", scheduleDiagnose),
);

// evidence 카드 클릭 위임
$("#evidenceList").addEventListener("click", (event) => {
  const btn = event.target.closest(".evidence-card");
  if (!btn) return;
  loadEvidenceDetail(btn.dataset.refType, btn.dataset.refId);
});

// ----- 06번 데이터 적재 manifest (기존 보존) -----

function renderDataManifest(manifest) {
  const stats = manifest.stats || {};
  $("#sourceCount").textContent = stats.sources ?? 0;
  $("#documentCount").textContent = stats.documents ?? 0;
  $("#signalCount").textContent = stats.signals ?? 0;
  $("#ruleCount").textContent = stats.strategy_rules ?? 0;
  $("#subjectCount").textContent = stats.exam_subjects ?? 0;
  $("#knowledgeNodeCount").textContent = stats.knowledge_nodes ?? 0;
  $("#acquisitionTargetCount").textContent = stats.acquisition_targets ?? 0;
  $("#manifestGeneratedAt").textContent = manifest.generated_at
    ? `마지막 적재 ${new Date(manifest.generated_at).toLocaleString("ko-KR")}`
    : "DB manifest 없음";

  const rules = stats.rules || [];
  $("#ruleTableBody").innerHTML = rules.length
    ? rules
        .map(
          (rule) => `
            <tr>
              <td>${escapeHtml(rule.rule_name)}</td>
              <td>${rule.source_signal_count}</td>
              <td>${Math.round(rule.confidence * 100)}%</td>
              <td>${escapeHtml(rule.review_status)}</td>
            </tr>
          `,
        )
        .join("")
    : `<tr><td colspan="4">아직 승격된 전략 규칙이 없습니다.</td></tr>`;
}

async function loadDataManifest() {
  try {
    const response = await fetch("data_manifest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`manifest ${response.status}`);
    renderDataManifest(await response.json());
  } catch {
    renderDataManifest({ generated_at: null, stats: { rules: [] } });
  }
}

// ----- 정적 주간 운영판 (참고 템플릿). 처방과는 별도. -----

const weeks = [
  ["월", "회계 금융자산 18문항", "세법 말문제 30개"],
  ["화", "수익인식 개념 재정렬", "오답 조건 누락 분류"],
  ["수", "세법 법인세 계산 20문항", "휘발 암기 회상"],
  ["목", "회계 2회전 풀이 드릴", "시간 초과 문제 표시"],
  ["금", "혼합 세트 40문항", "주간 재진단"],
];

function renderWeek() {
  $("#weekGrid").innerHTML = weeks
    .map(
      ([day, main, sub]) => `
        <div class="day-cell">
          <strong>${day}</strong>
          <span>${main}</span>
          <span>${sub}</span>
        </div>
      `,
    )
    .join("");
}

// ----- 부트 -----

async function healthCheck() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    $("#apiStatus").textContent = `처방 엔진 준비됨 (규칙 ${data.decision_rules}, 문제 ${data.problems})`;
    return true;
  } catch (err) {
    $("#apiStatus").textContent = `처방 엔진 연결 실패 — ${err.message}. \`cpa-serve\` 실행 필요`;
    return false;
  }
}

updateSliderOutputs();
renderWeek();
loadDataManifest();
healthCheck().then((ok) => {
  if (ok) triggerDiagnose();
});
