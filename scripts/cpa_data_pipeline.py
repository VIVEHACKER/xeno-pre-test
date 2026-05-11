import argparse
import csv
import hashlib
import html
import json
import re
import sqlite3
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib import robotparser
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "warehouse" / "cpa_first.sqlite"
DEFAULT_SEED = ROOT / "data" / "seeds" / "cpa_success_sources.csv"
DEFAULT_ONTOLOGY = ROOT / "data" / "seeds" / "exam_ontology.json"
DEFAULT_TARGETS = ROOT / "data" / "seeds" / "acquisition_targets.csv"
DEFAULT_EXAM_ASSETS = ROOT / "data" / "seeds" / "past_exam_assets.csv"
DEFAULT_TUTORIALS = ROOT / "data" / "seeds" / "subject_tutorials.json"
DEFAULT_EVALUATION = ROOT / "data" / "seeds" / "evaluation"
DEFAULT_MANIFEST = ROOT / "data" / "warehouse" / "manifest.json"
DEFAULT_PUBLIC_MANIFEST = ROOT / "prototype" / "data_manifest.json"
DEFAULT_PUBLIC_TUTORIALS = ROOT / "prototype" / "subject_tutorials.json"
DEFAULT_PUBLIC_PROBLEM_SOLUTIONS = ROOT / "prototype" / "problem_solution_maps.json"
USER_AGENT = "CPAFirstResearchBot/0.1 (+local research prototype)"
BLOCKED_RIGHTS_POLICIES = {"permission_required", "rights_check_required", "license_required"}
TRAINING_REVIEW_POLICIES = {"train_allowed_after_review", "train_after_rights_review"}
PROBLEM_SOLUTION_RIGHTS_ALLOWLIST = {"original_sample", "synthetic_seed", "rights_cleared_past_exam"}


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS sources (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  domain TEXT NOT NULL,
  source_type TEXT NOT NULL,
  exam TEXT NOT NULL,
  rights_policy TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 3,
  notes TEXT,
  collection_status TEXT NOT NULL DEFAULT 'seeded',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  fetched_at TEXT NOT NULL,
  robots_allowed INTEGER NOT NULL,
  http_status INTEGER,
  content_type TEXT,
  content_hash TEXT,
  content_length INTEGER NOT NULL DEFAULT 0,
  normalized_text TEXT,
  normalized_text_hash TEXT,
  fetch_error TEXT,
  UNIQUE(source_id, content_hash)
);

CREATE TABLE IF NOT EXISTS extracted_signals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  signal_type TEXT NOT NULL,
  subject TEXT NOT NULL,
  phase TEXT NOT NULL,
  signal_value TEXT NOT NULL,
  evidence_anchor TEXT NOT NULL,
  confidence REAL NOT NULL,
  extractor_version TEXT NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'machine_extracted',
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_rules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  rule_key TEXT NOT NULL UNIQUE,
  rule_name TEXT NOT NULL,
  condition_text TEXT NOT NULL,
  action_text TEXT NOT NULL,
  exception_text TEXT,
  source_signal_count INTEGER NOT NULL,
  confidence REAL NOT NULL,
  review_status TEXT NOT NULL DEFAULT 'machine_draft',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rule_signal_links (
  rule_id INTEGER NOT NULL REFERENCES strategy_rules(id) ON DELETE CASCADE,
  signal_id INTEGER NOT NULL REFERENCES extracted_signals(id) ON DELETE CASCADE,
  PRIMARY KEY (rule_id, signal_id)
);

CREATE TABLE IF NOT EXISTS ingestion_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  command TEXT NOT NULL,
  started_at TEXT NOT NULL,
  finished_at TEXT NOT NULL,
  stats_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS exam_subjects (
  subject_id TEXT PRIMARY KEY,
  exam_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  phase_name TEXT NOT NULL,
  subject_name TEXT NOT NULL,
  assessment_type TEXT NOT NULL,
  question_count INTEGER,
  minutes INTEGER,
  points INTEGER,
  source_url TEXT NOT NULL,
  notes TEXT,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_nodes (
  node_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL REFERENCES exam_subjects(subject_id) ON DELETE CASCADE,
  parent_node_id TEXT,
  node_name TEXT NOT NULL,
  node_type TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 3,
  source_basis TEXT NOT NULL,
  rights_policy TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS acquisition_targets (
  target_id TEXT PRIMARY KEY,
  exam_scope TEXT NOT NULL,
  subject_scope TEXT NOT NULL,
  data_category TEXT NOT NULL,
  url TEXT NOT NULL,
  source_owner TEXT NOT NULL,
  rights_policy TEXT NOT NULL,
  acquisition_method TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 3,
  notes TEXT,
  collection_status TEXT NOT NULL DEFAULT 'registered',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS past_exam_assets (
  asset_id TEXT PRIMARY KEY,
  exam_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  exam_year INTEGER,
  round_label TEXT NOT NULL,
  asset_kind TEXT NOT NULL,
  subject_scope TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT NOT NULL,
  source_owner TEXT NOT NULL,
  source_type TEXT NOT NULL,
  rights_policy TEXT NOT NULL,
  fetch_policy TEXT NOT NULL,
  training_policy TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 3,
  notes TEXT,
  processing_status TEXT NOT NULL DEFAULT 'registered',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS asset_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id TEXT NOT NULL REFERENCES past_exam_assets(asset_id) ON DELETE CASCADE,
  fetched_at TEXT NOT NULL,
  robots_allowed INTEGER NOT NULL,
  http_status INTEGER,
  content_type TEXT,
  content_hash TEXT,
  content_length INTEGER NOT NULL DEFAULT 0,
  extracted_title TEXT,
  attachment_names_json TEXT NOT NULL DEFAULT '[]',
  normalized_text_hash TEXT,
  fetch_error TEXT,
  UNIQUE(asset_id, content_hash)
);

CREATE TABLE IF NOT EXISTS problem_learning_jobs (
  job_id TEXT PRIMARY KEY,
  asset_id TEXT NOT NULL REFERENCES past_exam_assets(asset_id) ON DELETE CASCADE,
  job_type TEXT NOT NULL,
  input_policy TEXT NOT NULL,
  training_policy TEXT NOT NULL,
  status TEXT NOT NULL,
  blocker TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subject_tutorials (
  tutorial_id TEXT PRIMARY KEY,
  subject_id TEXT NOT NULL REFERENCES exam_subjects(subject_id) ON DELETE CASCADE,
  exam_id TEXT NOT NULL,
  phase_id TEXT NOT NULL,
  phase_name TEXT NOT NULL,
  subject_name TEXT NOT NULL,
  assessment_type TEXT NOT NULL,
  entry_topic TEXT NOT NULL,
  title TEXT NOT NULL,
  level TEXT NOT NULL,
  objective TEXT NOT NULL,
  concept_atoms_json TEXT NOT NULL,
  source_policy TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tutorial_steps (
  step_id TEXT PRIMARY KEY,
  tutorial_id TEXT NOT NULL REFERENCES subject_tutorials(tutorial_id) ON DELETE CASCADE,
  step_order INTEGER NOT NULL,
  step_type TEXT NOT NULL,
  label TEXT NOT NULL,
  title TEXT NOT NULL,
  difficulty INTEGER NOT NULL,
  core_explanation TEXT NOT NULL,
  prompt TEXT NOT NULL,
  model_answer TEXT NOT NULL,
  learner_action TEXT NOT NULL,
  checkpoints_json TEXT NOT NULL,
  solution_paths_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(tutorial_id, step_order)
);

CREATE TABLE IF NOT EXISTS solution_concept_links (
  link_id TEXT PRIMARY KEY,
  step_id TEXT NOT NULL REFERENCES tutorial_steps(step_id) ON DELETE CASCADE,
  path_id TEXT NOT NULL,
  concept_label TEXT NOT NULL,
  concept_role TEXT NOT NULL,
  why_required TEXT NOT NULL,
  evidence_basis TEXT NOT NULL,
  decision_test TEXT NOT NULL,
  rejection_test TEXT NOT NULL,
  confidence REAL NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problem_solution_maps (
  problem_id TEXT PRIMARY KEY,
  exam TEXT NOT NULL,
  subject TEXT NOT NULL,
  unit TEXT NOT NULL,
  tutorial_id TEXT,
  rights_status TEXT NOT NULL,
  review_status TEXT NOT NULL,
  applicable_year INTEGER,
  stem_hash TEXT NOT NULL,
  stem TEXT NOT NULL,
  choices_json TEXT NOT NULL,
  correct_choice INTEGER NOT NULL,
  concept_tags_json TEXT NOT NULL,
  explanation TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problem_solution_paths (
  path_id TEXT PRIMARY KEY,
  problem_id TEXT NOT NULL REFERENCES problem_solution_maps(problem_id) ON DELETE CASCADE,
  path_type TEXT NOT NULL,
  label TEXT NOT NULL,
  why_this_path TEXT NOT NULL,
  trigger_signals_json TEXT NOT NULL,
  do_not_use_when_json TEXT NOT NULL,
  ordered_steps_json TEXT NOT NULL,
  answer_index INTEGER NOT NULL,
  confidence REAL NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problem_solution_concept_links (
  link_id TEXT PRIMARY KEY,
  path_id TEXT NOT NULL REFERENCES problem_solution_paths(path_id) ON DELETE CASCADE,
  concept_label TEXT NOT NULL,
  concept_source TEXT NOT NULL,
  why_required TEXT NOT NULL,
  decision_test TEXT NOT NULL,
  rejection_test TEXT NOT NULL,
  evidence_basis TEXT NOT NULL,
  confidence REAL NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS problem_choice_eliminations (
  elimination_id TEXT PRIMARY KEY,
  path_id TEXT NOT NULL REFERENCES problem_solution_paths(path_id) ON DELETE CASCADE,
  choice_index INTEGER NOT NULL,
  choice_text TEXT NOT NULL,
  verdict TEXT NOT NULL,
  reason TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


@dataclass
class Signal:
  signal_type: str
  subject: str
  phase: str
  signal_value: str
  evidence_anchor: str
  confidence: float


class TextExtractor(HTMLParser):
  def __init__(self) -> None:
    super().__init__()
    self._skip_stack: list[str] = []
    self.parts: list[str] = []
    self.title = ""
    self._in_title = False

  def handle_starttag(self, tag: str, attrs) -> None:
    if tag in {"script", "style", "noscript", "svg"}:
      self._skip_stack.append(tag)
    if tag == "title":
      self._in_title = True
    if tag in {"p", "br", "li", "tr", "h1", "h2", "h3", "section", "article"}:
      self.parts.append("\n")

  def handle_endtag(self, tag: str) -> None:
    if self._skip_stack and self._skip_stack[-1] == tag:
      self._skip_stack.pop()
    if tag == "title":
      self._in_title = False
    if tag in {"p", "li", "tr", "h1", "h2", "h3"}:
      self.parts.append("\n")

  def handle_data(self, data: str) -> None:
    if self._skip_stack:
      return
    text = data.strip()
    if not text:
      return
    if self._in_title:
      self.title += text
    self.parts.append(text)

  def text(self) -> str:
    joined = " ".join(self.parts)
    joined = html.unescape(joined)
    joined = re.sub(r"[ \t\r\f\v]+", " ", joined)
    joined = re.sub(r"\n\s+", "\n", joined)
    return joined.strip()


def now() -> str:
  return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path) -> sqlite3.Connection:
  db_path.parent.mkdir(parents=True, exist_ok=True)
  conn = sqlite3.connect(db_path)
  conn.row_factory = sqlite3.Row
  conn.execute("PRAGMA foreign_keys = ON")
  return conn


def init_db(conn: sqlite3.Connection) -> None:
  conn.executescript(SCHEMA)
  conn.commit()


def seed_sources(conn: sqlite3.Connection, seed_path: Path) -> int:
  created = 0
  timestamp = now()
  with seed_path.open("r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
      domain = urlparse(row["url"]).netloc
      result = conn.execute(
        """
        INSERT OR IGNORE INTO sources
          (url, title, domain, source_type, exam, rights_policy, priority, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
          row["url"],
          row["title"],
          domain,
          row["source_type"],
          row["exam"],
          row["rights_policy"],
          int(row.get("priority") or 3),
          row.get("notes"),
          timestamp,
          timestamp,
        ),
      )
      created += result.rowcount
  conn.commit()
  return created


def seed_exam_ontology(conn: sqlite3.Connection, ontology_path: Path) -> dict:
  data = json.loads(ontology_path.read_text(encoding="utf-8"))
  timestamp = now()
  subjects = 0
  nodes = 0
  for subject in data["subjects"]:
    conn.execute(
      """
      INSERT INTO exam_subjects
        (subject_id, exam_id, phase_id, phase_name, subject_name, assessment_type,
         question_count, minutes, points, source_url, notes, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(subject_id) DO UPDATE SET
        exam_id = excluded.exam_id,
        phase_id = excluded.phase_id,
        phase_name = excluded.phase_name,
        subject_name = excluded.subject_name,
        assessment_type = excluded.assessment_type,
        question_count = excluded.question_count,
        minutes = excluded.minutes,
        points = excluded.points,
        source_url = excluded.source_url,
        notes = excluded.notes,
        updated_at = excluded.updated_at
      """,
      (
        subject["subject_id"],
        subject["exam_id"],
        subject["phase_id"],
        subject["phase_name"],
        subject["subject_name"],
        subject["assessment_type"],
        subject.get("question_count"),
        subject.get("minutes"),
        subject.get("points"),
        subject["source_url"],
        subject.get("notes"),
        timestamp,
      ),
    )
    subjects += 1
    for node_id, parent_node_id, node_name, node_type, priority in subject.get("nodes", []):
      conn.execute(
        """
        INSERT INTO knowledge_nodes
          (node_id, subject_id, parent_node_id, node_name, node_type, priority,
           source_basis, rights_policy, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(node_id) DO UPDATE SET
          subject_id = excluded.subject_id,
          parent_node_id = excluded.parent_node_id,
          node_name = excluded.node_name,
          node_type = excluded.node_type,
          priority = excluded.priority,
          source_basis = excluded.source_basis,
          rights_policy = excluded.rights_policy,
          updated_at = excluded.updated_at
        """,
        (
          node_id,
          subject["subject_id"],
          parent_node_id,
          node_name,
          node_type,
          int(priority),
          subject["source_url"],
          "metadata_and_concept_map",
          timestamp,
        ),
      )
      nodes += 1
  conn.commit()
  return {"exam_subjects": subjects, "knowledge_nodes": nodes, "ontology_version": data["version"]}


def solution_paths_for_step(tutorial: dict, step: dict) -> list[dict]:
  if step.get("solution_paths"):
    return [
      {
        **path,
        "selection_rationale": path.get("selection_rationale") or selection_rationale_for_path(tutorial, step, path),
        "concept_links": path.get("concept_links") or concept_links_for_path(tutorial, step, path),
      }
      for path in step["solution_paths"]
    ]

  is_written = tutorial.get("assessment_type") == "written"
  subject_name = tutorial["subject_name"]
  step_type = step["step_type"]
  paths = [
    {
      "path_id": f"{step_type}_direct",
      "label": "정석식",
      "method": f"{subject_name}의 기본 정의와 공식을 그대로 적용한다. 조건을 표시한 뒤 계산식 또는 판단 문장을 한 줄씩 쌓는다.",
      "when_to_use": "자료가 짧고 핵심 조건이 바로 보일 때",
    },
    {
      "path_id": f"{step_type}_table",
      "label": "표/구조식",
      "method": "조건을 표로 쪼갠다. 증가/감소, 내부/외부, 요건/효과, 시점/금액처럼 반대되는 칸을 먼저 만든다.",
      "when_to_use": "조건이 3개 이상이거나 실수하기 쉬운 방향 판단이 있을 때",
    },
    {
      "path_id": f"{step_type}_reverse_check",
      "label": "검산식",
      "method": f"구한 답을 원래 문장에 다시 넣는다. '{step['model_answer']}'라는 결론이 조건의 방향과 맞는지 확인한다.",
      "when_to_use": "계산 결과나 결론을 낸 직후",
    },
  ]
  if is_written:
    paths.append(
      {
        "path_id": f"{step_type}_answer_frame",
        "label": "답안목차식",
        "method": "쟁점, 요건, 계산 또는 포섭, 결론 순서로 답안 줄을 만든다. 숫자보다 채점자가 읽을 경로를 먼저 남긴다.",
        "when_to_use": "주관식에서 부분점수를 확보해야 할 때",
      }
    )
  else:
    paths.append(
      {
        "path_id": f"{step_type}_choice_elimination",
        "label": "선택지 제거식",
        "method": "정답을 바로 계산하기 전에 방향이 틀린 선택지를 먼저 지운다. 남은 선택지만 계산하거나 법적 효과를 대입한다.",
        "when_to_use": "객관식에서 시간이 부족하거나 숫자가 복잡할 때",
      }
    )
  return [
    {
      **path,
      "selection_rationale": selection_rationale_for_path(tutorial, step, path),
      "concept_links": concept_links_for_path(tutorial, step, path),
    }
    for path in paths
  ]


def path_family(path: dict) -> str:
  path_id = path["path_id"]
  if path_id.endswith("_direct"):
    return "direct"
  if path_id.endswith("_table"):
    return "table"
  if path_id.endswith("_reverse_check"):
    return "reverse_check"
  if path_id.endswith("_choice_elimination"):
    return "choice_elimination"
  if path_id.endswith("_answer_frame"):
    return "answer_frame"
  return "general"


def selection_rationale_for_path(tutorial: dict, step: dict, path: dict) -> dict:
  family = path_family(path)
  checkpoints = step.get("checkpoints", [])
  topic = tutorial["entry_topic"]
  if family == "direct":
    why = f"{topic}의 정의나 공식이 문제 조건에 바로 드러나므로 가장 짧은 경로다."
    use = [f"{topic} 키워드가 직접 보임", "계산 또는 판단 조건이 1-2개", "선택지보다 본문 조건이 명확함"]
    reject = ["조건이 3개 이상 섞임", "단계별 증명이 필요한 주관식", "계산 후 방향 검산이 불안함"]
  elif family == "table":
    why = "조건을 칸으로 분리해야 방향 실수를 줄일 수 있다."
    use = ["증가/감소처럼 반대 방향이 존재", "시점, 당사자, 세목, 계정이 2개 이상", "문제 풀이 중 누락 위험이 큼"]
    reject = ["조건이 하나라 표 작성이 시간 낭비", "정의 하나로 바로 판정 가능"]
  elif family == "reverse_check":
    why = "결론이 조건과 맞는지 되돌려 넣어 계산 실수와 법적 효과 착각을 잡는다."
    use = ["숫자 결과가 경계값 근처", "용어가 비슷해 방향 착각 가능", "답을 낸 뒤 10초 검산이 가능"]
    reject = ["아직 기본 풀이가 끝나지 않음", "검산보다 다음 문제 이동이 더 중요한 제한시간 상황"]
  elif family == "choice_elimination":
    why = "객관식에서는 모든 계산을 끝내기 전에 틀린 방향의 선택지를 먼저 지우는 것이 시간을 줄인다."
    use = ["선택지가 방향형", "본문 계산이 길지만 일부 선택지는 명백히 틀림", "시간 압박이 있음"]
    reject = ["선택지가 모두 숫자 근접형", "본문 조건을 이해하지 못한 상태"]
  elif family == "answer_frame":
    why = "주관식은 채점자가 읽는 경로가 점수이므로 목차가 먼저 필요하다."
    use = ["요건, 효과, 계산 과정이 채점 대상", "부분점수를 확보해야 함", "답안 분량을 통제해야 함"]
    reject = ["객관식 즉답 상황", "개념 정의 자체를 아직 모름"]
  else:
    why = "문제 조건을 안정적으로 해석하기 위한 보조 풀이 경로다."
    use = ["기본 경로가 막힘", "오답 원인을 분리해야 함"]
    reject = ["기본 정의가 불명확함"]

  return {
    "why_this_path": why,
    "use_when_signals": use,
    "do_not_use_when": reject,
    "evidence_basis": [
      f"entry_topic={topic}",
      f"step={step['label']}:{step['title']}",
      f"checkpoints={', '.join(checkpoints)}",
    ],
    "confidence": 0.72,
  }


def concept_links_for_path(tutorial: dict, step: dict, path: dict) -> list[dict]:
  atoms = tutorial.get("concept_atoms", [])
  checkpoints = step.get("checkpoints", [])
  family = path_family(path)
  role_by_family = {
    "direct": "definition_or_formula",
    "table": "condition_structure",
    "reverse_check": "answer_consistency",
    "choice_elimination": "wrong_choice_filter",
    "answer_frame": "scoring_frame",
    "general": "supporting_concept",
  }
  atom_index_by_family = {
    "direct": 0,
    "table": 1,
    "reverse_check": 2,
    "choice_elimination": 2,
    "answer_frame": 2,
    "general": 0,
  }
  selected_atom = atoms[min(atom_index_by_family.get(family, 0), max(0, len(atoms) - 1))] if atoms else tutorial["entry_topic"]
  checkpoint_label = " / ".join(checkpoints[:2]) if checkpoints else step["title"]
  return [
    {
      "concept_label": tutorial["entry_topic"],
      "concept_role": "domain_anchor",
      "why_required": f"문제가 {tutorial['entry_topic']} 단원의 기본 판단을 요구하므로 풀이의 출발점이 된다.",
      "evidence_basis": f"tutorial.entry_topic + step.prompt: {step['prompt']}",
      "decision_test": f"문장에 {tutorial['entry_topic']}와 연결되는 금액, 요건, 시점, 계정, 당사자가 있는가?",
      "rejection_test": "문제의 요구가 해당 단원 판단이 아니라 단순 암기 확인이면 보조 개념으로 낮춘다.",
      "confidence": 0.78,
    },
    {
      "concept_label": checkpoint_label,
      "concept_role": "condition_signal",
      "why_required": "풀이 경로를 고르기 전에 조건 신호를 판별해야 방향 실수를 줄일 수 있다.",
      "evidence_basis": f"step.checkpoints: {', '.join(checkpoints)}",
      "decision_test": f"체크포인트({checkpoint_label})가 문제 본문에 직접 또는 간접으로 주어졌는가?",
      "rejection_test": "체크포인트가 보이지 않으면 정석 계산보다 정의 확인이나 개념 복구를 먼저 한다.",
      "confidence": 0.74,
    },
    {
      "concept_label": selected_atom,
      "concept_role": role_by_family.get(family, "supporting_concept"),
      "why_required": f"{path['label']}은 이 개념을 사용해 문제의 조건을 풀이 가능한 구조로 바꾼다.",
      "evidence_basis": f"concept_atom + path.method: {path['method']}",
      "decision_test": f"{path['label']}을 적용하면 조건 누락 없이 답까지 이어지는가?",
      "rejection_test": f"{path['label']}을 써도 조건이 줄어들지 않거나 시간이 늘어나면 다른 풀이 경로로 전환한다.",
      "confidence": 0.72,
    },
  ]


def enriched_tutorials(data: dict) -> dict:
  enriched = json.loads(json.dumps(data, ensure_ascii=False))
  for tutorial in enriched["tutorials"]:
    for step in tutorial["steps"]:
      step["solution_paths"] = solution_paths_for_step(tutorial, step)
  return enriched


def seed_subject_tutorials(
  conn: sqlite3.Connection,
  tutorials_path: Path,
  public_path: Path = DEFAULT_PUBLIC_TUTORIALS,
) -> dict:
  timestamp = now()
  raw_data = json.loads(tutorials_path.read_text(encoding="utf-8"))
  data = enriched_tutorials(raw_data)
  source_policy = data["source_policy"]

  conn.execute("DELETE FROM solution_concept_links")
  conn.execute("DELETE FROM tutorial_steps")
  conn.execute("DELETE FROM subject_tutorials")

  tutorial_count = 0
  step_count = 0
  for tutorial in data["tutorials"]:
    conn.execute(
      """
      INSERT INTO subject_tutorials
        (tutorial_id, subject_id, exam_id, phase_id, phase_name, subject_name,
         assessment_type, entry_topic, title, level, objective, concept_atoms_json,
         source_policy, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      (
        tutorial["tutorial_id"],
        tutorial["subject_id"],
        tutorial["exam_id"],
        tutorial["phase_id"],
        tutorial["phase_name"],
        tutorial["subject_name"],
        tutorial["assessment_type"],
        tutorial["entry_topic"],
        tutorial["title"],
        tutorial["level"],
        tutorial["objective"],
        json.dumps(tutorial["concept_atoms"], ensure_ascii=False),
        source_policy,
        timestamp,
      ),
    )
    tutorial_count += 1
    for index, step in enumerate(tutorial["steps"], start=1):
      step_id = f"{tutorial['tutorial_id']}:{step['step_type']}"
      conn.execute(
        """
        INSERT INTO tutorial_steps
          (step_id, tutorial_id, step_order, step_type, label, title, difficulty,
           core_explanation, prompt, model_answer, learner_action, checkpoints_json,
           solution_paths_json, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
          step_id,
          tutorial["tutorial_id"],
          index,
          step["step_type"],
          step["label"],
          step["title"],
          int(step["difficulty"]),
          step["core_explanation"],
          step["prompt"],
          step["model_answer"],
          step["learner_action"],
          json.dumps(step["checkpoints"], ensure_ascii=False),
          json.dumps(step["solution_paths"], ensure_ascii=False),
          timestamp,
        ),
      )
      step_count += 1
      for path in step["solution_paths"]:
        for link_index, link in enumerate(path["concept_links"], start=1):
          link_id = f"{step_id}:{path['path_id']}:{link_index}"
          conn.execute(
            """
            INSERT INTO solution_concept_links
              (link_id, step_id, path_id, concept_label, concept_role, why_required,
               evidence_basis, decision_test, rejection_test, confidence, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
              link_id,
              step_id,
              path["path_id"],
              link["concept_label"],
              link["concept_role"],
              link["why_required"],
              link["evidence_basis"],
              link["decision_test"],
              link["rejection_test"],
              float(link["confidence"]),
              timestamp,
            ),
          )
  conn.commit()

  public_path.parent.mkdir(parents=True, exist_ok=True)
  public_payload = {
    "generated_at": timestamp,
    "version": data["version"],
    "source_policy": source_policy,
    "step_order": data["step_order"],
    "tutorials": data["tutorials"],
  }
  public_path.write_text(json.dumps(public_payload, ensure_ascii=False, indent=2), encoding="utf-8")
  concept_link_count = conn.execute("SELECT COUNT(*) FROM solution_concept_links").fetchone()[0]
  return {
    "subject_tutorials": tutorial_count,
    "tutorial_steps": step_count,
    "solution_concept_links": concept_link_count,
    "version": data["version"],
  }


def load_evaluation_questions(eval_dir: Path) -> list[dict]:
  questions: list[dict] = []
  for path in sorted(eval_dir.glob("**/*.evaluation_question.json")):
    questions.append(json.loads(path.read_text(encoding="utf-8")))
  return questions


def safe_problem_for_solution_map(question: dict) -> bool:
  return question["rights_status"] in PROBLEM_SOLUTION_RIGHTS_ALLOWLIST


def tutorial_id_for_question(question: dict) -> str:
  if question["subject"] == "accounting":
    return "tutorial_cpa1_accounting"
  if question["subject"] == "tax":
    return "tutorial_cpa1_tax"
  return ""


def problem_profile(question: dict) -> dict:
  unit = question["unit"]
  choices = question["choices"]
  correct = question["correct_choice"]
  correct_text = choices[correct]
  if unit == "financial_assets":
    return {
      "core": "상각후원가 금융자산의 유효이자율법",
      "signals": ["상각후원가 측정", "유효이자율", "이자수익", "기초 장부금액"],
      "direct_steps": [
        "금융자산 분류가 상각후원가 측정인지 확인한다.",
        "이자수익은 액면이자가 아니라 기초 장부금액 x 유효이자율임을 표시한다.",
        "950,260 x 10% = 95,026을 계산한다.",
        f"보기에서 {correct_text}를 선택한다.",
      ],
      "structure_steps": [
        "표 열을 액면금액, 액면이자율, 기초 장부금액, 유효이자율로 나눈다.",
        "액면이자 80,000은 현금수취액 칸에 두고 이자수익 칸과 분리한다.",
        "이자수익 칸에는 기초 장부금액 x 유효이자율만 넣는다.",
      ],
      "trap": "액면이자를 이자수익으로 고르는 함정",
      "eliminations": {
        0: "액면금액 x 액면이자율로 계산한 현금수취액이다.",
        2: "액면금액 x 유효이자율로 계산한 값이라 장부금액 기준을 놓쳤다.",
        3: "할인차금 상각액 또는 장부금액 변동을 이자수익과 혼동한 값이다.",
      },
    }
  if unit == "inventory":
    return {
      "core": "이동평균법과 판매 전후 평균단가 재계산",
      "signals": ["이동평균법", "매입 후 판매", "2차 매입", "기말재고 수량"],
      "direct_steps": [
        "1차 매입 후 평균단가를 계산한다: (100x1,000 + 200x1,200) / 300.",
        "250개 판매 후 남은 50개의 장부금액을 남긴다.",
        "2차 매입 100개를 더한 뒤 평균단가를 다시 계산한다.",
        "기말 150개 금액 약 196,667원과 가장 가까운 보기를 고른다.",
      ],
      "structure_steps": [
        "수량흐름표를 기초, 1차 매입, 판매, 2차 매입, 기말 순서로 만든다.",
        "판매가 일어난 시점 전 평균단가와 이후 평균단가를 분리한다.",
        "기말재고는 마지막 평균단가를 적용한다.",
      ],
      "trap": "전체 매입을 한 번에 평균내거나 판매 시점을 무시하는 함정",
      "eliminations": {
        0: "판매 시점 전후 평균단가를 낮게 잡은 값이다.",
        1: "계산값 196,667원보다 195,000원 보기가 더 가깝다.",
        3: "마지막 매입단가 1,400원에 기말수량을 바로 곱한 값이다.",
      },
    }
  if unit == "cost_management":
    return {
      "core": "CVP 분석의 단위당 공헌이익과 안전한계율",
      "signals": ["판매가격", "변동비", "고정비", "손익분기점", "안전한계율"],
      "direct_steps": [
        "단위당 공헌이익 = 5,000 - 3,000 = 2,000을 계산한다.",
        "BEP 판매량 = 4,000,000 / 2,000 = 2,000개를 구한다.",
        "BEP 매출액 = 2,000 x 5,000 = 10,000,000을 구한다.",
        "안전한계율 20%이면 현재 매출 = 10,000,000 / 0.8 = 12,500,000이다.",
      ],
      "structure_steps": [
        "가격, 변동비, 고정비, BEP, 안전한계율을 별도 칸으로 나눈다.",
        "단위당 공헌이익을 먼저 고정하고 모든 계산을 그 위에 얹는다.",
        "안전한계율은 현재 매출과 BEP 매출의 거리로 해석한다.",
      ],
      "trap": "안전한계율 20%를 안전한계 매출액 자체로 착각하는 함정",
      "eliminations": {
        0: "BEP 수량을 1,600개로 계산해 공헌이익 또는 고정비 적용이 틀렸다.",
        2: "BEP는 맞지만 안전한계율을 2,000,000원으로만 해석했다.",
        3: "BEP 수량을 2,500개로 계산해 공헌이익을 잘못 적용했다.",
      },
    }
  if unit == "vat":
    return {
      "core": "부가가치세 면세와 과세 거래 분류",
      "signals": ["면세 대상", "미가공 식료품", "수돗물", "외식 서비스", "의료보건 용역"],
      "direct_steps": [
        "각 보기를 기초생활필수재, 국민후생 용역, 일반 과세 용역으로 분류한다.",
        "미가공 식료품, 수돗물, 의료보건 용역은 면세 후보로 남긴다.",
        "일반 음식점 외식 서비스는 과세 용역이므로 면세 대상이 아니다.",
        f"면세 대상이 아닌 보기 {correct + 1}번을 선택한다.",
      ],
      "structure_steps": [
        "보기별로 재화/용역, 면세 범주, 과세 여부 세 칸을 만든다.",
        "면세 범주에 명확히 들어가는 보기를 제거한다.",
        "남는 일반 소비 서비스가 정답 후보가 된다.",
      ],
      "trap": "농산물 매입의 의제매입세액 공제와 음식점 용역의 과세 여부를 섞는 함정",
      "eliminations": {
        0: "미가공 식료품은 대표적인 면세 대상이다.",
        1: "수돗물 공급은 기초생활 관련 면세 범주에 속한다.",
        3: "허가받은 의료보건 용역은 국민후생 용역 면세 범주다.",
      },
    }
  if unit == "income_tax":
    return {
      "core": "금융소득 종합과세 기준금액과 전액 대상 판단",
      "signals": ["이자소득", "배당소득", "2,000만원 기준", "종합과세 대상"],
      "direct_steps": [
        "이자와 배당을 모두 금융소득으로 합산한다.",
        "1,500 + 600 + 300 = 2,400만원을 계산한다.",
        "기준금액 2,000만원을 초과하므로 금융소득 전액이 종합과세 대상임을 판단한다.",
        f"전액 종합과세 보기 {correct + 1}번을 선택한다.",
      ],
      "structure_steps": [
        "소득 종류, 금액, 금융소득 포함 여부, 종합과세 대상 여부 칸을 만든다.",
        "이자와 배당을 합산하고 기준금액과 비교한다.",
        "초과분만 대상인지 전액 대상인지 용어를 분리한다.",
      ],
      "trap": "기준금액 초과분만 종합과세 대상이라고 오해하는 함정",
      "eliminations": {
        0: "합계가 2,000만원을 초과하므로 전액 분리과세가 아니다.",
        1: "세액계산 구조의 초과분 개념을 종합과세 대상 금액과 혼동했다.",
        3: "비영업대금 이자만 따로 떼고 전체 금융소득 합산을 누락했다.",
      },
    }
  return {
    "core": "문제의 핵심 개념",
    "signals": question.get("concept_tags", [])[:4],
    "direct_steps": ["핵심 개념을 찾는다.", "조건을 분리한다.", "정답 보기와 대조한다."],
    "structure_steps": ["조건표를 만든다.", "방향을 판별한다.", "보기와 비교한다."],
    "trap": "조건 누락 함정",
    "eliminations": {},
  }


def problem_solution_concept_links(question: dict, profile: dict, path_type: str) -> list[dict]:
  tags = question.get("concept_tags") or [profile["core"]]
  path_roles = {
    "direct": "definition_or_formula",
    "structure": "condition_structure",
    "choice_elimination": "distractor_filter",
    "reverse_check": "answer_consistency",
  }
  return [
    {
      "concept_label": profile["core"],
      "concept_source": "unit_profile",
      "why_required": "이 개념이 문제의 계산식 또는 법적 분류 기준을 결정한다.",
      "decision_test": f"본문에 {', '.join(profile['signals'][:2])} 신호가 보이는가?",
      "rejection_test": "핵심 신호가 보이지 않으면 해당 단원 풀이가 아니라 다른 단원 판별부터 한다.",
      "evidence_basis": f"unit={question['unit']}; tags={', '.join(tags)}",
      "confidence": 0.82,
    },
    {
      "concept_label": " / ".join(profile["signals"][:3]),
      "concept_source": "condition_signal",
      "why_required": "풀이 경로 선택은 문제 본문에 드러난 조건 신호로 판별한다.",
      "decision_test": "조건 신호를 표시했을 때 계산 순서나 분류 순서가 하나로 정해지는가?",
      "rejection_test": "조건 신호가 서로 충돌하면 표/구조식으로 전환한다.",
      "evidence_basis": question["stem"][:180],
      "confidence": 0.78,
    },
    {
      "concept_label": path_roles[path_type],
      "concept_source": "solution_path",
      "why_required": f"{path_type} 풀이를 쓰는 직접 근거다.",
      "decision_test": "이 경로를 쓰면 오답 함정을 하나 이상 제거하거나 계산량을 줄이는가?",
      "rejection_test": "오답 함정이 줄지 않거나 설명이 길어지면 다른 풀이로 바꾼다.",
      "evidence_basis": profile["trap"],
      "confidence": 0.76,
    },
  ]


def choice_eliminations(question: dict, profile: dict) -> list[dict]:
  rows: list[dict] = []
  correct = question["correct_choice"]
  choices = question["choices"]
  for index, choice in enumerate(choices):
    if index == correct:
      reason = "핵심 개념과 조건 신호를 모두 만족하는 보기다."
      verdict = "keep_correct"
    else:
      reason = profile["eliminations"].get(index, "핵심 조건 또는 계산 방향과 맞지 않는다.")
      verdict = "eliminate"
    rows.append(
      {
        "choice_index": index,
        "choice_text": choice,
        "verdict": verdict,
        "reason": reason,
      }
    )
  return rows


def build_problem_solution_map(question: dict) -> dict:
  profile = problem_profile(question)
  answer_index = question["correct_choice"]
  answer_text = question["choices"][answer_index]
  base = {
    "question_id": question["question_id"],
    "exam": question["exam"],
    "subject": question["subject"],
    "unit": question["unit"],
    "tutorial_id": tutorial_id_for_question(question),
    "rights_status": question["rights_status"],
    "review_status": question["review_status"],
    "applicable_year": question.get("applicable_year"),
    "stem": question["stem"],
    "stem_hash": hashlib.sha256(question["stem"].encode("utf-8")).hexdigest(),
    "choices": question["choices"],
    "correct_choice": answer_index,
    "correct_answer": answer_text,
    "concept_tags": question.get("concept_tags", []),
    "explanation": question.get("explanation", ""),
  }
  path_specs = [
    (
      "direct",
      "정석식",
      f"{profile['core']}가 문제 본문에 직접 드러나므로 정의와 공식으로 바로 푼다.",
      profile["signals"][:3],
      ["조건이 시점별로 섞여 있거나 선택지 함정이 강하면 구조식으로 전환"],
      profile["direct_steps"],
    ),
    (
      "structure",
      "표/구조식",
      "조건을 표로 분리해야 판매 전후, 과세/면세, 증가/감소 같은 방향 실수를 줄일 수 있다.",
      profile["signals"],
      ["조건이 하나뿐이면 표 작성보다 정석식이 빠름"],
      profile["structure_steps"],
    ),
    (
      "choice_elimination",
      "선택지 제거식",
      "객관식에서는 대표 함정을 먼저 제거하면 계산량과 검산 부담이 줄어든다.",
      ["보기 중 하나가 대표 함정값", profile["trap"]],
      ["선택지가 모두 근접 숫자이면 제거식만으로 확정하지 않음"],
      [
        "각 보기가 어떤 계산 또는 분류를 전제로 하는지 표시한다.",
        "핵심 신호와 맞지 않는 보기를 제거한다.",
        f"남은 보기 {answer_index + 1}번({answer_text})을 정답으로 확정한다.",
      ],
    ),
    (
      "reverse_check",
      "검산식",
      "정답을 원문 조건과 해설 기준에 되돌려 넣어 계산값과 분류 기준이 맞는지 확인한다.",
      ["정답 확정 직후", "대표 함정 확인", "시간 10초 검산 가능"],
      ["아직 풀이식이 없거나 시간이 skip threshold를 넘긴 경우"],
      [
        f"정답 후보 {answer_text}를 문제의 핵심 조건에 다시 대입한다.",
        f"대표 함정: {profile['trap']}와 비교한다.",
        "해설의 계산 또는 분류 기준과 같은 결론인지 확인한다.",
      ],
    ),
  ]
  paths = []
  eliminations = choice_eliminations(question, profile)
  for path_type, label, why, triggers, reject, steps in path_specs:
    path_id = f"{question['question_id']}:{path_type}"
    paths.append(
      {
        "path_id": path_id,
        "path_type": path_type,
        "label": label,
        "why_this_path": why,
        "trigger_signals": triggers,
        "do_not_use_when": reject,
        "ordered_steps": steps,
        "answer_index": answer_index,
        "answer_text": answer_text,
        "concept_links": problem_solution_concept_links(question, profile, path_type),
        "choice_eliminations": eliminations if path_type == "choice_elimination" else [],
        "confidence": 0.78 if question["review_status"] == "expert_reviewed" else 0.68,
      }
    )
  base["solution_paths"] = paths
  return base


def seed_problem_solution_maps(
  conn: sqlite3.Connection,
  eval_dir: Path,
  public_path: Path = DEFAULT_PUBLIC_PROBLEM_SOLUTIONS,
) -> dict:
  timestamp = now()
  questions = [q for q in load_evaluation_questions(eval_dir) if safe_problem_for_solution_map(q)]
  maps = [build_problem_solution_map(q) for q in questions]

  conn.execute("DELETE FROM problem_choice_eliminations")
  conn.execute("DELETE FROM problem_solution_concept_links")
  conn.execute("DELETE FROM problem_solution_paths")
  conn.execute("DELETE FROM problem_solution_maps")

  for item in maps:
    conn.execute(
      """
      INSERT INTO problem_solution_maps
        (problem_id, exam, subject, unit, tutorial_id, rights_status, review_status,
         applicable_year, stem_hash, stem, choices_json, correct_choice,
         concept_tags_json, explanation, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      """,
      (
        item["question_id"],
        item["exam"],
        item["subject"],
        item["unit"],
        item["tutorial_id"],
        item["rights_status"],
        item["review_status"],
        item.get("applicable_year"),
        item["stem_hash"],
        item["stem"],
        json.dumps(item["choices"], ensure_ascii=False),
        item["correct_choice"],
        json.dumps(item["concept_tags"], ensure_ascii=False),
        item["explanation"],
        timestamp,
      ),
    )
    for path in item["solution_paths"]:
      conn.execute(
        """
        INSERT INTO problem_solution_paths
          (path_id, problem_id, path_type, label, why_this_path,
           trigger_signals_json, do_not_use_when_json, ordered_steps_json,
           answer_index, confidence, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
          path["path_id"],
          item["question_id"],
          path["path_type"],
          path["label"],
          path["why_this_path"],
          json.dumps(path["trigger_signals"], ensure_ascii=False),
          json.dumps(path["do_not_use_when"], ensure_ascii=False),
          json.dumps(path["ordered_steps"], ensure_ascii=False),
          path["answer_index"],
          float(path["confidence"]),
          timestamp,
        ),
      )
      for index, link in enumerate(path["concept_links"], start=1):
        conn.execute(
          """
          INSERT INTO problem_solution_concept_links
            (link_id, path_id, concept_label, concept_source, why_required,
             decision_test, rejection_test, evidence_basis, confidence, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
          """,
          (
            f"{path['path_id']}:{index}",
            path["path_id"],
            link["concept_label"],
            link["concept_source"],
            link["why_required"],
            link["decision_test"],
            link["rejection_test"],
            link["evidence_basis"],
            float(link["confidence"]),
            timestamp,
          ),
        )
      for elim in path["choice_eliminations"]:
        conn.execute(
          """
          INSERT INTO problem_choice_eliminations
            (elimination_id, path_id, choice_index, choice_text, verdict, reason, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?)
          """,
          (
            f"{path['path_id']}:{elim['choice_index']}",
            path["path_id"],
            elim["choice_index"],
            elim["choice_text"],
            elim["verdict"],
            elim["reason"],
            timestamp,
          ),
        )
  conn.commit()

  public_path.parent.mkdir(parents=True, exist_ok=True)
  public_payload = {
    "generated_at": timestamp,
    "source_policy": "safe_evaluation_questions_only",
    "problem_solution_maps": maps,
  }
  public_path.write_text(json.dumps(public_payload, ensure_ascii=False, indent=2), encoding="utf-8")

  return {
    "problem_solution_maps": len(maps),
    "problem_solution_paths": sum(len(item["solution_paths"]) for item in maps),
    "problem_solution_concept_links": sum(
      len(path["concept_links"]) for item in maps for path in item["solution_paths"]
    ),
    "problem_choice_eliminations": sum(
      len(path["choice_eliminations"]) for item in maps for path in item["solution_paths"]
    ),
  }


def seed_acquisition_targets(conn: sqlite3.Connection, targets_path: Path) -> int:
  timestamp = now()
  rows = 0
  with targets_path.open("r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
      conn.execute(
        """
        INSERT INTO acquisition_targets
          (target_id, exam_scope, subject_scope, data_category, url, source_owner,
           rights_policy, acquisition_method, priority, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(target_id) DO UPDATE SET
          exam_scope = excluded.exam_scope,
          subject_scope = excluded.subject_scope,
          data_category = excluded.data_category,
          url = excluded.url,
          source_owner = excluded.source_owner,
          rights_policy = excluded.rights_policy,
          acquisition_method = excluded.acquisition_method,
          priority = excluded.priority,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
          row["target_id"],
          row["exam_scope"],
          row["subject_scope"],
          row["data_category"],
          row["url"],
          row["source_owner"],
          row["rights_policy"],
          row["acquisition_method"],
          int(row.get("priority") or 3),
          row.get("notes"),
          timestamp,
          timestamp,
        ),
      )
      rows += 1
  conn.commit()
  return rows


def as_optional_int(value: str | None) -> int | None:
  if value is None or value == "":
    return None
  return int(value)


def effective_training_policy(row: dict[str, str] | sqlite3.Row) -> str:
  rights_policy = row["rights_policy"]
  requested_policy = row["training_policy"]
  source_type = row["source_type"]

  if rights_policy in BLOCKED_RIGHTS_POLICIES:
    return "do_not_train_until_permission"
  if source_type == "internal" and rights_policy == "owned_generated_content":
    return "train_allowed_after_review"
  return requested_policy


def seed_past_exam_assets(conn: sqlite3.Connection, assets_path: Path) -> int:
  timestamp = now()
  rows = 0
  with assets_path.open("r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
      training_policy = effective_training_policy(row)
      conn.execute(
        """
        INSERT INTO past_exam_assets
          (asset_id, exam_id, phase_id, exam_year, round_label, asset_kind,
           subject_scope, title, url, source_owner, source_type, rights_policy,
           fetch_policy, training_policy, priority, notes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(asset_id) DO UPDATE SET
          exam_id = excluded.exam_id,
          phase_id = excluded.phase_id,
          exam_year = excluded.exam_year,
          round_label = excluded.round_label,
          asset_kind = excluded.asset_kind,
          subject_scope = excluded.subject_scope,
          title = excluded.title,
          url = excluded.url,
          source_owner = excluded.source_owner,
          source_type = excluded.source_type,
          rights_policy = excluded.rights_policy,
          fetch_policy = excluded.fetch_policy,
          training_policy = excluded.training_policy,
          priority = excluded.priority,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        (
          row["asset_id"],
          row["exam_id"],
          row["phase_id"],
          as_optional_int(row.get("exam_year")),
          row["round_label"],
          row["asset_kind"],
          row["subject_scope"],
          row["title"],
          row["url"],
          row["source_owner"],
          row["source_type"],
          row["rights_policy"],
          row["fetch_policy"],
          training_policy,
          int(row.get("priority") or 3),
          row.get("notes"),
          timestamp,
          timestamp,
        ),
      )
      rows += 1
  conn.commit()
  return rows


def attachment_names_from_text(text: str) -> list[str]:
  names: list[str] = []
  for line in text.splitlines():
    stripped = line.strip()
    if not stripped:
      continue
    if re.search(r"\.(pdf|zip|hwp|hwpx|xlsx?|jpe?g|png)\b", stripped, flags=re.I):
      names.append(stripped[:240])
  return list(dict.fromkeys(names))


def fetch_past_exam_asset_metadata(conn: sqlite3.Connection, limit: int | None) -> dict:
  rows = conn.execute(
    """
    SELECT *
    FROM past_exam_assets
    WHERE fetch_policy = 'metadata_page'
      AND url NOT LIKE 'internal://%'
      AND url NOT LIKE 'manual://%'
    ORDER BY priority ASC, asset_id ASC
    """
  ).fetchall()
  if limit:
    rows = rows[:limit]

  stats = {"attempted": 0, "fetched": 0, "skipped_by_robots": 0, "failed": 0}
  for row in rows:
    stats["attempted"] += 1
    allowed = robots_allowed(row["url"])
    if not allowed:
      conn.execute(
        "UPDATE past_exam_assets SET processing_status = ?, updated_at = ? WHERE asset_id = ?",
        ("robots_disallowed", now(), row["asset_id"]),
      )
      conn.execute(
        """
        INSERT INTO asset_documents
          (asset_id, fetched_at, robots_allowed, fetch_error)
        VALUES (?, ?, ?, ?)
        """,
        (row["asset_id"], now(), 0, "robots.txt disallowed fetch"),
      )
      stats["skipped_by_robots"] += 1
      continue

    try:
      request = Request(row["url"], headers={"User-Agent": USER_AGENT})
      with urlopen(request, timeout=15) as response:
        body = response.read()
        status = getattr(response, "status", 200)
        content_type = response.headers.get("content-type")
      decoded = decode_body(body, content_type)
      title, text = normalize_html(decoded)
      raw_hash = hashlib.sha256(body).hexdigest()
      text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
      attachments = attachment_names_from_text(text)
      conn.execute(
        """
        INSERT OR IGNORE INTO asset_documents
          (asset_id, fetched_at, robots_allowed, http_status, content_type,
           content_hash, content_length, extracted_title, attachment_names_json,
           normalized_text_hash, fetch_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
          row["asset_id"],
          now(),
          1,
          status,
          content_type,
          raw_hash,
          len(text),
          title,
          json.dumps(attachments, ensure_ascii=False),
          text_hash,
        ),
      )
      status_value = "metadata_fetched_with_attachments" if attachments else "metadata_fetched"
      conn.execute(
        "UPDATE past_exam_assets SET processing_status = ?, updated_at = ? WHERE asset_id = ?",
        (status_value, now(), row["asset_id"]),
      )
      stats["fetched"] += 1
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
      conn.execute(
        "UPDATE past_exam_assets SET processing_status = ?, updated_at = ? WHERE asset_id = ?",
        ("fetch_failed", now(), row["asset_id"]),
      )
      conn.execute(
        """
        INSERT INTO asset_documents
          (asset_id, fetched_at, robots_allowed, fetch_error)
        VALUES (?, ?, ?, ?)
        """,
        (row["asset_id"], now(), 1, str(exc)[:500]),
      )
      stats["failed"] += 1
  conn.commit()
  return stats


def seed_problem_learning_jobs(conn: sqlite3.Connection) -> dict:
  timestamp = now()
  rows = conn.execute("SELECT * FROM past_exam_assets ORDER BY priority ASC, asset_id ASC").fetchall()
  created = 0
  for row in rows:
    if row["asset_kind"] in {"question", "question_answer"}:
      job_type = "problem_parse_and_solve"
    elif row["asset_kind"] == "answer":
      job_type = "answer_key_alignment"
    elif row["asset_kind"] == "explanation":
      job_type = "explanation_ingestion_or_generation"
    else:
      job_type = "asset_review"

    training_policy = effective_training_policy(row)
    if training_policy in TRAINING_REVIEW_POLICIES:
      status = "queued_rights_review"
      blocker = "rights_review_required_before_training"
    else:
      status = "blocked"
      blocker = "permission_or_license_required_before_training"

    if row["source_type"] == "internal" and training_policy == "train_allowed_after_review":
      status = "queued_generation"
      blocker = None

    job_id = f"{row['asset_id']}:{job_type}"
    conn.execute(
      """
      INSERT INTO problem_learning_jobs
        (job_id, asset_id, job_type, input_policy, training_policy, status, blocker,
         created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(job_id) DO UPDATE SET
        input_policy = excluded.input_policy,
        training_policy = excluded.training_policy,
        status = excluded.status,
        blocker = excluded.blocker,
        updated_at = excluded.updated_at
      """,
      (
        job_id,
        row["asset_id"],
        job_type,
        row["rights_policy"],
        training_policy,
        status,
        blocker,
        timestamp,
        timestamp,
      ),
    )
    created += 1
  conn.commit()
  return {"learning_jobs": created}


def seed_and_fetch_past_exam_assets(conn: sqlite3.Connection, assets_path: Path, limit: int | None) -> dict:
  seeded = seed_past_exam_assets(conn, assets_path)
  fetched = fetch_past_exam_asset_metadata(conn, limit)
  jobs = seed_problem_learning_jobs(conn)
  return {"seeded_assets": seeded, "fetch": fetched, **jobs}


def robots_allowed(url: str) -> bool:
  parsed = urlparse(url)
  robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
  parser = robotparser.RobotFileParser()
  parser.set_url(robots_url)
  try:
    parser.read()
    return parser.can_fetch(USER_AGENT, url)
  except Exception:
    return True


def decode_body(body: bytes, content_type: str | None) -> str:
  candidates: list[str] = []
  if content_type:
    match = re.search(r"charset=([\w\-]+)", content_type, flags=re.I)
    if match:
      candidates.append(match.group(1))
  candidates.extend(["utf-8", "cp949", "euc-kr"])
  for encoding in dict.fromkeys(candidates):
    try:
      return body.decode(encoding)
    except (LookupError, UnicodeDecodeError):
      continue
  return body.decode("utf-8", errors="replace")


def normalize_html(raw_html: str) -> tuple[str, str]:
  extractor = TextExtractor()
  extractor.feed(raw_html)
  return extractor.title.strip(), extractor.text()


def fetch_sources(conn: sqlite3.Connection, limit: int | None, store_text: bool) -> dict:
  rows = conn.execute(
    """
    SELECT * FROM sources
    WHERE source_type IN ('public_success_story', 'public_study_strategy', 'exam_statistics', 'official_exam_notice')
    ORDER BY priority ASC, id ASC
    """
  ).fetchall()
  if limit:
    rows = rows[:limit]

  stats = {"attempted": 0, "fetched": 0, "skipped_by_robots": 0, "failed": 0}
  for row in rows:
    stats["attempted"] += 1
    allowed = robots_allowed(row["url"])
    if not allowed:
      conn.execute(
        "UPDATE sources SET collection_status = ?, updated_at = ? WHERE id = ?",
        ("robots_disallowed", now(), row["id"]),
      )
      conn.execute(
        """
        INSERT INTO documents
          (source_id, fetched_at, robots_allowed, fetch_error)
        VALUES (?, ?, ?, ?)
        """,
        (row["id"], now(), 0, "robots.txt disallowed fetch"),
      )
      stats["skipped_by_robots"] += 1
      continue

    try:
      request = Request(row["url"], headers={"User-Agent": USER_AGENT})
      with urlopen(request, timeout=15) as response:
        body = response.read()
        status = getattr(response, "status", 200)
        content_type = response.headers.get("content-type")
      decoded = decode_body(body, content_type)
      title, text = normalize_html(decoded)
      raw_hash = hashlib.sha256(body).hexdigest()
      text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
      saved_text = text if store_text or row["rights_policy"] == "internal_analysis_only" else None
      conn.execute(
        """
        INSERT OR IGNORE INTO documents
          (source_id, fetched_at, robots_allowed, http_status, content_type, content_hash,
           content_length, normalized_text, normalized_text_hash, fetch_error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        """,
        (
          row["id"],
          now(),
          1,
          status,
          content_type,
          raw_hash,
          len(text),
          saved_text,
          text_hash,
        ),
      )
      conn.execute(
        """
        UPDATE sources
        SET collection_status = ?, title = COALESCE(NULLIF(?, ''), title), updated_at = ?
        WHERE id = ?
        """,
        ("fetched", title, now(), row["id"]),
      )
      stats["fetched"] += 1
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
      conn.execute(
        "UPDATE sources SET collection_status = ?, updated_at = ? WHERE id = ?",
        ("fetch_failed", now(), row["id"]),
      )
      conn.execute(
        """
        INSERT INTO documents
          (source_id, fetched_at, robots_allowed, fetch_error)
        VALUES (?, ?, ?, ?)
        """,
        (row["id"], now(), 1, str(exc)[:500]),
      )
      stats["failed"] += 1
  conn.commit()
  return stats


def split_sentences(text: str) -> list[str]:
  normalized = re.sub(r"([.!?。])\s+", r"\1\n", text)
  normalized = normalized.replace("다. ", "다.\n")
  normalized = normalized.replace("요. ", "요.\n")
  normalized = normalized.replace("음. ", "음.\n")
  normalized = normalized.replace("함. ", "함.\n")
  normalized = normalized.replace("됨. ", "됨.\n")
  rough = re.split(r"\n+", normalized)
  sentences = []
  for item in rough:
    cleaned = re.sub(r"\s+", " ", item).strip()
    if 35 <= len(cleaned) <= 360:
      sentences.append(cleaned)
  return sentences


def phase_for(sentence: str) -> str:
  if any(k in sentence for k in ["기본강의", "기본 강의", "강의"]):
    return "lecture"
  if any(k in sentence for k in ["객관식", "문제풀이", "문제 풀이"]):
    return "objective_entry"
  if any(k in sentence for k in ["기출", "회독"]):
    return "rotation"
  if any(k in sentence for k in ["모의고사", "실전", "시험장"]):
    return "mock_exam"
  if any(k in sentence for k in ["직전", "막판", "마지막"]):
    return "final"
  return "general"


def subject_for(sentence: str) -> str:
  has_accounting = any(k in sentence for k in ["회계", "재무회계", "원가", "관리회계"])
  has_tax = any(k in sentence for k in ["세법", "법인세", "소득세", "부가가치세", "말문제"])
  if has_accounting and has_tax:
    return "accounting_tax"
  if has_accounting:
    return "accounting"
  if has_tax:
    return "tax"
  return "general"


def signal_type_for(sentence: str) -> str:
  if any(k in sentence for k in ["해야", "추천", "반드시", "중요", "집중", "목표", "판단"]):
    return "decision_rule"
  if any(k in sentence for k in ["시작", "중순", "월", "기간", "때부터", "이후"]):
    return "timeline_event"
  if any(k in sentence for k in ["실수", "어렵", "불합격", "위험", "함정", "휘발"]):
    return "risk_pattern"
  return "subject_strategy"


def summarize_signal(sentence: str) -> str:
  if "객관식" in sentence:
    return "객관식 전환 시점과 전환 조건 후보"
  if "기출" in sentence:
    return "기출 회독 목적과 반복 방식 후보"
  if "세법" in sentence and "말문제" in sentence:
    return "세법 말문제 회상/압축 전략 후보"
  if "회계" in sentence and "세법" in sentence:
    return "회계/세법을 핵심 축으로 두는 시간 배분 후보"
  if "회계" in sentence:
    return "회계학 점수 전환 또는 풀이 운영 신호"
  if "세법" in sentence:
    return "세법 휘발/계산/암기 운영 신호"
  if "모의고사" in sentence:
    return "모의고사 단계 운영 신호"
  return "CPA 수험 전략 신호"


def evidence_anchor(sentence: str) -> str:
  compact = re.sub(r"\s+", " ", sentence).strip()
  digest = hashlib.sha256(compact.encode("utf-8")).hexdigest()[:12]
  tokens = [token for token in re.findall(r"[가-힣A-Za-z0-9]{2,}", compact)[:10]]
  return f"sha256:{digest}; keywords:{','.join(tokens)}"


def extract_signals_from_text(text: str, max_per_document: int) -> list[Signal]:
  keywords = [
    "회계",
    "세법",
    "객관식",
    "기출",
    "회독",
    "모의고사",
    "시간",
    "전략",
    "집중",
    "휘발",
    "말문제",
    "계산",
    "기본강의",
    "연습서",
    "점수",
    "합격"
  ]
  signals: list[Signal] = []
  seen: set[str] = set()
  for sentence in split_sentences(text):
    hit_count = sum(1 for keyword in keywords if keyword in sentence)
    if hit_count < 2:
      continue
    value = summarize_signal(sentence)
    anchor = evidence_anchor(sentence)
    key = f"{value}:{anchor}"
    if key in seen:
      continue
    seen.add(key)
    confidence = min(0.92, 0.46 + hit_count * 0.07)
    signals.append(
      Signal(
        signal_type=signal_type_for(sentence),
        subject=subject_for(sentence),
        phase=phase_for(sentence),
        signal_value=value,
        evidence_anchor=anchor,
        confidence=round(confidence, 2),
      )
    )
    if len(signals) >= max_per_document:
      break
  return signals


def extract_signals(conn: sqlite3.Connection, max_per_document: int) -> dict:
  rows = conn.execute(
    """
    SELECT d.id AS document_id, d.source_id, d.normalized_text
    FROM documents d
    JOIN sources s ON s.id = d.source_id
    WHERE d.normalized_text IS NOT NULL
      AND d.fetch_error IS NULL
      AND NOT EXISTS (
        SELECT 1 FROM extracted_signals e WHERE e.document_id = d.id
      )
    ORDER BY d.id ASC
    """
  ).fetchall()
  stats = {"documents": len(rows), "signals": 0}
  timestamp = now()
  for row in rows:
    for signal in extract_signals_from_text(row["normalized_text"], max_per_document):
      conn.execute(
        """
        INSERT INTO extracted_signals
          (source_id, document_id, signal_type, subject, phase, signal_value,
           evidence_anchor, confidence, extractor_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
          row["source_id"],
          row["document_id"],
          signal.signal_type,
          signal.subject,
          signal.phase,
          signal.signal_value,
          signal.evidence_anchor,
          signal.confidence,
          "heuristic-ko-cpa-v1",
          timestamp,
        ),
      )
      stats["signals"] += 1
  conn.commit()
  return stats


RULE_TEMPLATES = {
  "objective_entry_timing": {
    "rule_name": "객관식 전환 조건",
    "condition_text": "기본강의 이후 객관식 관련 신호가 반복되고, 사용자가 개념 이해는 있으나 문제 전환이 늦은 상태",
    "action_text": "신규 강의 확장을 제한하고 객관식 세트와 오답 원인 분류를 주간 처방에 포함한다.",
    "exception_text": "핵심 개념 정답률이 40% 미만이면 객관식 양치기보다 개념 복구를 우선한다."
  },
  "accounting_tax_core_focus": {
    "rule_name": "회계/세법 핵심축 집중",
    "condition_text": "회계와 세법 관련 신호가 같은 문서 또는 여러 사례에서 함께 반복됨",
    "action_text": "회계학과 세법개론을 주간 점수 상승의 중심축으로 두고, 나머지 과목은 유지 블록으로 분리한다.",
    "exception_text": "경제/기업법 과락 위험이 감지되면 최소 방어 시간을 별도 배정한다."
  },
  "past_exam_rotation": {
    "rule_name": "기출 회독 목적 분리",
    "condition_text": "기출 또는 회독 신호가 반복되고 사용자가 회독 목적을 구분하지 못하는 상태",
    "action_text": "1회독은 개념 연결, 2회독은 함정/오답, 3회독은 시간 압박 검증으로 목적을 분리한다.",
    "exception_text": "시험까지 30일 미만이면 고빈도 오답 유형 중심으로 압축한다."
  },
  "tax_verbal_recall": {
    "rule_name": "세법 말문제 회상 블록",
    "condition_text": "세법 말문제, 휘발, 암기 관련 신호가 반복되고 세법 말문제 정답률이 낮은 상태",
    "action_text": "매일 짧은 회상 블록을 배정하고 정답 문장이 아니라 판단 기준 문장으로 압축한다.",
    "exception_text": "계산문제 정답률도 낮으면 법인세/부가세 계산 구조를 먼저 복구한다."
  },
  "time_efficiency_guardrail": {
    "rule_name": "시간 집착 방지",
    "condition_text": "시간, 효율, 시험장 운영 관련 신호가 반복되고 시간 초과율이 높은 상태",
    "action_text": "문제별 통과 기준을 두고 1회전/2회전 풀이를 훈련한다.",
    "exception_text": "개념 공백이 큰 단원은 시간 제한보다 개념 재정렬을 먼저 적용한다."
  }
}


def classify_rule(signal: sqlite3.Row) -> str | None:
  value = signal["signal_value"]
  subject = signal["subject"]
  phase = signal["phase"]
  if "객관식" in value or phase == "objective_entry":
    return "objective_entry_timing"
  if subject == "accounting_tax":
    return "accounting_tax_core_focus"
  if "기출" in value or phase == "rotation":
    return "past_exam_rotation"
  if subject == "tax" and ("말문제" in value or "휘발" in value):
    return "tax_verbal_recall"
  if "시간" in value or phase == "mock_exam":
    return "time_efficiency_guardrail"
  return None


def build_strategy_rules(conn: sqlite3.Connection) -> dict:
  signals = conn.execute(
    "SELECT * FROM extracted_signals WHERE review_status != 'rejected'"
  ).fetchall()
  grouped: dict[str, list[sqlite3.Row]] = {}
  for signal in signals:
    rule_key = classify_rule(signal)
    if rule_key:
      grouped.setdefault(rule_key, []).append(signal)

  timestamp = now()
  touched = 0
  for rule_key, grouped_signals in grouped.items():
    template = RULE_TEMPLATES[rule_key]
    confidence = round(min(0.95, sum(row["confidence"] for row in grouped_signals) / len(grouped_signals)), 2)
    conn.execute(
      """
      INSERT INTO strategy_rules
        (rule_key, rule_name, condition_text, action_text, exception_text,
         source_signal_count, confidence, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(rule_key) DO UPDATE SET
        source_signal_count = excluded.source_signal_count,
        confidence = excluded.confidence,
        updated_at = excluded.updated_at
      """,
      (
        rule_key,
        template["rule_name"],
        template["condition_text"],
        template["action_text"],
        template["exception_text"],
        len(grouped_signals),
        confidence,
        timestamp,
        timestamp,
      ),
    )
    rule_id = conn.execute("SELECT id FROM strategy_rules WHERE rule_key = ?", (rule_key,)).fetchone()["id"]
    for signal in grouped_signals:
      conn.execute(
        "INSERT OR IGNORE INTO rule_signal_links (rule_id, signal_id) VALUES (?, ?)",
        (rule_id, signal["id"]),
      )
    touched += 1
  conn.commit()
  return {"rules": touched, "signals_linked": sum(len(v) for v in grouped.values())}


def stats(conn: sqlite3.Connection) -> dict:
  def scalar(sql: str) -> int:
    return conn.execute(sql).fetchone()[0]

  by_status = {
    row["collection_status"]: row["count"]
    for row in conn.execute(
      "SELECT collection_status, COUNT(*) AS count FROM sources GROUP BY collection_status"
    )
  }
  by_signal = {
    row["signal_type"]: row["count"]
    for row in conn.execute(
      "SELECT signal_type, COUNT(*) AS count FROM extracted_signals GROUP BY signal_type"
    )
  }
  by_data_category = {
    row["data_category"]: row["count"]
    for row in conn.execute(
      "SELECT data_category, COUNT(*) AS count FROM acquisition_targets GROUP BY data_category"
    )
  }
  by_asset_kind = {
    row["asset_kind"]: row["count"]
    for row in conn.execute(
      "SELECT asset_kind, COUNT(*) AS count FROM past_exam_assets GROUP BY asset_kind"
    )
  }
  by_asset_status = {
    row["processing_status"]: row["count"]
    for row in conn.execute(
      "SELECT processing_status, COUNT(*) AS count FROM past_exam_assets GROUP BY processing_status"
    )
  }
  by_learning_status = {
    row["status"]: row["count"]
    for row in conn.execute(
      "SELECT status, COUNT(*) AS count FROM problem_learning_jobs GROUP BY status"
    )
  }
  tutorial_coverage = [
    dict(row)
    for row in conn.execute(
      """
      SELECT exam_id, phase_id, COUNT(*) AS tutorial_count
      FROM subject_tutorials
      GROUP BY exam_id, phase_id
      ORDER BY exam_id, phase_id
      """
    )
  ]
  subject_coverage = [
    dict(row)
    for row in conn.execute(
      """
      SELECT exam_id, phase_id, COUNT(*) AS subject_count
      FROM exam_subjects
      GROUP BY exam_id, phase_id
      ORDER BY exam_id, phase_id
      """
    )
  ]
  rules = [
    dict(row)
    for row in conn.execute(
      """
      SELECT rule_key, rule_name, source_signal_count, confidence, review_status
      FROM strategy_rules
      ORDER BY source_signal_count DESC, confidence DESC
      """
    )
  ]
  return {
    "sources": scalar("SELECT COUNT(*) FROM sources"),
    "documents": scalar("SELECT COUNT(*) FROM documents WHERE fetch_error IS NULL"),
    "signals": scalar("SELECT COUNT(*) FROM extracted_signals"),
    "strategy_rules": scalar("SELECT COUNT(*) FROM strategy_rules"),
    "exam_subjects": scalar("SELECT COUNT(*) FROM exam_subjects"),
    "knowledge_nodes": scalar("SELECT COUNT(*) FROM knowledge_nodes"),
    "acquisition_targets": scalar("SELECT COUNT(*) FROM acquisition_targets"),
    "past_exam_assets": scalar("SELECT COUNT(*) FROM past_exam_assets"),
    "asset_documents": scalar("SELECT COUNT(*) FROM asset_documents WHERE fetch_error IS NULL"),
    "learning_jobs": scalar("SELECT COUNT(*) FROM problem_learning_jobs"),
    "subject_tutorials": scalar("SELECT COUNT(*) FROM subject_tutorials"),
    "tutorial_steps": scalar("SELECT COUNT(*) FROM tutorial_steps"),
    "solution_paths": scalar(
      "SELECT COALESCE(SUM(json_array_length(solution_paths_json)), 0) FROM tutorial_steps"
    ),
    "solution_concept_links": scalar("SELECT COUNT(*) FROM solution_concept_links"),
    "solution_rationales": scalar(
      "SELECT COALESCE(SUM(json_array_length(solution_paths_json)), 0) FROM tutorial_steps"
    ),
    "problem_solution_maps": scalar("SELECT COUNT(*) FROM problem_solution_maps"),
    "problem_solution_paths": scalar("SELECT COUNT(*) FROM problem_solution_paths"),
    "problem_solution_concept_links": scalar("SELECT COUNT(*) FROM problem_solution_concept_links"),
    "problem_choice_eliminations": scalar("SELECT COUNT(*) FROM problem_choice_eliminations"),
    "trainable_after_review_jobs": scalar(
      "SELECT COUNT(*) FROM problem_learning_jobs WHERE status IN ('queued_rights_review', 'queued_generation')"
    ),
    "source_status": by_status,
    "signal_types": by_signal,
    "data_categories": by_data_category,
    "asset_kinds": by_asset_kind,
    "asset_status": by_asset_status,
    "learning_status": by_learning_status,
    "tutorial_coverage": tutorial_coverage,
    "subject_coverage": subject_coverage,
    "rules": rules,
  }


def write_manifest(conn: sqlite3.Connection, manifest_path: Path) -> None:
  manifest_path.parent.mkdir(parents=True, exist_ok=True)
  data = {
    "generated_at": now(),
    "database": str(DEFAULT_DB),
    "stats": stats(conn),
  }
  manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
  public_data = {
    "generated_at": data["generated_at"],
    "stats": data["stats"],
  }
  DEFAULT_PUBLIC_MANIFEST.write_text(json.dumps(public_data, ensure_ascii=False, indent=2), encoding="utf-8")


def record_run(conn: sqlite3.Connection, command: str, started_at: str, run_stats: dict) -> None:
  finished_at = now()
  conn.execute(
    """
    INSERT INTO ingestion_runs (command, started_at, finished_at, stats_json)
    VALUES (?, ?, ?, ?)
    """,
    (command, started_at, finished_at, json.dumps(run_stats, ensure_ascii=False)),
  )
  conn.commit()


def main(argv: Iterable[str]) -> int:
  parser = argparse.ArgumentParser(description="CPA First data accumulation pipeline")
  parser.add_argument("commands", nargs="+", choices=["init", "seed", "ontology", "tutorials", "problem-solutions", "exam-assets", "fetch", "extract", "rules", "stats", "all"])
  parser.add_argument("--db", type=Path, default=DEFAULT_DB)
  parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
  parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
  parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
  parser.add_argument("--exam-assets", type=Path, default=DEFAULT_EXAM_ASSETS)
  parser.add_argument("--tutorials", type=Path, default=DEFAULT_TUTORIALS)
  parser.add_argument("--evaluation", type=Path, default=DEFAULT_EVALUATION)
  parser.add_argument("--limit", type=int)
  parser.add_argument("--max-signals-per-document", type=int, default=20)
  parser.add_argument("--store-text", action="store_true", help="Store normalized source text for internal analysis")
  args = parser.parse_args(list(argv))

  commands = ["init", "seed", "ontology", "tutorials", "problem-solutions", "exam-assets", "fetch", "extract", "rules", "stats"] if "all" in args.commands else args.commands
  conn = connect(args.db)
  started_at = now()
  run_stats: dict[str, object] = {}

  try:
    for command in commands:
      if command == "init":
        init_db(conn)
        run_stats["init"] = "ok"
      elif command == "seed":
        init_db(conn)
        run_stats["seeded_sources"] = seed_sources(conn, args.seed)
      elif command == "ontology":
        init_db(conn)
        run_stats["ontology"] = seed_exam_ontology(conn, args.ontology)
        run_stats["acquisition_targets"] = seed_acquisition_targets(conn, args.targets)
      elif command == "tutorials":
        init_db(conn)
        run_stats["ontology_for_tutorials"] = seed_exam_ontology(conn, args.ontology)
        run_stats["tutorials"] = seed_subject_tutorials(conn, args.tutorials)
      elif command == "problem-solutions":
        init_db(conn)
        run_stats["ontology_for_problem_solutions"] = seed_exam_ontology(conn, args.ontology)
        run_stats["tutorials_for_problem_solutions"] = seed_subject_tutorials(conn, args.tutorials)
        run_stats["problem_solutions"] = seed_problem_solution_maps(conn, args.evaluation)
      elif command == "exam-assets":
        init_db(conn)
        run_stats["exam_assets"] = seed_and_fetch_past_exam_assets(conn, args.exam_assets, args.limit)
      elif command == "fetch":
        init_db(conn)
        run_stats["fetch"] = fetch_sources(conn, args.limit, args.store_text)
      elif command == "extract":
        init_db(conn)
        run_stats["extract"] = extract_signals(conn, args.max_signals_per_document)
      elif command == "rules":
        init_db(conn)
        run_stats["rules"] = build_strategy_rules(conn)
      elif command == "stats":
        init_db(conn)
        run_stats["stats"] = stats(conn)
    write_manifest(conn, DEFAULT_MANIFEST)
    record_run(conn, " ".join(commands), started_at, run_stats)
    print(json.dumps(run_stats, ensure_ascii=False, indent=2))
    return 0
  finally:
    conn.close()


if __name__ == "__main__":
  raise SystemExit(main(sys.argv[1:]))
