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

// SUBJECT_LABEL: 백엔드 cpa_first/subjects.py의 SUBJECTS와 동기화. 새 과목 추가 시 양쪽 갱신.
const SUBJECT_LABEL = {
  accounting: "회계",
  tax: "세법",
  business: "경영학",
  economics: "경제원론",
  corporate_law: "기업법",
  management: "경영",
  finance: "재무관리",
  cost_accounting: "원가관리",
  mixed: "혼합",
};

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
  success_case: "전략 사례",
  extracted_signal: "추출 신호",
};

const STAGE_LABEL = {
  post_lecture: "기본강의 이후",
  objective_entry: "객관식 진입",
  past_exam_rotation: "기출 회독",
  mock_exam: "모의고사",
  final: "파이널",
};

function classifyLearner(payload) {
  const [accounting, tax] = payload.subject_states;
  const avgAccuracy = (accounting.accuracy + tax.accuracy) / 2;
  const maxOverrun = Math.max(accounting.time_overrun_rate, tax.time_overrun_rate);
  const weakSubject = accounting.accuracy <= tax.accuracy ? "회계" : "세법";
  const stage = payload.current_stage;
  const days = payload.days_until_exam;

  if (avgAccuracy < 0.5) {
    return {
      level: "기초 재구축",
      mode: "개념-예제 회복",
      focus: `${weakSubject} 핵심 개념`,
      defer: "고난도 모의고사",
      reason: "평균 정답률이 50% 아래라 기출 회독보다 개념-풀이 연결을 먼저 복구해야 합니다.",
    };
  }
  if (maxOverrun >= 0.4) {
    return {
      level: "풀이 순서 교정",
      mode: "시간 방어",
      focus: `${weakSubject} 시간초과 유형`,
      defer: "풀이 오래 붙잡기",
      reason: "정답률보다 시간초과율이 더 큰 병목입니다. 넘김 기준과 풀이 순서를 먼저 고정합니다.",
    };
  }
  if (stage === "objective_entry") {
    return {
      level: "객관식 전환",
      mode: "보기 판별 훈련",
      focus: `${weakSubject} 낮은 난도 기출`,
      defer: "기본서 정독 회귀",
      reason: "기본 개념을 문제 선택지로 바꾸는 단계입니다. 설명보다 판별 기준을 훈련합니다.",
    };
  }
  if (days <= 45 || stage === "final") {
    return {
      level: "실전 방어",
      mode: "점수 보존",
      focus: "실수 반복 유형",
      defer: "새로운 범위 확장",
      reason: "남은 기간이 짧아 새 범위보다 반복 실수와 시간 손실을 줄이는 편이 유리합니다.",
    };
  }
  return {
    level: "회독 안정화",
    mode: "기출 회전",
    focus: `${weakSubject} 약점 단원`,
    defer: "무근거 양치기",
    reason: "현재는 많은 문제보다 왜 틀렸는지 남는 회독 구조를 만드는 단계입니다.",
  };
}

const UNIT_LABEL = {
  financial_assets: "금융자산",
  inventory: "재고자산",
  cost_management: "CVP/원가관리",
  tangible_assets: "유형자산",
  revenue_recognition: "수익인식",
  liabilities: "충당부채",
  cash_flow: "현금흐름표",
  equity: "자본",
  vat: "부가가치세",
  income_tax: "소득세",
  corporate_tax: "법인세",
  national_tax_basic_act: "국세기본법",
};

function unitLabel(unit) {
  return UNIT_LABEL[unit] ?? String(unit ?? "").replaceAll("_", " ");
}

function weaknessScore(state) {
  return state.accuracy - state.time_overrun_rate * 0.35;
}

function weakestSubjectState(payload) {
  return payload.subject_states.reduce((weakest, state) =>
    weaknessScore(state) < weaknessScore(weakest) ? state : weakest,
  );
}

function normalizeSearchText(value) {
  return String(value ?? "")
    .toLowerCase()
    .replace(/[^0-9a-z가-힣]/g, "");
}

function conceptMatchScore(problem, concepts) {
  const source = normalizeSearchText(
    [
      problem.unit,
      problem.question_analysis?.asked_output,
      problem.question_analysis?.examiner_intent,
      ...(problem.concept_tags || []),
    ].join(" "),
  );
  return concepts.reduce((score, concept) => {
    const normalized = normalizeSearchText(concept);
    if (!normalized) return score;
    if (source.includes(normalized)) return score + 16;
    const tokens = String(concept)
      .split(/[:\s,/_-]+/)
      .map(normalizeSearchText)
      .filter((token) => token.length >= 3);
    return score + tokens.filter((token) => source.includes(token)).length * 5;
  }, 0);
}

function scoreProblemForToday(problem, weakSubject, concepts, payload) {
  const weakState = payload.subject_states.find((state) => state.subject === weakSubject);
  const overrun = weakState?.time_overrun_rate ?? 0;
  let score = 0;
  if (problem.subject === weakSubject) score += 40;
  if (problem.review_status === "expert_reviewed") score += 8;
  if (problem.rights_status === "synthetic_seed") score += 4;
  score += conceptMatchScore(problem, concepts);
  if (overrun >= 0.35 && problem.question_analysis?.question_type === "calculation") score += 7;
  if (payload.current_stage === "objective_entry" && problem.solution_paths?.length >= 3) score += 6;
  return score;
}

function selectTodayProblems(payload, concepts) {
  const weakSubject = weakestSubjectState(payload).subject;
  return [...problemSolutionMaps]
    .sort((a, b) => scoreProblemForToday(b, weakSubject, concepts, payload) - scoreProblemForToday(a, weakSubject, concepts, payload))
    .slice(0, 3);
}

function uniqueItems(items) {
  return Array.from(new Set(items.filter(Boolean)));
}

function buildDailyPrescription(payload, rx = null) {
  const profile = classifyLearner(payload);
  const weakState = weakestSubjectState(payload);
  const weakLabel = SUBJECT_LABEL[weakState.subject] ?? weakState.subject;
  const concepts = uniqueItems([...(rx?.concepts_to_review || []), profile.focus]).slice(0, 4);
  const problems = selectTodayProblems(payload, concepts);
  const hours = payload.available_hours_per_day;
  const problemMinutes = Math.max(45, Math.min(120, Math.round(hours * 60 * 0.32)));
  const reviewMinutes = Math.max(15, Math.min(60, Math.round(hours * 60 * 0.14)));
  const topUnit = problems[0] ? `${SUBJECT_LABEL[displaySubjectKey(problems[0])] ?? problems[0].subject} ${unitLabel(problems[0].unit)}` : profile.focus;
  const otherUnits = problemSolutionMaps
    .filter((problem) => problem.subject !== weakState.subject)
    .slice(0, 2)
    .map((problem) => `${SUBJECT_LABEL[displaySubjectKey(problem)] ?? problem.subject} ${unitLabel(problem.unit)}`);
  const deferItems = uniqueItems([
    profile.defer,
    weakState.time_overrun_rate >= 0.35 ? "시간을 넘긴 문제를 끝까지 붙잡기" : "채점 없는 문제 양치기",
    ...otherUnits,
    payload.days_until_exam <= 45 ? "새로운 범위 확장" : "고난도 실전 모의고사",
  ]).slice(0, 4);
  const firstProblem = problems[0];
  const firstIntent = firstProblem?.question_analysis?.examiner_intent || "조건 신호를 보고 먼저 적용할 개념 체계를 고르는지 확인합니다.";

  return {
    title: `${weakLabel}부터 ${profile.mode} 모드로 시작`,
    reason: `${profile.reason} 오늘은 ${topUnit}을 먼저 풀고, 출제 의도와 오답 유인을 해설보다 먼저 확인합니다.`,
    budget: `${hours}시간 중 문제 ${problemMinutes}분 · 복습 ${reviewMinutes}분 우선 배정`,
    riskMode: `${profile.level} · ${profile.mode}`,
    weakSubject: `${weakLabel} 정답률 ${Math.round(weakState.accuracy * 100)}% · 시간초과 ${Math.round(weakState.time_overrun_rate * 100)}%`,
    verification: rx?.weekly_goal?.verification_metric || "오늘 문제별 선택지 제거 근거와 오답 원인 태그를 남깁니다.",
    problems,
    concepts,
    deferItems,
    rotationMode: `${STAGE_LABEL[payload.current_stage] ?? payload.current_stage} 기준`,
    rotation: [
      `${concepts[0] || profile.focus}을 5분 안에 말로 설명하고 바로 문제로 확인합니다.`,
      `${problemMinutes}분 동안 오늘 문제 ${Math.max(1, problems.length || 3)}개를 제한 시간으로 풉니다.`,
      firstIntent,
      "채점 후 정답 해설보다 질문 요구, 본문 신호, 오답 유인을 먼저 표시합니다.",
      "틀린 문제는 개념 공백, 계산 순서, 시간 압박 중 하나로 태그를 남기고 다음 처방에 반영합니다.",
    ],
  };
}

function renderDailyPrescription(payload, rx = null) {
  const prescription = buildDailyPrescription(payload, rx);
  latestTodayProblemIds = prescription.problems.map((problem) => problem.question_id);
  $("#dailyCommandTitle").textContent = prescription.title;
  $("#dailyCommandReason").textContent = prescription.reason;
  $("#dailyStudyBudget").textContent = prescription.budget;
  $("#dailyRiskMode").textContent = prescription.riskMode;
  $("#dailyWeakSubject").textContent = prescription.weakSubject;
  $("#dailyVerification").textContent = prescription.verification;
  $("#todayProblemSummary").textContent = prescription.problems.length ? `${prescription.problems.length}개 문제` : "풀이맵 로딩 중";
  $("#todayRotationMode").textContent = prescription.rotationMode;

  $("#todayProblemList").innerHTML = prescription.problems.length
    ? prescription.problems
        .map((problem, index) => {
          const analysis = problem.question_analysis || {};
          return `
            <button class="today-problem-card" type="button" data-problem-id="${escapeAttr(problem.question_id)}">
              <span>${index + 1} · ${escapeHtml(SUBJECT_LABEL[displaySubjectKey(problem)] ?? problem.subject)}</span>
              <strong>${escapeHtml(unitLabel(problem.unit))}</strong>
              <small>${escapeHtml(analysis.asked_output || problem.question_id)}</small>
              <p>${escapeHtml(analysis.examiner_intent || problem.explanation || "개념 선택과 보기 판별을 확인합니다.")}</p>
            </button>
          `;
        })
        .join("")
    : `<div class="daily-empty">풀이맵이 로딩되면 오늘 풀 문제를 자동으로 채웁니다.</div>`;

  $("#todayConceptList").innerHTML = prescription.concepts
    .map(
      (concept, index) => `
        <article>
          <span>${index + 1}</span>
          <strong>${escapeHtml(concept)}</strong>
          <p>풀이 전에 정의, 적용 조건, 대표 함정 1개를 말로 확인합니다.</p>
        </article>
      `,
    )
    .join("");

  $("#todayDeferList").innerHTML = prescription.deferItems
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");

  $("#todayRotationList").innerHTML = prescription.rotation
    .map((item) => `<li>${escapeHtml(item)}</li>`)
    .join("");
}

function renderCoachFromState(payload, rx = null) {
  const profile = classifyLearner(payload);
  const tasks = rx?.daily_tasks || [];
  const concepts = rx?.concepts_to_review || [];
  const firstTask = tasks[0]?.task_text || `${profile.focus}을 45분 단위로 풀고 오답 원인을 기록합니다.`;
  const verification = rx?.weekly_goal?.verification_metric || "오늘 풀이 로그 20개와 오답 원인 태그를 남깁니다.";

  $("#coachLevel").textContent = profile.level;
  $("#coachLevelReason").textContent = profile.reason;
  $("#coachMode").textContent = profile.mode;
  $("#coachModeReason").textContent = `${STAGE_LABEL[payload.current_stage] ?? payload.current_stage} 단계에 맞춰 자동 전환됩니다.`;
  $("#coachPrimaryAction").textContent = firstTask;
  $("#coachPrimaryReason").textContent = rx?.diagnosis?.summary || "현재 입력값 기준의 임시 처방입니다.";
  $("#coachFocus").textContent = concepts[0] || profile.focus;
  $("#coachDefer").textContent = profile.defer;
  $("#coachNextProblem").textContent = profile.level === "객관식 전환" ? "문제 훈련 탭의 낮은 난도 풀이맵" : "오답 원인이 남는 단원 문제";
  $("#coachVerification").textContent = verification;

  const guidelines = [
    firstTask,
    profile.defer ? `오늘 제외: ${profile.defer}.` : "",
    concepts[0] ? `${concepts[0]}은 풀이 전에 5분 요약 후 바로 문제로 확인합니다.` : `${profile.focus}은 개념 설명보다 예제 풀이로 확인합니다.`,
    "채점 후 정답보다 선택지 제거 근거를 먼저 확인합니다.",
  ].filter(Boolean);
  $("#coachGuidelines").innerHTML = guidelines.map((item) => `<li>${escapeHtml(item)}</li>`).join("");

  const accounting = payload.subject_states.find((s) => s.subject === "accounting");
  const tax = payload.subject_states.find((s) => s.subject === "tax");
  $("#levelDiagnosisTitle").textContent = profile.level;
  $("#levelDiagnosisBody").textContent = profile.reason;
  $("#levelAccountingSignal").textContent = `정답률 ${Math.round(accounting.accuracy * 100)}% · 시간초과 ${Math.round(accounting.time_overrun_rate * 100)}%`;
  $("#levelTaxSignal").textContent = `정답률 ${Math.round(tax.accuracy * 100)}% · 시간초과 ${Math.round(tax.time_overrun_rate * 100)}%`;
  $("#levelTimeSignal").textContent = Math.max(accounting.time_overrun_rate, tax.time_overrun_rate) >= 0.4 ? "시간 병목 우선" : "시간 관리 가능";
  $("#levelTransitionSignal").textContent = profile.mode;
}

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
  renderDailyPrescription(buildPayload(), rx);
  renderMetrics(rx);
  renderPriority(rx);
  renderTasks(rx);
  renderEvidence(rx);
  renderCoachFromState(buildPayload(), rx);
}

let inflight = null;
let diagnoseTimer = null;
let latestPrescription = null;
let latestTodayProblemIds = [];

async function triggerDiagnose() {
  const payload = buildPayload();
  renderCoachFromState(payload, latestPrescription);
  renderDailyPrescription(payload, latestPrescription);
  if (inflight) inflight.aborted = true;
  const ticket = { aborted: false };
  inflight = ticket;
  try {
    const body = await postDiagnose(payload);
    if (ticket.aborted) return;
    latestPrescription = body.prescription;
    render(body.prescription);
    $("#apiStatus").textContent = "처방 엔진 연결됨";
  } catch (err) {
    $("#apiStatus").textContent = `오류: ${err.message}`;
  }
}

function scheduleDiagnose() {
  updateSliderOutputs();
  const payload = buildPayload();
  renderCoachFromState(payload, latestPrescription);
  renderDailyPrescription(payload, latestPrescription);
  if (diagnoseTimer) clearTimeout(diagnoseTimer);
  diagnoseTimer = setTimeout(triggerDiagnose, 300);
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

function activateView(viewId) {
  const view = $(`#${viewId}`);
  if (!view) return;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewId));
  $$(".view").forEach((item) => item.classList.toggle("active", item.id === viewId));
}

$$(".nav-item").forEach((button) => {
  button.addEventListener("click", () => activateView(button.dataset.view));
});

$$("[data-jump-view]").forEach((button) => {
  button.addEventListener("click", () => {
    if (button.dataset.jumpView === "problem" && latestTodayProblemIds[0]) {
      openProblemMap(latestTodayProblemIds[0]);
    }
    activateView(button.dataset.jumpView);
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

// ----- 과목별 튜토리얼 -----

let subjectTutorials = [];
let selectedTutorialId = null;
let selectedStepIndex = 0;

function phaseOptionValue(tutorial) {
  return `${tutorial.exam_id}:${tutorial.phase_id}`;
}

function phaseOptionLabel(tutorial) {
  return `${tutorial.exam_id} · ${tutorial.phase_name}`;
}

function filteredTutorials() {
  const phase = $("#tutorialPhaseFilter").value;
  return subjectTutorials.filter((tutorial) => phase === "all" || phaseOptionValue(tutorial) === phase);
}

function renderTutorialFilters() {
  const phases = new Map();
  subjectTutorials.forEach((tutorial) => phases.set(phaseOptionValue(tutorial), phaseOptionLabel(tutorial)));
  $("#tutorialPhaseFilter").innerHTML = [
    `<option value="all">전체</option>`,
    ...Array.from(phases, ([value, label]) => `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`),
  ].join("");
  renderTutorialSubjectOptions();
}

function renderTutorialSubjectOptions() {
  const tutorials = filteredTutorials();
  if (!tutorials.length) {
    $("#tutorialSubjectSelect").innerHTML = `<option value="">과목 없음</option>`;
    return;
  }
  if (!tutorials.some((tutorial) => tutorial.tutorial_id === selectedTutorialId)) {
    selectedTutorialId = tutorials[0].tutorial_id;
    selectedStepIndex = 0;
  }
  $("#tutorialSubjectSelect").innerHTML = tutorials
    .map(
      (tutorial) =>
        `<option value="${escapeAttr(tutorial.tutorial_id)}" ${tutorial.tutorial_id === selectedTutorialId ? "selected" : ""}>${escapeHtml(tutorial.subject_name)} · ${escapeHtml(tutorial.entry_topic)}</option>`,
    )
    .join("");
  renderSelectedTutorial();
}

function renderSelectedTutorial() {
  const tutorial = subjectTutorials.find((item) => item.tutorial_id === selectedTutorialId);
  if (!tutorial) {
    $("#tutorialTitle").textContent = "튜토리얼 데이터 없음";
    $("#tutorialObjective").textContent = "subject_tutorials.json을 먼저 생성해야 합니다.";
    $("#tutorialAtoms").innerHTML = "";
    $("#tutorialFlow").innerHTML = "";
    $("#tutorialStepDetail").innerHTML = "";
    return;
  }
  selectedStepIndex = Math.min(selectedStepIndex, tutorial.steps.length - 1);
  $("#tutorialSummary").textContent = `${subjectTutorials.length}개 과목 · ${subjectTutorials.reduce((sum, item) => sum + item.steps.length, 0)}개 단계`;
  $("#tutorialMeta").textContent = `${tutorial.exam_id} · ${tutorial.phase_name} · ${tutorial.assessment_type === "written" ? "주관식" : "객관식"}`;
  $("#tutorialTitle").textContent = tutorial.title;
  $("#tutorialObjective").textContent = tutorial.objective;
  $("#tutorialTopic").textContent = tutorial.entry_topic;
  $("#tutorialAtoms").innerHTML = tutorial.concept_atoms
    .map(
      (atom, index) => `
        <article>
          <span>atom ${index + 1}</span>
          ${escapeHtml(atom)}
        </article>
      `,
    )
    .join("");
  $("#tutorialFlow").innerHTML = tutorial.steps
    .map(
      (step, index) => `
        <button class="tutorial-step-button ${index === selectedStepIndex ? "active" : ""}" data-step-index="${index}">
          <span>${escapeHtml(step.label)}</span>
          <strong>${escapeHtml(step.title)}</strong>
        </button>
      `,
    )
    .join("");
  renderTutorialStep(tutorial, selectedStepIndex);
}

function renderTutorialStep(tutorial, index) {
  const step = tutorial.steps[index];
  const paths = step.solution_paths || [];
  $("#tutorialStepDetail").innerHTML = `
    <p class="eyebrow">${escapeHtml(step.label)} · 난이도 ${step.difficulty}</p>
    <h3>${escapeHtml(step.title)}</h3>
    <p>${escapeHtml(step.core_explanation)}</p>
    <div class="tutorial-step-body">
      <div class="tutorial-problem">
        <strong>문제</strong>
        <p>${escapeHtml(step.prompt)}</p>
        <strong>해야 할 일</strong>
        <p>${escapeHtml(step.learner_action)}</p>
      </div>
      <div class="tutorial-answer">
        <strong>기본 풀이</strong>
        <p>${escapeHtml(step.model_answer)}</p>
        <div class="checkpoint-list">
          ${step.checkpoints.map((item) => `<span>${escapeHtml(item)}</span>`).join("")}
        </div>
      </div>
    </div>
    <div class="solution-paths">
      ${paths
        .map(
          (path) => `
            <article class="solution-path">
              <strong>${escapeHtml(path.label)}</strong>
              <p>${escapeHtml(path.method)}</p>
              <small>${escapeHtml(path.when_to_use)}</small>
              <div class="path-rationale">
                <span>왜 이 풀이인가</span>
                <p>${escapeHtml(path.selection_rationale?.why_this_path ?? "")}</p>
              </div>
              <div class="path-signal-grid">
                <div>
                  <span>사용 신호</span>
                  ${(path.selection_rationale?.use_when_signals ?? []).map((signal) => `<em>${escapeHtml(signal)}</em>`).join("")}
                </div>
                <div>
                  <span>배제 신호</span>
                  ${(path.selection_rationale?.do_not_use_when ?? []).map((signal) => `<em>${escapeHtml(signal)}</em>`).join("")}
                </div>
              </div>
              <div class="concept-link-block">
                <span>연결 개념</span>
                ${(path.concept_links ?? [])
                  .map(
                    (link) => `
                      <div class="concept-link">
                        <strong>${escapeHtml(link.concept_label)}</strong>
                        <small>${escapeHtml(link.concept_role)}</small>
                        <p>${escapeHtml(link.why_required)}</p>
                      </div>
                    `,
                  )
                  .join("")}
              </div>
            </article>
          `,
        )
        .join("")}
    </div>
  `;
}

async function loadSubjectTutorials() {
  try {
    const response = await fetch("subject_tutorials.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`tutorials ${response.status}`);
    const data = await response.json();
    subjectTutorials = data.tutorials || [];
    renderTutorialFilters();
  } catch (err) {
    $("#tutorialSummary").textContent = `튜토리얼 로딩 실패: ${err.message}`;
    renderSelectedTutorial();
  }
}

$("#tutorialPhaseFilter").addEventListener("change", () => {
  selectedTutorialId = null;
  selectedStepIndex = 0;
  renderTutorialSubjectOptions();
});

$("#tutorialSubjectSelect").addEventListener("change", (event) => {
  selectedTutorialId = event.target.value;
  selectedStepIndex = 0;
  renderSelectedTutorial();
});

$("#tutorialFlow").addEventListener("click", (event) => {
  const button = event.target.closest(".tutorial-step-button");
  if (!button) return;
  selectedStepIndex = Number(button.dataset.stepIndex);
  renderSelectedTutorial();
});

// ----- 문제별 풀이 맵 -----

let problemSolutionMaps = [];
let selectedProblemId = null;
let selectedAttemptChoice = null;
let attemptStartedAt = 0;
let attemptTimer = null;
let latestAttemptDiagnosis = null;

// 데이터상 subject="business"는 재무관리(financial_management)와 경영학(management_general)을
// 함께 담고 있어 UI에서는 단원 기반으로 두 chip으로 분리한다. 키는 SUBJECT_LABEL과 매칭.
function displaySubjectKey(item) {
  if (!item) return "mixed";
  if (item.subject === "business") {
    return item.unit === "financial_management" ? "finance" : "business";
  }
  return item.subject;
}

function filteredProblemMaps() {
  const subject = $("#problemSubjectFilter").value;
  return problemSolutionMaps.filter((item) => subject === "all" || displaySubjectKey(item) === subject);
}

// 등록 순서대로 chip을 보장하기 위한 표시 순서. SUBJECT_LABEL의 key와 일치해야 한다.
const PROBLEM_FILTER_ORDER = [
  "accounting",
  "tax",
  "finance",
  "business",
  "economics",
  "corporate_law",
  "management",
  "cost_accounting",
];

function renderProblemFilters() {
  const present = new Set(problemSolutionMaps.map(displaySubjectKey));
  const ordered = PROBLEM_FILTER_ORDER.filter((key) => present.has(key));
  // 등록 순서 외에 등장한 미지의 키도 후미에 붙여 누락 방지.
  Array.from(present).forEach((key) => { if (!ordered.includes(key)) ordered.push(key); });
  $("#problemSubjectFilter").innerHTML = [
    `<option value="all">전체</option>`,
    ...ordered.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(SUBJECT_LABEL[value] ?? value)}</option>`),
  ].join("");
  renderProblemOptions();
}

function renderProblemOptions() {
  const items = filteredProblemMaps();
  if (!items.length) {
    $("#problemSolutionSelect").innerHTML = `<option value="">문제 없음</option>`;
    return;
  }
  if (!items.some((item) => item.question_id === selectedProblemId)) {
    selectedProblemId = items[0].question_id;
  }
  $("#problemSolutionSelect").innerHTML = items
    .map(
      (item) =>
        `<option value="${escapeAttr(item.question_id)}" ${item.question_id === selectedProblemId ? "selected" : ""}>${escapeHtml(item.question_id)} · ${escapeHtml(item.unit)}</option>`,
    )
    .join("");
  renderSelectedProblemMap();
}

function openProblemMap(problemId) {
  selectedProblemId = problemId;
  $("#problemSubjectFilter").value = "all";
  renderProblemOptions();
}

function problemPathByType(item, pathType) {
  return (item.solution_paths || []).find((path) => path.path_type === pathType);
}

function problemChoiceElimination(item, choiceIndex) {
  const path = problemPathByType(item, "choice_elimination");
  return (path?.choice_eliminations || []).find((choice) => choice.choice_index === choiceIndex) || null;
}

function diagnoseProblemAttemptLocal(item, selectedChoice, timeSeconds, timeLimitSeconds = 120) {
  const correct = selectedChoice === item.correct_choice;
  const slow = Number.isFinite(timeSeconds) && timeSeconds > timeLimitSeconds;
  const recommendedPath = !correct
    ? problemPathByType(item, "choice_elimination")
    : slow
      ? problemPathByType(item, "structure")
      : problemPathByType(item, "reverse_check");
  const missingLinks = correct && !slow ? [] : recommendedPath?.concept_links || [];
  const mistakeTags = [];
  if (!correct) mistakeTags.push("concept_gap", "distractor_trap");
  if (slow) mistakeTags.push("time_pressure");
  const action = !correct
    ? {
        action_type: "concept_rebuild",
        action_text: "선택한 보기와 정답 보기의 조건 차이를 표시하고 같은 개념의 기초-예제-유제 순서로 다시 풉니다.",
      }
    : slow
      ? {
          action_type: "speed_rebuild",
          action_text: "정답은 맞혔지만 제한 시간을 넘겼으므로 표/구조식으로 조건 분리 시간을 줄입니다.",
        }
      : {
          action_type: "advance_to_variant",
          action_text: "핵심 개념과 검산이 통과됐으므로 같은 단원의 낮은 난도 변형 문제로 이동합니다.",
        };

  return {
    question_id: item.question_id,
    correct,
    selected_choice: selectedChoice,
    selected_choice_text: item.choices[selectedChoice],
    correct_choice: item.correct_choice,
    correct_choice_text: item.choices[item.correct_choice],
    time_seconds: Number.isFinite(timeSeconds) ? timeSeconds : null,
    time_limit_seconds: timeLimitSeconds,
    time_over_limit: slow,
    mistake_tags: mistakeTags,
    selected_choice_elimination: problemChoiceElimination(item, selectedChoice),
    recommended_path: recommendedPath,
    missing_concept_links: missingLinks,
    next_tutorial: {
      tutorial_id: item.tutorial_id,
      focus_concepts: missingLinks.slice(0, 3).map((link) => link.concept_label),
    },
    next_action: action,
  };
}

function formatElapsed(totalSeconds) {
  const safeSeconds = Math.max(0, Math.floor(totalSeconds));
  const minutes = String(Math.floor(safeSeconds / 60)).padStart(2, "0");
  const seconds = String(safeSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function currentAttemptSeconds() {
  if (!attemptStartedAt) return 0;
  return Math.max(0, Math.round((Date.now() - attemptStartedAt) / 1000));
}

function updateAttemptClock() {
  $("#problemAttemptElapsed").textContent = formatElapsed(currentAttemptSeconds());
}

function startAttemptTimer() {
  if (attemptTimer) clearInterval(attemptTimer);
  attemptStartedAt = Date.now();
  updateAttemptClock();
  attemptTimer = setInterval(updateAttemptClock, 1000);
}

function stopAttemptTimer() {
  if (attemptTimer) clearInterval(attemptTimer);
  attemptTimer = null;
  updateAttemptClock();
}

function setAttemptStatus({ selected = "미선택", result = "대기", path = "-" } = {}) {
  $("#attemptSelectedLabel").textContent = selected;
  $("#attemptResultLabel").textContent = result;
  $("#attemptPathLabel").textContent = path;
}

function clearAttemptDiagnosis() {
  latestAttemptDiagnosis = null;
  const selected = selectedAttemptChoice !== null;
  $("#problemAttemptDiagnosis").innerHTML = `
    <div class="attempt-empty">
      <strong>${selected ? "채점 대기" : "진단 대기"}</strong>
      <p>${selected ? `${selectedAttemptChoice + 1}번 선택됨` : "선택 전입니다."}</p>
    </div>
  `;
}

function renderChoiceBoard(item) {
  $("#problemChoiceBoard").innerHTML = item.choices
    .map(
      (choice, index) =>
        `<button class="choice-option" data-choice-index="${index}" type="button">
          <span>${index + 1}</span>
          <strong>${escapeHtml(choice)}</strong>
        </button>`,
    )
    .join("");
}

function updateChoiceSelection() {
  const buttons = document.querySelectorAll(".choice-option");
  buttons.forEach((button) => {
    const active = Number(button.dataset.choiceIndex) === selectedAttemptChoice;
    button.classList.toggle("selected", active);
  });
  $("#runAttemptDiagnosis").disabled = selectedAttemptChoice === null;
  setAttemptStatus({
    selected: selectedAttemptChoice === null ? "미선택" : `${selectedAttemptChoice + 1}번`,
    result: latestAttemptDiagnosis ? (latestAttemptDiagnosis.correct ? "정답" : "오답") : "대기",
    path: latestAttemptDiagnosis?.recommended_path?.label ?? "-",
  });
}

function resetProblemAttempt() {
  selectedAttemptChoice = null;
  latestAttemptDiagnosis = null;
  clearAttemptDiagnosis();
  updateChoiceSelection();
  startAttemptTimer();
}

function renderAttemptDiagnosis(diagnosis, persistenceLabel) {
  latestAttemptDiagnosis = diagnosis;
  stopAttemptTimer();
  const tags = diagnosis.mistake_tags?.length
    ? diagnosis.mistake_tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")
    : `<span>정리 완료</span>`;
  const elimination = diagnosis.selected_choice_elimination
    ? `<p>${escapeHtml(diagnosis.selected_choice_elimination.reason)}</p>`
    : `<p>정답 보기의 조건을 검산 경로로 확인했습니다.</p>`;
  const links = (diagnosis.missing_concept_links || [])
    .slice(0, 3)
    .map(
      (link) => `
        <li>
          <strong>${escapeHtml(link.concept_label)}</strong>
          <span>${escapeHtml(link.why_required)}</span>
        </li>
      `,
    )
    .join("");
  const steps = (diagnosis.recommended_path.ordered_steps || [])
    .slice(0, 4)
    .map((step) => `<li>${escapeHtml(step)}</li>`)
    .join("");

  setAttemptStatus({
    selected: `${diagnosis.selected_choice + 1}번`,
    result: diagnosis.correct ? "정답" : "오답",
    path: diagnosis.recommended_path.label,
  });
  updateChoiceSelection();
  $("#problemCorrectAnswer").textContent = `정답 ${diagnosis.correct_choice + 1}번`;

  $("#problemAttemptDiagnosis").innerHTML = `
    <div class="attempt-result-head">
      <strong>${diagnosis.correct ? "정답" : "오답"} · ${escapeHtml(diagnosis.next_action.action_type)}</strong>
      <span>${escapeHtml(persistenceLabel)}</span>
    </div>
    <div class="attempt-result-tags">${tags}</div>
    <div class="attempt-next-action">
      <span>판정 근거</span>
      ${elimination}
    </div>
    <div class="attempt-next-action">
      <span>다음 풀이</span>
      <p>${escapeHtml(diagnosis.recommended_path.label)} · ${escapeHtml(diagnosis.recommended_path.why_this_path)}</p>
      ${steps ? `<ol class="attempt-step-list">${steps}</ol>` : ""}
    </div>
    <div class="attempt-next-action">
      <span>바로 할 일</span>
      <p>${escapeHtml(diagnosis.next_action.action_text)}</p>
    </div>
    ${
      links
        ? `<ol class="attempt-concept-list">${links}</ol>`
        : `<p class="attempt-clear">이번 시도는 개념 재진입보다 변형 문제로 넘어가는 편이 낫습니다.</p>`
    }
  `;
}

async function submitProblemAttemptDiagnosis() {
  const item = problemSolutionMaps.find((problem) => problem.question_id === selectedProblemId);
  if (!item || selectedAttemptChoice === null) return;
  const timeSeconds = currentAttemptSeconds();
  const payload = {
    question_id: item.question_id,
    selected_choice: selectedAttemptChoice,
    time_seconds: timeSeconds,
    time_limit_seconds: 120,
  };

  try {
    const response = await fetch("/attempts/diagnose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`attempt ${response.status}`);
    const data = await response.json();
    renderAttemptDiagnosis(data.diagnosis, "서버 기록됨");
  } catch (_err) {
    const diagnosis = diagnoseProblemAttemptLocal(
      item,
      selectedAttemptChoice,
      timeSeconds,
      120,
    );
    renderAttemptDiagnosis(diagnosis, "로컬 미리보기");
  }
}

function renderQuestionAnalysis(item) {
  const analysis = item.question_analysis;
  if (!analysis) {
    $("#problemQuestionType").textContent = "-";
    $("#problemIntent").innerHTML = `<p class="muted-note">출제 의도 분석이 아직 생성되지 않았습니다.</p>`;
    $("#stemConditionList").innerHTML = "";
    return;
  }

  const combinations = analysis.concept_combination ?? [];
  const stemConditions = analysis.stem_conditions ?? [];
  const mustNotMiss = analysis.question_stem_parse?.must_not_miss ?? [];
  const roleLabel = { trigger: "판별 신호", ask: "질문 요구", distractor: "오답 유인" };

  $("#problemQuestionType").textContent = analysis.question_type ?? "mixed";
  $("#problemIntent").innerHTML = `
    <div class="intent-grid">
      <section>
        <span>의도</span>
        <p>${escapeHtml(analysis.examiner_intent ?? "")}</p>
      </section>
      <section>
        <span>질문</span>
        <p>${escapeHtml(analysis.asked_output ?? analysis.question_stem_parse?.target_entity ?? "")}</p>
      </section>
      <section>
        <span>놓치면 안 되는 조건</span>
        <div class="intent-chip-row">
          ${mustNotMiss.map((item) => `<em>${escapeHtml(item)}</em>`).join("")}
        </div>
      </section>
    </div>
    <div class="intent-section-label">개념 조합</div>
    <div class="concept-combination-list">
      ${combinations
        .map(
          (row) => `
            <section>
              <strong>${escapeHtml(row.concept ?? "개념 조합")}</strong>
              <p>${escapeHtml(row.why_combined ?? "")}</p>
              <small>${escapeHtml(row.examiner_objective ?? "")}</small>
            </section>
          `,
        )
        .join("")}
    </div>
  `;
  $("#stemConditionList").innerHTML = `
    <div class="intent-section-label">본문 신호</div>
    <div class="stem-condition-list">
      ${stemConditions
        .map(
          (condition) => `
            <section>
              <span>${escapeHtml(roleLabel[condition.role] ?? condition.role ?? "signal")}</span>
              <strong>${escapeHtml(condition.text ?? "")}</strong>
              <p>${escapeHtml(condition.why_it_matters ?? "")}</p>
            </section>
          `,
        )
        .join("")}
    </div>
  `;
}

function renderSelectedProblemMap() {
  const item = problemSolutionMaps.find((problem) => problem.question_id === selectedProblemId);
  if (!item) {
    $("#problemSolutionSummary").textContent = "문제 풀이맵 없음";
    $("#problemMeta").textContent = "데이터 없음";
    $("#problemTitle").textContent = "문제별 풀이 지능";
    $("#problemStem").textContent = "problem_solution_maps.json을 먼저 생성해야 합니다.";
    $("#problemConceptTags").innerHTML = "";
    $("#problemChoiceBoard").innerHTML = "";
    setAttemptStatus();
    clearAttemptDiagnosis();
    $("#problemSolutionPaths").innerHTML = "";
    $("#problemQuestionType").textContent = "-";
    $("#problemIntent").innerHTML = "";
    $("#stemConditionList").innerHTML = "";
    return;
  }

  $("#problemSolutionSummary").textContent = `${problemSolutionMaps.length}개 문제 · ${problemSolutionMaps.reduce((sum, problem) => sum + problem.solution_paths.length, 0)}개 풀이`;
  $("#problemMeta").textContent = `${SUBJECT_LABEL[displaySubjectKey(item)] ?? item.subject} · ${item.unit} · ${item.applicable_year ?? "연도 미지정"}`;
  $("#problemTitle").textContent = item.question_id;
  $("#problemStem").textContent = item.stem;
  $("#problemConceptTags").innerHTML = item.concept_tags
    .map((tag) => `<span>${escapeHtml(tag)}</span>`)
    .join("");
  $("#problemCorrectAnswer").textContent = "정답 비공개";
  $("#problemRightsStatus").textContent = item.rights_status;
  $("#problemReviewStatus").textContent = item.review_status;
  renderChoiceBoard(item);
  renderQuestionAnalysis(item);
  resetProblemAttempt();
  $("#problemSolutionPaths").innerHTML = `
    <details class="solution-library">
      <summary>풀이 경로 ${item.solution_paths.length}개</summary>
      <div class="solution-library-grid">
        ${item.solution_paths
          .map(
            (path) => `
              <article class="problem-path-card">
                <p class="eyebrow">${escapeHtml(path.path_type)} · 신뢰도 ${Math.round(path.confidence * 100)}%</p>
                <h3>${escapeHtml(path.label)}</h3>
                <p>${escapeHtml(path.why_this_path)}</p>
                <div class="problem-path-meta">
                  ${path.trigger_signals.map((signal) => `<span>${escapeHtml(signal)}</span>`).join("")}
                </div>
                <ol>
                  ${path.ordered_steps.map((step) => `<li>${escapeHtml(step)}</li>`).join("")}
                </ol>
              </article>
            `,
          )
          .join("")}
      </div>
    </details>
  `;
}

async function loadProblemSolutionMaps() {
  try {
    const response = await fetch("problem_solution_maps.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`problem solutions ${response.status}`);
    const data = await response.json();
    problemSolutionMaps = data.problem_solution_maps || [];
    renderProblemFilters();
    renderDailyPrescription(buildPayload(), latestPrescription);
  } catch (err) {
    $("#problemSolutionSummary").textContent = `문제 풀이맵 로딩 실패: ${err.message}`;
    renderSelectedProblemMap();
  }
}

$("#todayProblemList").addEventListener("click", (event) => {
  const button = event.target.closest("[data-problem-id]");
  if (!button) return;
  openProblemMap(button.dataset.problemId);
  activateView("problem");
});

$("#problemSubjectFilter").addEventListener("change", () => {
  selectedProblemId = null;
  renderProblemOptions();
});

$("#problemSolutionSelect").addEventListener("change", (event) => {
  selectedProblemId = event.target.value;
  renderSelectedProblemMap();
});

$("#problemChoiceBoard").addEventListener("click", (event) => {
  const button = event.target.closest(".choice-option");
  if (!button) return;
  const hadDiagnosis = latestAttemptDiagnosis !== null;
  selectedAttemptChoice = Number(button.dataset.choiceIndex);
  latestAttemptDiagnosis = null;
  clearAttemptDiagnosis();
  if (hadDiagnosis) startAttemptTimer();
  updateChoiceSelection();
});

$("#runAttemptDiagnosis").addEventListener("click", submitProblemAttemptDiagnosis);

$("#resetProblemAttempt").addEventListener("click", resetProblemAttempt);

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
  $("#pastExamAssetCount").textContent = stats.past_exam_assets ?? 0;
  $("#assetDocumentCount").textContent = stats.asset_documents ?? 0;
  $("#learningJobCount").textContent = stats.learning_jobs ?? 0;
  $("#trainableAfterReviewCount").textContent = stats.trainable_after_review_jobs ?? 0;
  $("#blockedLearningJobCount").textContent = stats.learning_status?.blocked ?? 0;
  $("#subjectTutorialCount").textContent = stats.subject_tutorials ?? 0;
  $("#tutorialStepCount").textContent = stats.tutorial_steps ?? 0;
  $("#solutionPathCount").textContent = stats.solution_paths ?? 0;
  $("#solutionConceptLinkCount").textContent = stats.solution_concept_links ?? 0;
  $("#solutionRationaleCount").textContent = stats.solution_rationales ?? 0;
  $("#problemSolutionMapCount").textContent = stats.problem_solution_maps ?? 0;
  $("#problemSolutionPathCount").textContent = stats.problem_solution_paths ?? 0;
  $("#problemChoiceEliminationCount").textContent = stats.problem_choice_eliminations ?? 0;
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
renderCoachFromState(buildPayload());
renderDailyPrescription(buildPayload());
renderWeek();
loadDataManifest();
loadSubjectTutorials();
loadProblemSolutionMaps();
healthCheck().then((ok) => {
  if (ok) triggerDiagnose();
});
