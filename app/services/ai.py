from __future__ import annotations

import hashlib
import re
from collections import Counter
from urllib.parse import quote_plus

from groq import Groq

from ..config import settings
from ..schemas import AnalysisResult, Dimension, GapAction, SearchPreferences, TailorResult


WORD = re.compile(r"(?<![\w])[A-Za-z][A-Za-z0-9+#.-]*(?![\w])")
STOPWORDS = {
    "and", "the", "with", "for", "that", "this", "from", "your", "you", "our", "are", "will", "have",
    "has", "job", "role", "work", "team", "using", "years", "experience", "skills", "required", "preferred",
    "who", "what", "when", "where", "all", "any", "not", "but", "into", "about", "their", "they", "its",
    "hire", "hiring", "build", "requires", "require", "including", "candidate", "position", "opportunity",
    "need", "needs", "engineer", "clear", "strong", "excellent", "responsible", "responsibilities",
}
SECTION_NAMES = {"summary", "experience", "education", "skills", "projects"}
TECH_SKILLS = {
    "python", "java", "javascript", "typescript", "react", "angular", "vue", "node", "fastapi", "django",
    "sql", "postgresql", "mysql", "aws", "azure", "gcp", "docker", "kubernetes", "git", "figma", "excel",
    "tableau", "powerbi", "machine", "learning", "analytics", "product", "management", "salesforce", "agile",
    "c", "c++", "c#", "go", "r", "rust", "redis", "pgvector", "rag", "embeddings", "pytest", "testing",
    "kafka", "graphql", "terraform", "pytorch", "tensorflow", "oauth", "jwt", "vector", "retrieval",
}
ACTION_VERBS = {"led", "built", "created", "improved", "delivered", "managed", "designed", "developed", "launched", "reduced", "increased"}
groq_client = Groq(api_key=settings.groq_api_key, timeout=settings.ai_timeout_seconds, max_retries=2) if settings.groq_api_key else None


def tokens(text: str) -> list[str]:
    normalized = (match.group(0).lower().strip(".") for match in WORD.finditer(text))
    aliases = {"postgres": "postgresql", "postgresql": "postgresql", "reactjs": "react", "nodejs": "node", "k8s": "kubernetes", "golang": "go"}
    return [aliases.get(word, word) for word in normalized if word not in STOPWORDS]


def _sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", text) if len(item.strip()) > 10]


def _score(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _fingerprint(resume_text: str, jd_text: str) -> str:
    normalized = "\n---TARGET---\n".join(" ".join(value.lower().split()) for value in (resume_text, jd_text))
    return hashlib.sha256(normalized.encode()).hexdigest()


def _polish(base_text: str, instruction: str) -> str:
    if groq_client is None:
        return base_text
    try:
        completion = groq_client.chat.completions.create(
            model=settings.groq_model,
            temperature=0.2,
            max_completion_tokens=512,
            messages=[
                {"role": "system", "content": "You polish supplied career-writing drafts. Never add names, employers, dates, numbers, skills, or claims that are not already in the draft. Return only the revised draft."},
                {"role": "user", "content": f"{instruction}\n\nDRAFT:\n{base_text[:5000]}"},
            ],
        )
        candidate = (completion.choices[0].message.content or "").strip()
        base_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?", base_text))
        candidate_numbers = set(re.findall(r"\b\d+(?:\.\d+)?%?", candidate))
        if 20 <= len(candidate) <= 10_000 and candidate_numbers <= base_numbers:
            return candidate
    except Exception:
        pass
    return base_text


def analyze(resume_text: str, jd_text: str) -> AnalysisResult:
    resume_tokens = tokens(resume_text)
    jd_tokens = tokens(jd_text)
    resume_set, jd_set = set(resume_tokens), set(jd_tokens)
    frequencies = Counter(jd_tokens)
    important = [word for word, _ in frequencies.most_common(30)]
    matched = [word for word in important if word in resume_set]
    keyword_score = _score(100 * len(matched) / max(len(important), 1))

    jd_skills = sorted(jd_set & TECH_SKILLS)
    matched_skills = sorted(set(jd_skills) & resume_set)
    skills_score = _score(100 * len(matched_skills) / max(len(jd_skills), 1)) if jd_skills else keyword_score

    jd_actions = jd_set & ACTION_VERBS
    resume_actions = resume_set & ACTION_VERBS
    relevant_actions = [sentence for sentence in _sentences(resume_text) if set(tokens(sentence)) & ACTION_VERBS and set(tokens(sentence)) & jd_set]
    experience_score = _score(100 * min(len(relevant_actions) / 3, 1))

    lower_resume = resume_text.lower()
    found_sections = [name for name in sorted(SECTION_NAMES) if re.search(rf"(?m)^\s*{name}\s*:?\s*$", lower_resume)]
    formatting_score = _score(100 * len(found_sections) / len(SECTION_NAMES))

    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    average_words = sum(len(line.split()) for line in lines) / max(len(lines), 1)
    readability_score = _score(100 - abs(14 - average_words) * 4)

    dimensions = [
        Dimension(key="skills", label="Skills alignment", score=skills_score, definition="Share of explicit job skills found in the resume.", evidence=matched_skills[:8], confidence=None),
        Dimension(key="keywords", label="Keyword coverage", score=keyword_score, definition="Coverage of the 30 most frequent meaningful job terms.", evidence=matched[:8], confidence=None),
        Dimension(key="experience", label="Experience evidence", score=experience_score, definition="Resume sentences containing an action verb and a job term; this does not verify experience.", evidence=[sentence[:500] for sentence in relevant_actions[:8]], confidence=None),
        Dimension(key="formatting", label="Section completeness", score=formatting_score, definition="Presence of standard resume sections; this does not grade visual design.", evidence=found_sections, confidence=None),
        Dimension(key="readability", label="Line readability", score=readability_score, definition="Heuristic based on average words per non-empty line.", evidence=[f"Average words per line: {average_words:.1f}"], confidence=None),
    ]
    weights = {"skills": 0.3, "keywords": 0.25, "experience": 0.25, "formatting": 0.1, "readability": 0.1}
    overall = _score(sum(item.score * weights[item.key] for item in dimensions))

    sentence_lookup = _sentences(jd_text)
    gaps: list[GapAction] = []
    for index, keyword in enumerate(word for word in important if word not in resume_set):
        evidence = next((sentence for sentence in sentence_lookup if re.search(rf"\b{re.escape(keyword)}\b", sentence, re.I)), "")
        related = next((sentence for sentence in _sentences(resume_text) if keyword[:5] in sentence.lower()), None)
        gaps.append(
            GapAction(
                keyword=keyword,
                importance="high" if index < 3 else "medium" if index < 7 else "low",
                action="clarify" if related else "learn",
                jd_evidence=evidence[:500] or f"Repeated requirement: {keyword}",
                resume_evidence=related[:500] if related else None,
                suggestion=("Clarify existing evidence without changing the underlying fact." if related else "Do not add this claim unless you can provide truthful evidence."),
                confidence=None,
            )
        )
        if len(gaps) == 10:
            break

    if overall >= 75:
        verdict = "High text coverage. Review remaining gaps and keep every claim factual."
    elif overall >= 50:
        verdict = "Moderate text coverage. Strengthen verified evidence for the highest-impact requirements."
    else:
        verdict = "Low text coverage. Inspect supporting experience before deciding whether to apply."
    methodology = {
        "label": "Evidence-weighted deterministic match",
        "weights": weights,
        "repeatable": True,
        "limitations": [
            "This is an explainable heuristic, not a prediction from a specific employer ATS.",
            "Scores compare only the supplied resume and job description.",
            "A higher score does not guarantee an interview.",
        ],
    }
    return AnalysisResult(
        score=overall,
        verdict=verdict,
        dimensions=dimensions,
        gap_plan=gaps,
        methodology_version="heuristic-v3",
        input_fingerprint=_fingerprint(resume_text, jd_text),
        methodology=methodology,
    )


def tailor(resume_text: str, jd_text: str, confirmed_facts: list[str]) -> TailorResult:
    # Checkboxes and keyword strings are not evidence of a personal achievement.
    return TailorResult(original=resume_text, tailored=resume_text, added_phrases=[], warnings=[
        "No unsupported keywords were added. Choose reviewed project evidence to propose cited bullets."
    ])


def cover_letter(resume_text: str, jd_text: str, company: str, role: str) -> str:
    analysis = analyze(resume_text, jd_text)
    skills = [item for dimension in analysis.dimensions[:2] for item in dimension.evidence][:3]
    skill_text = ", ".join(skills) or "the experience described in my resume"
    draft = (
        f"Dear Hiring Team,\n\nI am interested in the {role or 'open'} role at {company or 'your organization'}. "
        f"My background includes verified experience relevant to {skill_text}. I would welcome the opportunity to discuss "
        "how that evidence maps to your priorities while learning more about the team.\n\nSincerely,\nCandidate"
    )
    return _polish(draft, "Improve clarity and warmth while keeping the draft under 300 words.")


def interview_questions(resume_text: str, jd_text: str, interview_type: str) -> list[dict]:
    gaps = analyze(resume_text, jd_text).gap_plan
    focus = [gap.keyword for gap in gaps[:3]] or ["the role's core requirements"]
    questions = [
        ("behavioral", "Tell me about a difficult project where you had to influence others. What changed because of your work?"),
        ("behavioral", "Describe a setback, the evidence you used to respond, and what you would do differently."),
        ("technical", f"Walk through a real example that demonstrates {focus[0]}. Explain trade-offs and measurable results."),
        ("technical", f"How would you approach a first 30-day problem involving {focus[min(1, len(focus)-1)]}?"),
        ("mixed", "Which claim in your resume best predicts success in this role, and what evidence supports it?"),
    ]
    selected = [item for item in questions if interview_type == "mixed" or item[0] in {interview_type, "mixed"}]
    return [{"id": index, "type": kind, "question": text} for index, (kind, text) in enumerate(selected)]


def interview_prep(resume_text: str, jd_text: str) -> dict:
    analysis = analyze(resume_text, jd_text)
    strengths = list(dict.fromkeys(evidence for dimension in analysis.dimensions for evidence in dimension.evidence))[:5]
    gaps = [gap.keyword for gap in analysis.gap_plan[:4]]
    return {
        "competencies": [item.label for item in analysis.dimensions[:3]],
        "talking_points": strengths or ["Select one verified achievement from your resume."],
        "risk_areas": gaps or ["No high-priority evidence gaps detected."],
        "questions_to_ask": [
            "What outcomes would define success in the first 90 days?",
            "Which challenge is the team most eager for this hire to solve?",
            "How will this role collaborate with its closest partner teams?",
        ],
        "estimated_minutes": 25,
        "evidence_reminder": "Use only examples and results you can substantiate.",
    }


def score_answer(answer: str, jd_text: str = "", question: str = "") -> dict:
    meaningful = tokens(answer)
    counts = Counter(meaningful)
    repetitive = not meaningful or max(counts.values(), default=0) / max(len(meaningful), 1) > 0.25
    relevant_terms = set(tokens(jd_text + " " + question)) & set(meaningful) - {"situation", "task", "action", "result"}
    personal_action = bool(re.search(r"\bI\s+(?:built|designed|implemented|tested|debugged|profiled|led|chose|measured|reduced)\b", answer, re.I))
    outcome = bool(re.search(r"\b(?:resulted|reduced|improved|learned|resolved|increased|fell)\b", answer, re.I))
    evidence_sentences = [s for s in _sentences(answer) if set(tokens(s)) & relevant_terms][:3]
    score = 0 if repetitive else _score(40 * min(len(relevant_terms) / 4, 1) + 35 * personal_action + 25 * outcome)
    missing = []
    if not relevant_terms:
        missing.append("Connect your example to the question and role.")
    if not personal_action:
        missing.append("Explain your own action and the trade-off you made.")
    if not outcome:
        missing.append("Describe the actual outcome or lesson; numbers are optional.")
    if repetitive:
        missing.insert(0, "The answer is highly repetitive; provide a substantive example.")
    return {
        "score": score,
        "dimensions": {"relevance": 0 if repetitive else round(100 * min(len(relevant_terms) / 4, 1)), "personal_action": 100 if personal_action and not repetitive else 0, "outcome": 100 if outcome and not repetitive else 0},
        "feedback": " ".join(missing) or "Your example includes relevant detail, a personal action and an outcome. Explain the trade-off next.",
        "matched_terms": sorted(relevant_terms)[:8],
        "stronger_answer_outline": "Situation and stakes; your specific action and trade-off; measurable result; lesson relevant to this role.",
        "evidence": evidence_sentences,
        "limitations": "Deterministic practice checklist, not a calibrated interview assessment or fact verification.",
        "follow_up": "What alternative did you consider, and what evidence led you to your decision?",
    }


def outreach_variants(resume_text: str, jd_text: str, name: str, role: str, company: str, cta: str, tone: str = "professional") -> dict:
    analysis = analyze(resume_text, jd_text)
    evidence = [item for dimension in analysis.dimensions[:2] for item in dimension.evidence][:2]
    proof = " and ".join(evidence) or "the relevant experience in my resume"
    greeting = f"Hi {name}," if name else "Hello,"
    opening = {"professional": f"I am contacting you in your role as {role or 'a team contact'}.", "warm": f"I hope your week is going well. I would value your perspective as {role or 'a team contact'}.", "concise": f"A quick question for you as {role or 'a team contact'}."}[tone]
    return {
        "subjects": [f"Interest in opportunities at {company or 'your team'}", f"Candidate with experience in {proof}"],
        "recruiter_email": f"{greeting}\n\n{opening} I am exploring the role at {company or 'your company'}; my resume includes {proof}. Would you be open to {cta}?\n\nBest,\nCandidate",
        "hiring_manager_note": f"{greeting} {opening} My resume includes {proof}. Would you be open to {cta} about {company or 'your team'}?",
        "referral_request": f"{greeting} {opening} I am considering a role at {company or 'your company'}. My resume includes {proof}. Would you be comfortable sharing your perspective or referring me if the fit is relevant?",
        "linkedin_message": f"{greeting} {opening} My resume includes {proof}. Open to {cta} about {company or 'your team'}?"[:300],
        "follow_ups": [
            "Following up in case this was buried. I would still value a brief conversation if the fit is relevant.",
            "One final note: I remain interested, but no response is needed if priorities have changed. Thank you for considering it.",
        ],
        "evidence": evidence,
    }


def discover(resume_text: str, preferences: SearchPreferences) -> list[dict]:
    resume_skills = sorted(set(tokens(resume_text)) & TECH_SKILLS)
    titles = preferences.desired_titles or [
        f"{skill.title()} Specialist" for skill in resume_skills[:3]
    ] or ["Business Analyst", "Project Coordinator", "Operations Associate"]
    excluded = {title.lower() for title in preferences.excluded_titles}
    results = []
    for title in titles:
        if title.lower() in excluded:
            continue
        query_parts = [title, *preferences.locations[:1], *preferences.work_modes[:1]]
        query = quote_plus(" ".join(part for part in query_parts if part))
        overlap = sorted(set(tokens(title)) & set(tokens(resume_text)))
        results.append(
            {
                "title": title,
                "fit_score": None,
                "reason": f"Search suggestion based on resume terms: {', '.join(resume_skills[:4]) or 'review resume evidence'}. No opening has been evaluated.",
                "limitations": "Salary and seniority must be checked on the provider; these are search links, not verified vacancies.",
                "links": {
                    "LinkedIn": f"https://www.linkedin.com/jobs/search/?keywords={query}",
                    "Indeed": f"https://www.indeed.com/jobs?q={query}",
                    "WeWorkRemotely": f"https://weworkremotely.com/remote-jobs/search?term={quote_plus(title)}",
                },
            }
        )
        if len(results) == 10:
            break
    return results
