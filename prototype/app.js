// 동적 처방 대시보드. 백엔드: cpa_first.api.main (같은 호스트로 fetch).

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

const API_BASE = ""; // 같은 호스트(FastAPI가 정적도 서빙)

// ============================================================
// Subject registry — 백엔드 cpa_first/subjects.py와 동기화
// ============================================================

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

const SUBJECT_ORDER = [
  "accounting",
  "tax",
  "finance",
  "cost_accounting",
  "economics",
  "corporate_law",
  "business",
  "management",
];

const RISK_TAGS = [
  { id: "time_pressure", label: "시간 압박" },
  { id: "memory_decay", label: "휘발" },
  { id: "concept_gap", label: "개념 공백" },
  { id: "objective_entry_delay", label: "객관식 진입" },
  { id: "rotation_confusion", label: "회독 혼동" },
];

// 활성 과목/입력 상태 — UI와 payload의 단일 진실원
function defaultSubjectState() {
  const state = {};
  for (const id of SUBJECT_ORDER) {
    state[id] = {
      active: id === "accounting" || id === "tax",
      accuracy: id === "accounting" ? 52 : id === "tax" ? 46 : 50,
      overrun: id === "accounting" ? 30 : id === "tax" ? 15 : 20,
      tags: id === "accounting" || id === "tax" ? ["time_pressure", "objective_entry_delay"] : [],
    };
  }
  return state;
}

let subjectState = defaultSubjectState();

const env = {
  months: $("#monthsInput"),
  hours: $("#hoursInput"),
  stage: $("#stageInput"),
};

// ============================================================
// Subject smart table
// ============================================================

function renderSubjectTable() {
  const container = $("#subjectRows");
  if (!container) return;
  container.innerHTML = SUBJECT_ORDER.map((id) => {
    const s = subjectState[id];
    const chips = RISK_TAGS.map((t) => {
      const on = s.tags.includes(t.id);
      return `<button type="button" class="chip" data-tag="${t.id}" aria-pressed="${on}">${escapeHtml(t.label)}</button>`;
    }).join("");
    return `
      <div class="subject-row" data-subject="${id}" data-active="${s.active}" role="row">
        <button class="subject-row__toggle" type="button" data-action="toggle" aria-pressed="${s.active}">${escapeHtml(SUBJECT_LABEL[id])}</button>
        <input class="subject-row__num" type="number" data-field="accuracy" min="0" max="100" step="1" value="${s.accuracy}" ${s.active ? "" : "disabled"} aria-label="${escapeHtml(SUBJECT_LABEL[id])} 정답률" />
        <input class="subject-row__num" type="number" data-field="overrun" min="0" max="100" step="1" value="${s.overrun}" ${s.active ? "" : "disabled"} aria-label="${escapeHtml(SUBJECT_LABEL[id])} 시간초과율" />
        <div class="risk-chips" role="group" aria-label="${escapeHtml(SUBJECT_LABEL[id])} 리스크 태그">${chips}</div>
      </div>
    `;
  }).join("");
  updateSubjectTableMeta();
}

function updateSubjectTableMeta() {
  const active = SUBJECT_ORDER.filter((id) => subjectState[id].active).length;
  const meta = $("#subjectActiveCount");
  if (meta) meta.textContent = `${active}개 과목 활성 / ${SUBJECT_ORDER.length}`;
}

function attachSubjectTableEvents() {
  const container = $("#subjectRows");
  if (!container) return;

  container.addEventListener("click", (event) => {
    const row = event.target.closest(".subject-row");
    if (!row) return;
    const id = row.dataset.subject;

    if (event.target.matches('[data-action="toggle"]')) {
      subjectState[id].active = !subjectState[id].active;
      renderSubjectTable();
      scheduleDiagnose();
      return;
    }

    const chip = event.target.closest(".chip");
    if (chip && subjectState[id].active) {
      const tag = chip.dataset.tag;
      const tags = subjectState[id].tags;
      const idx = tags.indexOf(tag);
      if (idx >= 0) tags.splice(idx, 1);
      else tags.push(tag);
      chip.setAttribute("aria-pressed", String(idx < 0));
      scheduleDiagnose();
    }
  });

  container.addEventListener("input", (event) => {
    const input = event.target.closest(".subject-row__num");
    if (!input) return;
    const row = input.closest(".subject-row");
    const id = row.dataset.subject;
    const field = input.dataset.field;
    let v = Number(input.value);
    if (!Number.isFinite(v)) v = 0;
    v = Math.max(0, Math.min(100, v));
    subjectState[id][field] = v;
    scheduleDiagnose();
  });

  const reset = $("#subjectResetBtn");
  if (reset) {
    reset.addEventListener("click", () => {
      subjectState = defaultSubjectState();
      renderSubjectTable();
      scheduleDiagnose();
      showToast("진단 입력을 초기화했습니다.", "info");
    });
  }
}

function getSubjectStates() {
  return SUBJECT_ORDER.filter((id) => subjectState[id].active).map((id) => ({
    subject: id,
    accuracy: subjectState[id].accuracy / 100,
    time_overrun_rate: subjectState[id].overrun / 100,
    risk_tags: [...subjectState[id].tags],
  }));
}

function buildPayload() {
  const months = Number(env.months.value);
  const days = Math.max(1, Math.round(months * 30));
  return {
    user_id: "ui-user",
    target_exam: "CPA_1",
    days_until_exam: days,
    available_hours_per_day: Number(env.hours.value),
    current_stage: env.stage.value,
    subject_states: getSubjectStates(),
  };
}

// ============================================================
// Toast / status / help
// ============================================================

let toastSeq = 0;
function showToast(message, kind = "info", { duration = 3000 } = {}) {
  const container = $("#toastContainer");
  if (!container) return;
  const id = `t-${++toastSeq}`;
  const div = document.createElement("div");
  div.className = `toast toast--${kind}`;
  div.id = id;
  div.setAttribute("role", kind === "error" ? "alert" : "status");
  div.textContent = message;
  container.appendChild(div);
  setTimeout(() => {
    div.style.opacity = "0";
    div.style.transition = "opacity 0.2s ease";
    setTimeout(() => div.remove(), 220);
  }, duration);
}

function setStatusBar(text, kind = "ok") {
  const bar = $("#statusBar");
  const t = $("#statusText");
  if (!bar || !t) return;
  t.textContent = text;
  bar.classList.remove("is-error", "is-loading");
  if (kind === "error") bar.classList.add("is-error");
  if (kind === "loading") bar.classList.add("is-loading");
}

function showHelpModal() {
  if ($(".help-overlay")) return;
  const overlay = document.createElement("div");
  overlay.className = "help-overlay";
  overlay.innerHTML = `
    <div class="help-modal" role="dialog" aria-modal="true" aria-label="단축키">
      <h2>키보드 단축키</h2>
      <dl>
        <dt>g d</dt><dd>오늘의 처방</dd>
        <dt>g t</dt><dd>과목 튜토리얼</dd>
        <dt>g p</dt><dd>문제 훈련</dd>
        <dt>g s</dt><dd>맞춤 코치</dd>
        <dt>g i</dt><dd>레벨 진단</dd>
        <dt>g r</dt><dd>용어 사전</dd>
        <dt>?</dt><dd>이 화면</dd>
        <dt>Esc</dt><dd>닫기</dd>
      </dl>
      <button class="btn help-modal-close" type="button">닫기</button>
    </div>
  `;
  document.body.appendChild(overlay);
  const close = () => overlay.remove();
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) close();
  });
  overlay.querySelector(".help-modal-close").addEventListener("click", close);
}

function closeOverlays() {
  $$(".help-overlay").forEach((el) => el.remove());
  const detail = $("#evidenceDetail");
  if (detail && !detail.hidden) detail.hidden = true;
}

// ============================================================
// API + render
// ============================================================

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

function renderTasks(rx) {
  $("#planSummary").textContent = `${rx.daily_tasks.length}개 처방`;
  if (!rx.daily_tasks.length) {
    $("#taskList").innerHTML = `<li class="muted-note">처방이 없습니다.</li>`;
    return;
  }
  $("#taskList").innerHTML = rx.daily_tasks
    .map((task) => {
      const subj = SUBJECT_LABEL[task.subject] ?? task.subject;
      const min = task.estimated_minutes ? ` · ${task.estimated_minutes}분` : "";
      return `<li><strong>${subj}${min}</strong>${escapeHtml(task.task_text)}</li>`;
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
  const states = payload.subject_states;
  if (!states.length) {
    return {
      level: "입력 대기",
      mode: "과목 활성화 필요",
      focus: "과목 행을 선택해 주세요",
      defer: "—",
      reason: "진단 입력 테이블에서 분석할 과목을 1개 이상 활성화해 주세요.",
    };
  }
  const avgAccuracy = states.reduce((sum, s) => sum + s.accuracy, 0) / states.length;
  const maxOverrun = Math.max(...states.map((s) => s.time_overrun_rate));
  const weak = weakestSubjectState(payload);
  const weakSubjectKo = SUBJECT_LABEL[weak.subject] ?? weak.subject;
  const stage = payload.current_stage;
  const days = payload.days_until_exam;

  if (avgAccuracy < 0.5) {
    return {
      level: "기초 재구축",
      mode: "개념-예제 회복",
      focus: `${weakSubjectKo} 핵심 개념`,
      defer: "고난도 모의고사",
      reason: "평균 정답률이 50% 아래라 기출 회독보다 개념-풀이 연결을 먼저 복구해야 합니다.",
    };
  }
  if (maxOverrun >= 0.4) {
    return {
      level: "풀이 순서 교정",
      mode: "시간 방어",
      focus: `${weakSubjectKo} 시간초과 유형`,
      defer: "풀이 오래 붙잡기",
      reason: "정답률보다 시간초과율이 더 큰 병목입니다. 넘김 기준과 풀이 순서를 먼저 고정합니다.",
    };
  }
  if (stage === "objective_entry") {
    return {
      level: "객관식 전환",
      mode: "보기 판별 훈련",
      focus: `${weakSubjectKo} 낮은 난도 기출`,
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
    focus: `${weakSubjectKo} 약점 단원`,
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
  if (!payload.subject_states.length) {
    return { subject: "mixed", accuracy: 0.5, time_overrun_rate: 0, risk_tags: [] };
  }
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
  const weak = weakestSubjectState(payload);
  return [...problemSolutionMaps]
    .sort(
      (a, b) =>
        scoreProblemForToday(b, weak.subject, concepts, payload) -
        scoreProblemForToday(a, weak.subject, concepts, payload),
    )
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
  const topUnit = problems[0]
    ? `${SUBJECT_LABEL[displaySubjectKey(problems[0])] ?? problems[0].subject} ${unitLabel(problems[0].unit)}`
    : profile.focus;
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
  const firstIntent =
    firstProblem?.question_analysis?.examiner_intent ||
    "조건 신호를 보고 먼저 적용할 개념 체계를 고르는지 확인합니다.";

  return {
    title: `${weakLabel}부터 ${profile.mode} 모드로 시작`,
    reason: `${profile.reason} 오늘은 ${topUnit}을 먼저 풀고, 출제 의도와 오답 유인을 해설보다 먼저 확인합니다.`,
    budget: `${hours}시간 중 문제 ${problemMinutes}분 · 복습 ${reviewMinutes}분 우선 배정`,
    riskMode: `${profile.level} · ${profile.mode}`,
    weakSubject: `${weakLabel} 정답률 ${Math.round(weakState.accuracy * 100)}% · 시간초과 ${Math.round(weakState.time_overrun_rate * 100)}%`,
    verification:
      rx?.weekly_goal?.verification_metric || "오늘 문제별 선택지 제거 근거와 오답 원인 태그를 남깁니다.",
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
  $("#todayProblemSummary").textContent = prescription.problems.length
    ? `${prescription.problems.length}개 문제`
    : "풀이맵 로딩 중";
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
    : `<div class="empty-state"><strong>풀이맵 로딩 대기</strong><p>로딩되면 오늘 풀 문제가 자동으로 채워집니다.</p></div>`;

  $("#todayConceptList").innerHTML = prescription.concepts.length
    ? prescription.concepts
        .map(
          (concept, index) => `
            <article>
              <span>개념 ${index + 1}</span>
              <strong>${escapeHtml(concept)}</strong>
              <p>풀이 전에 정의, 적용 조건, 대표 함정 1개를 말로 확인합니다.</p>
            </article>
          `,
        )
        .join("")
    : `<p class="muted-note">우선순위 개념이 없습니다.</p>`;

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
  const verification =
    rx?.weekly_goal?.verification_metric || "오늘 풀이 로그 20개와 오답 원인 태그를 남깁니다.";

  $("#coachLevel").textContent = profile.level;
  $("#coachLevelReason").textContent = profile.reason;
  $("#coachMode").textContent = profile.mode;
  $("#coachModeReason").textContent = `${STAGE_LABEL[payload.current_stage] ?? payload.current_stage} 단계에 맞춰 자동 전환됩니다.`;
  $("#coachPrimaryAction").textContent = firstTask;
  $("#coachPrimaryReason").textContent = rx?.diagnosis?.summary || "현재 입력값 기준의 임시 처방입니다.";
  $("#coachFocus").textContent = concepts[0] || profile.focus;
  $("#coachDefer").textContent = profile.defer;
  $("#coachNextProblem").textContent =
    profile.level === "객관식 전환" ? "문제 훈련 탭의 낮은 난도 풀이맵" : "오답 원인이 남는 단원 문제";
  $("#coachVerification").textContent = verification;

  const guidelines = [
    firstTask,
    profile.defer ? `오늘 제외: ${profile.defer}.` : "",
    concepts[0]
      ? `${concepts[0]}은 풀이 전에 5분 요약 후 바로 문제로 확인합니다.`
      : `${profile.focus}은 개념 설명보다 예제 풀이로 확인합니다.`,
    "채점 후 정답보다 선택지 제거 근거를 먼저 확인합니다.",
  ].filter(Boolean);
  $("#coachGuidelines").innerHTML = guidelines.map((item) => `<li>${escapeHtml(item)}</li>`).join("");

  // Level signals — 활성 과목당 1개 카드
  const states = payload.subject_states;
  const signals = $("#levelSignals");
  if (!states.length) {
    signals.innerHTML = `<p class="muted-note">활성 과목이 없습니다.</p>`;
  } else {
    signals.innerHTML = states
      .map(
        (s) => `
          <article class="level-signal">
            <span>${escapeHtml(SUBJECT_LABEL[s.subject] ?? s.subject)}</span>
            <strong>정답률 ${Math.round(s.accuracy * 100)}%</strong>
            <small>시간초과 ${Math.round(s.time_overrun_rate * 100)}% · 태그 ${s.risk_tags.length}</small>
          </article>
        `,
      )
      .join("");
  }
  $("#levelDiagnosisTitle").textContent = profile.level;
  $("#levelDiagnosisBody").textContent = profile.reason;
}

function renderEvidence(rx) {
  const list = $("#evidenceList");
  $("#evidenceSummary").textContent = `${rx.evidence_refs.length}개 근거. 클릭해서 원본 조회.`;
  if (!rx.evidence_refs.length) {
    list.innerHTML = `<li class="muted-note">근거 없음.</li>`;
    return;
  }
  list.innerHTML = rx.evidence_refs
    .map(
      (ref, i) => `
        <li>
          <button class="evidence-card" data-ref-type="${ref.ref_type}" data-ref-id="${escapeAttr(ref.ref_id)}" data-idx="${i}">
            <span class="evidence-type">${REF_TYPE_LABEL[ref.ref_type] ?? ref.ref_type}</span>
            <div>
              <strong>${escapeHtml(ref.ref_id)}</strong>
              <small>${escapeHtml(ref.note ?? "")}</small>
            </div>
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
    showToast(`근거 조회 실패: ${err.message}`, "error");
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

  if (!payload.subject_states.length) {
    setStatusBar("활성 과목 없음 — 진단 보류", "loading");
    return;
  }

  if (inflight) inflight.aborted = true;
  const ticket = { aborted: false };
  inflight = ticket;
  setStatusBar("진단 중…", "loading");
  try {
    const body = await postDiagnose(payload);
    if (ticket.aborted) return;
    latestPrescription = body.prescription;
    render(body.prescription);
    setStatusBar("처방 동기화됨", "ok");
  } catch (err) {
    setStatusBar(`연결 실패: ${err.message}`, "error");
    showToast(`진단 실패: ${err.message}`, "error");
  }
}

function scheduleDiagnose() {
  const payload = buildPayload();
  updateSubjectTableMeta();
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

// ============================================================
// View routing + keyboard
// ============================================================

const VIEW_TITLE = {
  dashboard: "오늘의 처방",
  tutorials: "과목 튜토리얼",
  problem: "문제 훈련",
  stories: "맞춤 코치",
  interview: "레벨 진단",
  terms: "용어 사전",
};

function activateView(viewId) {
  const view = $(`#${viewId}`);
  if (!view) return;
  $$(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.view === viewId));
  $$(".view").forEach((item) => item.classList.toggle("active", item.id === viewId));
  const title = VIEW_TITLE[viewId];
  if (title) $("#topbarTitle").textContent = title;
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

// vim-style: g + key
let pendingGo = false;
let goTimeout = null;
const VIEW_BY_KEY = {};
$$(".nav-item").forEach((b) => {
  if (b.dataset.key) VIEW_BY_KEY[b.dataset.key] = b.dataset.view;
});

document.addEventListener("keydown", (event) => {
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  const target = event.target;
  const inField = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);

  if (event.key === "Escape") {
    closeOverlays();
    if (inField) target.blur();
    return;
  }

  if (inField) return;

  if (event.key === "?") {
    event.preventDefault();
    showHelpModal();
    return;
  }

  if (pendingGo && VIEW_BY_KEY[event.key]) {
    event.preventDefault();
    activateView(VIEW_BY_KEY[event.key]);
    pendingGo = false;
    clearTimeout(goTimeout);
    return;
  }

  if (event.key === "g") {
    event.preventDefault();
    pendingGo = true;
    clearTimeout(goTimeout);
    goTimeout = setTimeout(() => {
      pendingGo = false;
    }, 800);
  }
});

// env input listeners
Object.values(env).forEach((input) => {
  if (input) input.addEventListener("input", scheduleDiagnose);
});

// evidence card click delegation
$("#evidenceList").addEventListener("click", (event) => {
  const btn = event.target.closest(".evidence-card");
  if (!btn) return;
  loadEvidenceDetail(btn.dataset.refType, btn.dataset.refId);
});

// ============================================================
// 과목별 튜토리얼
// ============================================================

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

// ============================================================
// 문제별 풀이 맵
// ============================================================

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

function renderProblemFilters() {
  const present = new Set(problemSolutionMaps.map(displaySubjectKey));
  const ordered = SUBJECT_ORDER.filter((key) => present.has(key));
  Array.from(present).forEach((key) => {
    if (!ordered.includes(key)) ordered.push(key);
  });
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

function setAttemptStatus({ selected = "미선택", result = "대기", path = "—" } = {}) {
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
    path: latestAttemptDiagnosis?.recommended_path?.label ?? "—",
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
    const diagnosis = diagnoseProblemAttemptLocal(item, selectedAttemptChoice, timeSeconds, 120);
    renderAttemptDiagnosis(diagnosis, "로컬 미리보기");
  }
}

function renderQuestionAnalysis(item) {
  const analysis = item.question_analysis;
  if (!analysis) {
    $("#problemQuestionType").textContent = "—";
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
    $("#problemQuestionType").textContent = "—";
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

// ============================================================
// 06번 데이터 적재 manifest (기존 보존)
// ============================================================

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

// ============================================================
// 정적 주간 운영판
// ============================================================

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

// ============================================================
// 부트
// ============================================================

async function healthCheck() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    setStatusBar(`엔진 준비됨 · 규칙 ${data.decision_rules} · 문제 ${data.problems}`, "ok");
    return true;
  } catch (err) {
    setStatusBar(`엔진 연결 실패 — cpa-serve 실행 필요 (${err.message})`, "error");
    return false;
  }
}

renderSubjectTable();
attachSubjectTableEvents();
renderCoachFromState(buildPayload());
renderDailyPrescription(buildPayload());
renderWeek();
loadDataManifest();
loadSubjectTutorials();
loadProblemSolutionMaps();
initTermsView();
healthCheck().then((ok) => {
  if (ok) triggerDiagnose();
});

// ============================================================
// 용어 사전 (Phase 7)
// ============================================================

const SUBJECT_LABEL_KO = {
  accounting: "회계학",
  tax: "세법",
  business: "경영학",
  economics: "경제학",
  corporate_law: "상법",
  management: "경영",
  finance: "재무",
  cost_accounting: "원가",
  general: "일반",
};

const DIFFICULTY_LABEL_KO = {
  foundational: "기초",
  intermediate: "중급",
  advanced: "심화",
};

let termSearchTimer = null;
let lastTermQuery = "";

function initTermsView() {
  const input = $("#termSearchInput");
  if (!input) return;
  input.addEventListener("input", () => {
    const q = input.value.trim();
    if (q === lastTermQuery) return;
    lastTermQuery = q;
    if (termSearchTimer) clearTimeout(termSearchTimer);
    termSearchTimer = setTimeout(() => runTermSearch(q), 150);
  });
}

async function runTermSearch(q) {
  const meta = $("#termSearchMeta");
  const resultsBox = $("#termResults");
  if (!q) {
    meta.textContent = "검색어를 입력하면 결과가 표시됩니다.";
    resultsBox.innerHTML = '<p class="terms-empty">왼쪽 검색창에 용어를 입력하세요.</p>';
    return;
  }
  meta.textContent = `"${q}" 검색 중…`;
  try {
    const res = await fetch(`${API_BASE}/terms/search?q=${encodeURIComponent(q)}&limit=30`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderTermResults(data.results, q);
  } catch (err) {
    meta.textContent = `검색 실패 — ${err.message}`;
    resultsBox.innerHTML = `<p class="terms-empty">서버 연결 실패. \`cpa-serve\` 실행 확인.</p>`;
  }
}

function renderTermResults(results, query) {
  const meta = $("#termSearchMeta");
  const box = $("#termResults");
  meta.textContent = `"${query}" — ${results.length}개 결과`;
  if (!results.length) {
    box.innerHTML = '<p class="terms-empty">매칭되는 용어가 없습니다.</p>';
    return;
  }
  const html = results
    .map((r) => {
      const subject = SUBJECT_LABEL_KO[r.subject] || r.subject;
      const difficulty = DIFFICULTY_LABEL_KO[r.difficulty] || r.difficulty;
      return `
        <button class="term-result" data-term-id="${escapeAttr(r.term_id)}">
          <span class="term-result-name">${escapeHtml(r.name_ko)}</span>
          <span class="term-result-meta">${escapeHtml(subject)} · ${escapeHtml(difficulty)}${
        r.unit ? ` · ${escapeHtml(r.unit)}` : ""
      }</span>
        </button>
      `;
    })
    .join("");
  box.innerHTML = html;
  box.querySelectorAll(".term-result").forEach((btn) => {
    btn.addEventListener("click", () => loadTermDetail(btn.dataset.termId));
  });
}

async function loadTermDetail(termId) {
  const detail = $("#termDetail");
  detail.innerHTML = '<p class="terms-empty">로딩 중…</p>';
  try {
    const res = await fetch(`${API_BASE}/terms/${encodeURIComponent(termId)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    renderTermDetail(data);
  } catch (err) {
    detail.innerHTML = `<p class="terms-empty">불러오기 실패 — ${escapeHtml(err.message)}</p>`;
  }
}

function renderTermDetail(data) {
  const { term, related } = data;
  const subject = SUBJECT_LABEL_KO[term.subject] || term.subject;
  const difficulty = DIFFICULTY_LABEL_KO[term.difficulty] || term.difficulty;
  const sections = [];

  sections.push(`
    <header class="term-detail-head">
      <p class="term-detail-tags">
        <span class="term-tag term-tag-subject">${escapeHtml(subject)}</span>
        <span class="term-tag">${escapeHtml(difficulty)}</span>
        ${term.unit ? `<span class="term-tag term-tag-unit">${escapeHtml(term.unit)}</span>` : ""}
        <span class="term-tag term-tag-review">${escapeHtml(term.review_status)}</span>
      </p>
      <h3>${escapeHtml(term.name_ko)}</h3>
      ${term.name_en ? `<p class="term-detail-en">${escapeHtml(term.name_en)}</p>` : ""}
      ${
        term.aliases && term.aliases.length
          ? `<p class="term-detail-aliases">동의어: ${term.aliases.map(escapeHtml).join(", ")}</p>`
          : ""
      }
    </header>
  `);

  sections.push(`
    <section class="term-section">
      <h4>정의</h4>
      <p>${escapeHtml(term.definition)}</p>
    </section>
  `);

  if (term.formula) {
    sections.push(`
      <section class="term-section">
        <h4>공식</h4>
        <pre class="term-formula">${escapeHtml(term.formula)}</pre>
      </section>
    `);
  }

  if (term.example) {
    sections.push(`
      <section class="term-section">
        <h4>예시</h4>
        <p>${escapeHtml(term.example)}</p>
      </section>
    `);
  }

  if (related.confusable_terms.length) {
    const items = related.confusable_terms
      .map((c) => {
        const name = c.name_ko || c.term_id;
        const action = c.in_seed
          ? `<button class="term-link" data-term-id="${escapeAttr(c.term_id)}">${escapeHtml(name)}</button>`
          : `<span class="term-link term-link-stub" title="시드에 등록되지 않은 용어">${escapeHtml(name)}</span>`;
        return `<li>${action}<p>${escapeHtml(c.reason || "")}</p></li>`;
      })
      .join("");
    sections.push(`
      <section class="term-section">
        <h4>헷갈리는 짝</h4>
        <ul class="term-pair-list">${items}</ul>
      </section>
    `);
  }

  if (related.prerequisite_terms.length) {
    const items = related.prerequisite_terms
      .map((p) => {
        const name = p.name_ko || p.term_id;
        return p.in_seed
          ? `<button class="term-link" data-term-id="${escapeAttr(p.term_id)}">${escapeHtml(name)}</button>`
          : `<span class="term-link term-link-stub">${escapeHtml(name)}</span>`;
      })
      .join(" ");
    sections.push(`
      <section class="term-section">
        <h4>선수 용어</h4>
        <div class="term-link-row">${items}</div>
      </section>
    `);
  }

  if (related.chunks.length) {
    const items = related.chunks
      .map(
        (c) =>
          `<li><strong>${escapeHtml(c.title || c.chunk_id)}</strong><span class="term-related-meta">${escapeHtml(
            c.subject,
          )} · w=${c.weight}</span></li>`,
      )
      .join("");
    sections.push(`
      <section class="term-section">
        <h4>관련 자료 (RAG)</h4>
        <ul class="term-related-list">${items}</ul>
      </section>
    `);
  }

  if (related.problems.length) {
    const items = related.problems
      .map(
        (p) =>
          `<li><strong>${escapeHtml(p.problem_id)}</strong><span class="term-related-meta">${escapeHtml(
            SUBJECT_LABEL_KO[p.subject] || p.subject,
          )}${p.unit ? ` · ${escapeHtml(p.unit)}` : ""} · w=${p.weight}</span></li>`,
      )
      .join("");
    sections.push(`
      <section class="term-section">
        <h4>관련 문제</h4>
        <ul class="term-related-list">${items}</ul>
      </section>
    `);
  }

  if (related.tutorials.length) {
    const items = related.tutorials
      .map(
        (t) =>
          `<li><strong>${escapeHtml(t.title || t.tutorial_id)}</strong><span class="term-related-meta">${escapeHtml(
            t.subject_name || "",
          )}</span></li>`,
      )
      .join("");
    sections.push(`
      <section class="term-section">
        <h4>튜토리얼</h4>
        <ul class="term-related-list">${items}</ul>
      </section>
    `);
  }

  const detail = $("#termDetail");
  detail.innerHTML = sections.join("");
  detail.querySelectorAll(".term-link[data-term-id]").forEach((btn) => {
    btn.addEventListener("click", () => loadTermDetail(btn.dataset.termId));
  });
}
