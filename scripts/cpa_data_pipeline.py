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
DEFAULT_MANIFEST = ROOT / "data" / "warehouse" / "manifest.json"
DEFAULT_PUBLIC_MANIFEST = ROOT / "prototype" / "data_manifest.json"
USER_AGENT = "CPAFirstResearchBot/0.1 (+local research prototype)"


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


def seed_past_exam_assets(conn: sqlite3.Connection, assets_path: Path) -> int:
  timestamp = now()
  rows = 0
  with assets_path.open("r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
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
          row["training_policy"],
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

    if row["training_policy"] in {"train_allowed_after_review", "train_after_rights_review"}:
      status = "queued_rights_review"
      blocker = "rights_review_required_before_training"
    else:
      status = "blocked"
      blocker = "permission_or_license_required_before_training"

    if row["source_type"] == "internal" and row["training_policy"] == "train_allowed_after_review":
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
        row["training_policy"],
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
    "trainable_after_review_jobs": scalar(
      "SELECT COUNT(*) FROM problem_learning_jobs WHERE status IN ('queued_rights_review', 'queued_generation')"
    ),
    "source_status": by_status,
    "signal_types": by_signal,
    "data_categories": by_data_category,
    "asset_kinds": by_asset_kind,
    "asset_status": by_asset_status,
    "learning_status": by_learning_status,
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
  parser.add_argument("commands", nargs="+", choices=["init", "seed", "ontology", "exam-assets", "fetch", "extract", "rules", "stats", "all"])
  parser.add_argument("--db", type=Path, default=DEFAULT_DB)
  parser.add_argument("--seed", type=Path, default=DEFAULT_SEED)
  parser.add_argument("--ontology", type=Path, default=DEFAULT_ONTOLOGY)
  parser.add_argument("--targets", type=Path, default=DEFAULT_TARGETS)
  parser.add_argument("--exam-assets", type=Path, default=DEFAULT_EXAM_ASSETS)
  parser.add_argument("--limit", type=int)
  parser.add_argument("--max-signals-per-document", type=int, default=20)
  parser.add_argument("--store-text", action="store_true", help="Store normalized source text for internal analysis")
  args = parser.parse_args(list(argv))

  commands = ["init", "seed", "ontology", "exam-assets", "fetch", "extract", "rules", "stats"] if "all" in args.commands else args.commands
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
