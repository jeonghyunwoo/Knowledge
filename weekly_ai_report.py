#!/usr/bin/env python3
"""
weekly_ai_report.py
매주 금요일 실행: arXiv 직전 7일 AI 논문 수집 → MD + HTML 생성 → GitHub push

환경변수 필요:
  ANTHROPIC_API_KEY  — Anthropic API 키 (sk-ant-... 또는 ghp_ 형식 아님)
  OPENAI_API_KEY 는 불필요, Anthropic만 사용

설정법:
  setx ANTHROPIC_API_KEY "sk-ant-..."  (PowerShell, 재시작 후 적용)
"""

import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── 경로 설정 ───────────────────────────────────────────────────────────────
OBSIDIAN_KNOWLEDGE = Path(r"C:\Users\User\Documents\Projects\leonard-obsidian\Knowledge")
OBSIDIAN_ROOT      = Path(r"C:\Users\User\Documents\Projects\leonard-obsidian")
GITHUB_REPO        = Path(r"C:\Users\User\Documents\Projects\Knowledge")
GITHUB_PAGES_BASE  = "https://jeonghyunwoo.github.io/Knowledge"
PYTHON_EXE         = r"C:\Users\User\AppData\Local\Python\bin\python.exe"
GIT_NAME           = "jeonghyunwoo"
GIT_EMAIL          = "jeonghyunwoo@gmail.com"
CLAUDE_MODEL       = "claude-sonnet-4-6"
# ────────────────────────────────────────────────────────────────────────────


def ensure_anthropic():
    try:
        import anthropic
        return anthropic
    except ImportError:
        print("  anthropic SDK 설치 중...")
        subprocess.run([PYTHON_EXE, "-m", "pip", "install", "anthropic", "-q"], check=True)
        import anthropic
        return anthropic


# ── 1. arXiv 검색 ───────────────────────────────────────────────────────────

def search_arxiv(query: str, max_results: int = 15, days_back: int = 7) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    params = urllib.parse.urlencode({
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = f"https://export.arxiv.org/api/query?{params}"
    req = urllib.request.Request(url, headers={"User-Agent": "weekly-ai-report/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read()

    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(xml_data)
    papers = []
    for entry in root.findall("a:entry", ns):
        pub_raw = entry.find("a:published", ns).text
        pub_dt  = datetime.fromisoformat(pub_raw.replace("Z", "+00:00"))
        if pub_dt < cutoff:
            continue
        arxiv_id = entry.find("a:id", ns).text.split("/abs/")[-1]
        papers.append({
            "title":    re.sub(r"\s+", " ", entry.find("a:title", ns).text).strip(),
            "arxiv_id": arxiv_id,
            "url":      f"https://arxiv.org/abs/{arxiv_id}",
            "date":     pub_dt.strftime("%Y-%m-%d"),
            "summary":  re.sub(r"\s+", " ", entry.find("a:summary", ns).text).strip()[:600],
        })
    return papers


def collect_papers(days_back: int = 7) -> list[dict]:
    queries = [
        "cat:cs.AI large language model agent reasoning",
        "cat:cs.LG reinforcement learning optimization efficient",
        "cat:cs.CV diffusion model image video generation",
        "cat:cs.CL multimodal benchmark evaluation",
        "cat:cs.AI safety alignment hallucination robustness",
        "cat:cs.LG on-device edge model compression",
    ]
    seen, all_papers = set(), []
    for q in queries:
        try:
            for p in search_arxiv(q, days_back=days_back):
                if p["arxiv_id"] not in seen:
                    seen.add(p["arxiv_id"])
                    all_papers.append(p)
        except Exception as e:
            print(f"  [!] 쿼리 실패 '{q}': {e}")
    return all_papers


# ── 2. Claude 분석 ──────────────────────────────────────────────────────────

def analyse_with_claude(papers: list[dict], today: str, week_start: str) -> dict:
    anthropic = ensure_anthropic()
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY 환경변수가 없습니다.\n"
            "PowerShell에서 실행: setx ANTHROPIC_API_KEY \"sk-ant-...\""
        )
    client = anthropic.Anthropic(api_key=api_key)

    papers_block = "\n\n".join(
        f"[{i+1}] {p['title']}\n"
        f"arXiv: {p['arxiv_id']} ({p['date']})\n"
        f"URL: {p['url']}\n"
        f"요약: {p['summary']}"
        for i, p in enumerate(papers)
    )

    prompt = f"""기간 {week_start} ~ {today} 직전 7일 arXiv 제출 AI 논문들입니다.

{papers_block}

가장 중요하고 다양한 트렌드를 커버하는 10편을 선정해 분석하세요.
JSON만 반환 (마크다운 코드블록 없이):
{{
  "papers": [
    {{
      "num": 1,
      "topic": "트렌드 주제 (한국어, 12자 이내)",
      "title": "논문 영문 제목",
      "arxiv_id": "2606.xxxxx",
      "url": "https://arxiv.org/abs/...",
      "date": "YYYY-MM-DD",
      "summary_ko": "핵심 내용 한국어 2~3문장",
      "use_cases": ["구체적 활용방안1", "활용방안2", "활용방안3"]
    }}
  ],
  "trends": [
    {{"title": "흐름 제목 (10자 이내)", "desc": "설명 1~2문장"}},
    {{"title": "흐름 제목", "desc": "설명"}},
    {{"title": "흐름 제목", "desc": "설명"}},
    {{"title": "흐름 제목", "desc": "설명"}}
  ]
}}"""

    msg = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}]
    )
    text = msg.content[0].text
    start = text.find("{")
    end   = text.rfind("}") + 1
    return json.loads(text[start:end])


# ── 3. 마크다운 렌더링 ──────────────────────────────────────────────────────

def render_md(data: dict, today: str, week_start: str) -> str:
    papers = data["papers"]
    trends = data["trends"]
    lines = [
        f"# AI 최신 트렌드 논문 정리 ({today} 기준)\n",
        f"> 수집일: {today} | 기간: {week_start} ~ {today} | 출처: arXiv\n",
        "## 요약 표\n",
        "| # | 트렌드 주제 | 논문명 | arXiv ID | 구체적 활용방안 |",
        "|---|------------|--------|----------|--------------|",
    ]
    for p in papers:
        use = " / ".join(p["use_cases"][:2])
        lines.append(f"| {p['num']} | {p['topic']} | {p['title']} | [{p['arxiv_id']}]({p['url']}) | {use} |")

    lines.append("\n## 상세 내용\n")
    for p in papers:
        lines += [
            f"### {p['num']}. {p['topic']} — {p['title']}\n",
            f"**arXiv**: [{p['arxiv_id']}]({p['url']}) | {p['date']}\n",
            f"**핵심 내용**: {p['summary_ko']}\n",
            "**구체적 활용방안**",
        ]
        for uc in p["use_cases"]:
            lines.append(f"- {uc}")
        lines.append("")

    lines.append("\n## 주요 흐름 요약\n")
    lines.append("| 흐름 | 내용 |")
    lines.append("|------|------|")
    for t in trends:
        lines.append(f"| **{t['title']}** | {t['desc']} |")

    lines.append(f"\n---\n\n#AI #LLM #arXiv #트렌드 #{today[:4]}")
    return "\n".join(lines)


# ── 4. HTML 렌더링 ──────────────────────────────────────────────────────────

def render_html(data: dict, today: str, week_start: str) -> str:
    papers = data["papers"]
    trends = data["trends"]

    def esc(s):
        return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

    table_rows = "".join(f"""
      <tr>
        <td>{p['num']}</td>
        <td><span class="tag">{esc(p['topic'])}</span></td>
        <td>{esc(p['title'])}</td>
        <td><a href="{esc(p['url'])}" target="_blank">{esc(p['arxiv_id'])}</a></td>
        <td>{esc(p['use_cases'][0])}</td>
      </tr>""" for p in papers)

    cards = "".join(f"""
    <div class="trend-card">
      <div class="trend-card-header">
        <span class="trend-num">{p['num']:02d}</span>
        <span class="trend-topic">{esc(p['topic'])}</span>
      </div>
      <div class="trend-card-body">
        <div class="trend-paper">{esc(p['title'])}</div>
        <ul class="use-list">{''.join(f'<li>{esc(uc)}</li>' for uc in p['use_cases'])}</ul>
        <div class="arxiv-badge"><a href="{esc(p['url'])}" target="_blank">{esc(p['arxiv_id'])}</a></div>
      </div>
    </div>""" for p in papers)

    details = "".join(f"""
  <div class="detail-item">
    <div class="detail-header">
      <span class="detail-num">{p['num']:02d}</span>
      <span class="detail-topic-label">{esc(p['topic'])}</span>
    </div>
    <div class="detail-title">{esc(p['title'])}</div>
    <div class="detail-meta">arXiv <a href="{esc(p['url'])}" target="_blank">{esc(p['arxiv_id'])}</a> — {p['date']}</div>
    <div class="detail-body">
      <div class="sub-label blue">핵심 내용</div>
      <p>{esc(p['summary_ko'])}</p>
      <div class="sub-label green">구체적 활용방안</div>
      <ul class="use-list">{''.join(f'<li>{esc(uc)}</li>' for uc in p['use_cases'])}</ul>
    </div>
  </div>""" for p in papers)

    trend_colors = ["royalblue", "firebrick", "forestgreen", "#c8a000"]
    trend_boxes = "".join(f"""
    <div class="trend-summary-item" style="border-left-color:{trend_colors[i % 4]}">
      <h4>{esc(t['title'])}</h4>
      <p>{esc(t['desc'])}</p>
    </div>""" for i, t in enumerate(trends[:4]))

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>AI 트렌드 논문 — {today}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root{{--bg:#ffffff;--surface:#f5f5f5;--surface2:#ebebeb;--border:#d4d4d4;--text:#111111;--text-muted:#555555;}}
    *{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:var(--bg);color:var(--text);font-family:'IBM Plex Sans KR','IBM Plex Sans',sans-serif;font-size:15px;line-height:1.7;padding:2.5rem 1.5rem 5rem;max-width:980px;margin:0 auto;}}
    .page-header{{border-bottom:2px solid var(--text);padding-bottom:1rem;margin-bottom:2rem;}}
    .page-header h1{{font-size:1.6rem;font-weight:700;letter-spacing:-0.02em;}}
    .page-header .meta{{font-size:0.82rem;color:var(--text-muted);margin-top:0.3rem;}}
    .page-header .meta span{{margin-right:1.2rem;}}
    .section-title{{font-size:1.05rem;font-weight:700;color:royalblue;border-left:4px solid royalblue;padding-left:0.7rem;margin:2.5rem 0 1rem;}}
    .summary-table{{width:100%;border-collapse:collapse;font-size:0.88rem;}}
    .summary-table thead tr{{background:var(--text);color:var(--bg);}}
    .summary-table thead th{{padding:0.6rem 0.8rem;text-align:left;font-weight:600;}}
    .summary-table tbody tr:nth-child(odd){{background:var(--surface);}}
    .summary-table tbody tr:hover{{background:#e8eeff;}}
    .summary-table td{{padding:0.55rem 0.8rem;border-bottom:1px solid var(--border);vertical-align:top;}}
    .summary-table td:first-child{{font-weight:700;color:var(--text-muted);text-align:center;width:2rem;}}
    .tag{{display:inline-block;background:#e8eeff;color:royalblue;border-radius:4px;font-size:0.78rem;padding:0.1rem 0.45rem;font-weight:600;white-space:nowrap;}}
    .summary-table a{{color:royalblue;text-decoration:none;font-family:'IBM Plex Mono',monospace;font-size:0.8rem;}}
    .summary-table a:hover{{text-decoration:underline;}}
    .trend-grid{{display:grid;grid-template-columns:1fr 1fr;gap:1.1rem;margin-bottom:0.5rem;}}
    .trend-card{{border:1px solid var(--border);border-radius:6px;overflow:hidden;}}
    .trend-card-header{{background:var(--surface2);padding:0.65rem 1rem;display:flex;align-items:flex-start;gap:0.6rem;}}
    .trend-num{{font-size:0.78rem;font-weight:700;color:royalblue;min-width:1.4rem;}}
    .trend-topic{{font-size:0.82rem;font-weight:700;color:var(--text-muted);}}
    .trend-card-body{{padding:0.8rem 1rem;}}
    .trend-paper{{font-size:0.9rem;font-weight:600;margin-bottom:0.5rem;line-height:1.4;}}
    .arxiv-badge{{display:inline-block;font-family:'IBM Plex Mono',monospace;font-size:0.75rem;background:#fff8e0;border:1px solid #e0c800;color:#7a6000;border-radius:3px;padding:0.05rem 0.4rem;margin-top:0.5rem;}}
    .arxiv-badge a{{color:inherit;text-decoration:none;}}
    hr.sd{{border:none;border-top:1px solid var(--border);margin:3rem 0 2.5rem;}}
    .detail-item{{margin-bottom:2.8rem;}}
    .detail-header{{display:flex;align-items:baseline;gap:0.8rem;margin-bottom:0.8rem;flex-wrap:wrap;}}
    .detail-num{{font-size:0.78rem;font-weight:700;color:#fff;background:royalblue;border-radius:3px;padding:0.1rem 0.45rem;}}
    .detail-topic-label{{font-size:0.78rem;color:var(--text-muted);font-weight:500;background:var(--surface2);border-radius:3px;padding:0.1rem 0.5rem;}}
    .detail-title{{font-size:1.05rem;font-weight:700;line-height:1.4;margin-bottom:0.6rem;}}
    .detail-meta{{font-size:0.78rem;color:var(--text-muted);margin-bottom:0.9rem;font-family:'IBM Plex Mono',monospace;}}
    .detail-meta a{{color:royalblue;text-decoration:none;}}
    .sub-label{{font-size:0.8rem;font-weight:700;text-transform:uppercase;letter-spacing:0.06em;margin:0.9rem 0 0.35rem;}}
    .sub-label.blue{{color:royalblue;}}.sub-label.green{{color:forestgreen;}}
    .detail-body p{{font-size:0.88rem;margin-bottom:0.4rem;}}
    .use-list{{list-style:none;padding:0;margin:0;}}
    .use-list li{{font-size:0.88rem;padding:0.25rem 0 0.25rem 1.1rem;position:relative;}}
    .use-list li::before{{content:"▸";position:absolute;left:0;color:forestgreen;font-size:0.8rem;}}
    .trend-summary-grid{{display:grid;grid-template-columns:1fr 1fr;gap:0.9rem;}}
    .trend-summary-item{{background:var(--surface);border-left:4px solid royalblue;border-radius:0 5px 5px 0;padding:0.7rem 0.9rem;}}
    .trend-summary-item h4{{font-size:0.85rem;font-weight:700;margin-bottom:0.3rem;}}
    .trend-summary-item p{{font-size:0.82rem;color:var(--text-muted);}}
    .page-footer{{margin-top:4rem;padding-top:1.2rem;border-top:1px solid var(--border);font-size:0.78rem;color:var(--text-muted);}}
    .page-footer a{{color:royalblue;text-decoration:none;}}
  </style>
</head>
<body>
  <header class="page-header">
    <h1>AI 최신 트렌드 논문 정리</h1>
    <div class="meta">
      <span>수집일 <strong>{today}</strong></span>
      <span>기간 <strong>{week_start} ~ {today}</strong></span>
      <span>출처 <strong>arXiv — cs.AI · cs.LG · cs.CV · cs.CL</strong></span>
    </div>
  </header>

  <div class="section-title">요약 표</div>
  <table class="summary-table">
    <thead><tr><th>#</th><th>트렌드 주제</th><th>논문명</th><th>arXiv</th><th>대표 활용방안</th></tr></thead>
    <tbody>{table_rows}</tbody>
  </table>

  <div class="section-title">트렌드 한눈에 보기</div>
  <div class="trend-grid">{cards}</div>

  <hr class="sd">

  <div class="section-title">논문별 상세 내용</div>
  {details}

  <hr class="sd">

  <div class="section-title">주요 흐름 요약</div>
  <div class="trend-summary-grid">{trend_boxes}</div>

  <footer class="page-footer">
    출처: arXiv cs.AI · cs.LG · cs.CV · cs.CL | 수집일 {today} |
    <a href="{GITHUB_PAGES_BASE}/ai-trends-{today}.html">영구 링크</a>
  </footer>
</body>
</html>"""


# ── 5. README 업데이트 ──────────────────────────────────────────────────────

def update_readme(today: str):
    readme = GITHUB_REPO / "README.md"
    content = readme.read_text(encoding="utf-8")
    new_row = (
        f"| [ai-trends-{today}.html]"
        f"({GITHUB_PAGES_BASE}/ai-trends-{today}.html)"
        f" | arXiv AI 트렌드 논문 10선 — {today} | {today} |"
    )
    if new_row in content:
        return
    # 테이블 마지막 항목 아래에 삽입
    lines = content.splitlines()
    insert_idx = None
    for i, line in enumerate(lines):
        if line.startswith("| [ai-trends-"):
            insert_idx = i
    if insert_idx is not None:
        lines.insert(insert_idx + 1, new_row)
    else:
        lines.append(new_row)
    readme.write_text("\n".join(lines), encoding="utf-8")


# ── 6. Git push ─────────────────────────────────────────────────────────────

def git_push(today: str) -> bool:
    def run(*args):
        r = subprocess.run(list(args), cwd=GITHUB_REPO, capture_output=True, text=True)
        if r.returncode != 0 and r.stderr:
            print(f"  [git] {' '.join(args[-2:])}: {r.stderr.strip()[:120]}")
        return r

    run("git", "config", "user.name", GIT_NAME)
    run("git", "config", "user.email", GIT_EMAIL)
    run("git", "add", ".")
    run("git", "commit", "-m", f"weekly: AI 트렌드 논문 리포트 {today}")
    result = run("git", "push", "origin", "main")
    return result.returncode == 0


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    today      = datetime.now().strftime("%Y-%m-%d")
    week_start = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    html_name  = f"ai-trends-{today}.html"
    md_name    = f"AI_트렌드_{datetime.now().strftime('%Y년%m월%d일')}.md"

    print(f"\n{'='*50}")
    print(f"  Weekly AI Report: {week_start} ~ {today}")
    print(f"{'='*50}\n")

    # 1. arXiv 검색
    print("[ 1/5 ] arXiv 검색 중...")
    papers = collect_papers(days_back=7)
    if len(papers) < 5:
        print("        논문 부족 — 10일로 확장")
        papers = collect_papers(days_back=10)
    print(f"        {len(papers)}편 수집")

    # 2. Claude 분석
    print("[ 2/5 ] Claude API 분석 중...")
    data = analyse_with_claude(papers, today, week_start)
    print(f"        {len(data['papers'])}편 선정")

    # 3. 파일 생성
    print("[ 3/5 ] 파일 생성 중...")
    md_content   = render_md(data, today, week_start)
    html_content = render_html(data, today, week_start)

    (OBSIDIAN_KNOWLEDGE / md_name).write_text(md_content, encoding="utf-8")
    (OBSIDIAN_ROOT / html_name).write_text(html_content, encoding="utf-8")
    (GITHUB_REPO / html_name).write_text(html_content, encoding="utf-8")
    print(f"        {md_name}")
    print(f"        {html_name}")

    # 4. README 업데이트
    print("[ 4/5 ] README 업데이트 중...")
    update_readme(today)

    # 5. Git push
    print("[ 5/5 ] GitHub push 중...")
    ok = git_push(today)

    print(f"\n{'='*50}")
    print("  완료")
    print(f"  Pages: {GITHUB_PAGES_BASE}/{html_name}")
    if not ok:
        print("  [!] Push 실패 — git 상태 확인 필요")
        return 1
    print(f"{'='*50}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
