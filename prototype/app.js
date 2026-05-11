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
let diagnoseTimer = null;

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

function filteredProblemMaps() {
  const subject = $("#problemSubjectFilter").value;
  return problemSolutionMaps.filter((item) => subject === "all" || item.subject === subject);
}

function renderProblemFilters() {
  const subjects = new Map();
  problemSolutionMaps.forEach((item) => subjects.set(item.subject, SUBJECT_LABEL[item.subject] ?? item.subject));
  $("#problemSubjectFilter").innerHTML = [
    `<option value="all">전체</option>`,
    ...Array.from(subjects, ([value, label]) => `<option value="${escapeAttr(value)}">${escapeHtml(label)}</option>`),
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

function renderSelectedProblemMap() {
  const item = problemSolutionMaps.find((problem) => problem.question_id === selectedProblemId);
  if (!item) {
    $("#problemSolutionSummary").textContent = "문제 풀이맵 없음";
    $("#problemMeta").textContent = "데이터 없음";
    $("#problemTitle").textContent = "문제별 풀이 지능";
    $("#problemStem").textContent = "problem_solution_maps.json을 먼저 생성해야 합니다.";
    $("#problemConceptTags").innerHTML = "";
    $("#problemSolutionPaths").innerHTML = "";
    return;
  }

  $("#problemSolutionSummary").textContent = `${problemSolutionMaps.length}개 문제 · ${problemSolutionMaps.reduce((sum, problem) => sum + problem.solution_paths.length, 0)}개 풀이`;
  $("#problemMeta").textContent = `${SUBJECT_LABEL[item.subject] ?? item.subject} · ${item.unit} · ${item.applicable_year ?? "연도 미지정"}`;
  $("#problemTitle").textContent = item.question_id;
  $("#problemStem").textContent = item.stem;
  $("#problemConceptTags").innerHTML = item.concept_tags
    .map((tag) => `<span>${escapeHtml(tag)}</span>`)
    .join("");
  $("#problemCorrectAnswer").textContent = `${item.correct_choice + 1}. ${item.correct_answer}`;
  $("#problemRightsStatus").textContent = item.rights_status;
  $("#problemReviewStatus").textContent = item.review_status;
  $("#problemSolutionPaths").innerHTML = item.solution_paths
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
          <div class="problem-link-grid">
            ${(path.concept_links ?? [])
              .map(
                (link) => `
                  <div class="problem-concept-link">
                    <strong>${escapeHtml(link.concept_label)}</strong>
                    <small>${escapeHtml(link.why_required)}</small>
                    <small>판별: ${escapeHtml(link.decision_test)}</small>
                    <small>배제: ${escapeHtml(link.rejection_test)}</small>
                  </div>
                `,
              )
              .join("")}
          </div>
          ${
            path.choice_eliminations?.length
              ? `
                <div class="choice-elimination-list">
                  ${path.choice_eliminations
                    .map(
                      (choice) => `
                        <div class="choice-elimination">
                          <strong>${choice.choice_index + 1}. ${escapeHtml(choice.choice_text)}</strong>
                          <span class="choice-verdict">${choice.verdict === "keep_correct" ? "정답 유지" : "제거"}</span>
                          <small>${escapeHtml(choice.reason)}</small>
                        </div>
                      `,
                    )
                    .join("")}
                </div>
              `
              : ""
          }
        </article>
      `,
    )
    .join("");
}

async function loadProblemSolutionMaps() {
  try {
    const response = await fetch("problem_solution_maps.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`problem solutions ${response.status}`);
    const data = await response.json();
    problemSolutionMaps = data.problem_solution_maps || [];
    renderProblemFilters();
  } catch (err) {
    $("#problemSolutionSummary").textContent = `문제 풀이맵 로딩 실패: ${err.message}`;
    renderSelectedProblemMap();
  }
}

$("#problemSubjectFilter").addEventListener("change", () => {
  selectedProblemId = null;
  renderProblemOptions();
});

$("#problemSolutionSelect").addEventListener("change", (event) => {
  selectedProblemId = event.target.value;
  renderSelectedProblemMap();
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
renderWeek();
loadDataManifest();
loadSubjectTutorials();
loadProblemSolutionMaps();
healthCheck().then((ok) => {
  if (ok) triggerDiagnose();
});
