"""
NoteAI 用户记忆系统 — 纯 SQLite，替代外部 mem0 服务。

记忆分四类：
  style       写作风格偏好（如"接地气"、"少表情"）
  preference  内容偏好（如"短正文"、"多步骤"）
  achievement 成就里程碑（如"首次突破70分"）
  context     对话上下文摘要（最近3次生成的关键决策）

注入策略：按 importance 降序，取前 N 条拼成 system prompt 片段。
"""
import json
import math
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import db
import content_retention

_MAX_CONTEXT_MEMORIES = 3   # 最多注入几条上下文记忆
_MAX_STYLE_MEMORIES   = 5   # 最多注入几条风格/偏好记忆
_DECAY_ON_ACCESS      = 0.98  # 每次被注入时轻微衰减（让旧记忆逐渐淡出）
PREFERENCE_KEYS = frozenset({'tone', 'emoji', 'title_length', 'title_style', 'body_length'})
PREFERENCE_DOMAINS = frozenset({'美食', '旅行', '穿搭', '美妆', '家居', '健身', '母婴'})
_PREFERENCE_SCHEMA = 'noteai.preference.v1'


def extract_explicit_preferences(message: str, *, domain: str | None = None) -> list[dict]:
    """Bounded explicit user statements only; no model or draft inference."""
    if not isinstance(message, str) or len(message) > 4000:
        return []
    found = {}
    for clause in re.split(r'[。；;！!\n]', message):
        clause = clause.strip()
        if not clause or len(clause) > 240 or re.search(
            r'[？?]|这次|本次|这篇|这一篇|当前稿|暂时|仅这|不要记|不用记|别记|不需要记|无需记|'
            r'不是|并非|不代表|并不|不是我|引用|转述|示例|例如|假如|如果|'
            r'(?:客户|朋友|别人|他|她|模型|AI|专家|系统).{0,12}(?:说|建议|认为|觉得)|[“”「」『』"\']', clause, re.I):
            continue
        if not re.search(r'记住|记下|以后|今后|长期|默认|我(?:的笔记|的文案)?(?:一直|通常|更|比较)?(?:喜欢|不喜欢|偏好|习惯)', clause):
            continue
        scopes = {name for name in PREFERENCE_DOMAINS if name in clause}
        if len(scopes) > 1:
            continue
        scope = next(iter(scopes)) if scopes else None
        if re.search(r'这个(?:行业|领域)|本(?:行业|领域)', clause):
            if domain not in PREFERENCE_DOMAINS:
                continue
            scope = domain
        # Unknown explicit industry scopes must not silently become global.
        if not scope:
            scope_text = re.sub(r'请记住|请记下|记住|记下|以后|今后|长期|默认|我的|这个|本|关于|针对|写|做', '', clause)
            if re.search(r'[\u4e00-\u9fff]{1,8}(?:领域|行业|类笔记|笔记)', scope_text):
                continue
        patterns = (
            ('emoji', '少用表情', r'(?:少用|少放|少点|不用|不要|不带|不加|不喜欢|避免)(?:使用|添加|带)?(?:太多)?(?:表情|emoji)'),
            ('emoji', '多用表情', r'(?:多用|多放|多点|多加)(?:一些|一点)?(?:表情|emoji)'),
            ('title_style', '陈述句标题', r'不(?:用|要|喜欢)(?:用)?疑问句|(?:标题|题目).{0,5}(?:陈述句|不用问句)'),
            ('title_style', '疑问句标题', r'(?:标题|题目).{0,5}(?:用|喜欢|偏好)疑问句|喜欢疑问句标题'),
            ('title_length', '更短标题', r'(?:标题|题目).{0,5}(?:短|简短|精简)|(?:短|简短)标题'),
            ('title_length', '信息更完整的标题', r'(?:标题|题目).{0,5}(?:完整|详细|长一点)'),
            ('body_length', '更短正文', r'(?:正文|文案).{0,5}(?:短|精简|简洁)|(?:短|简短)正文'),
            ('body_length', '信息更完整的正文', r'(?:正文|文案).{0,5}(?:完整|详细|长一点)'),
            ('tone', '自然口语风格', r'(?:语气|风格|表达|文案).{0,5}(?:自然|口语|接地气)|喜欢(?:自然|口语|接地气)'),
        )
        per_key, excerpts = {}, {}
        for key, value, pattern in patterns:
            for match in re.finditer(pattern, clause, re.I):
                # Do not turn a negated positive pattern into a preference.
                # Explicit negative forms (e.g. 不用表情) start at the 不 itself.
                prefix = clause[:match.start()]
                if re.search(r'(?:不|不要|不用|不喜欢|不想|不希望|避免)(?:用|使用|写|写成|采用|太|更)?$', prefix):
                    continue
                if re.search(r'不|不要|不用|不喜欢', match.group()) and not (key == 'emoji' and value == '少用表情' or key == 'title_style' and value == '陈述句标题'):
                    continue
                per_key.setdefault(key, set()).add(value)
                # Keep just the preference's own comma clause, not unrelated
                # personal details appended elsewhere in the same sentence.
                left = max(clause.rfind('，', 0, match.start()), clause.rfind(',', 0, match.start())) + 1
                ends = [end for sep in ('，', ',') if (end := clause.find(sep, match.end())) >= 0]
                excerpts[(key, value)] = clause[left:min(ends) if ends else len(clause)].strip()
        for key, values in per_key.items():
            if len(values) == 1:
                value = next(iter(values))
                found[(scope, key)] = dict(key=key, value=value, domain=scope, source_text=excerpts[(key, value)])
    return list(found.values())


def _preference(content):
    """Read typed explicit records and the original key:value representation."""
    if not isinstance(content, str):
        return None
    if content.lstrip().startswith('{'):
        try:
            value = json.loads(content)
            if (not isinstance(value, dict) or set(value) != {'schema','key','value','domain','source','source_text','source_note_id'}
                or value['schema'] != _PREFERENCE_SCHEMA or value['source'] != 'explicit_user'
                or value['key'] not in PREFERENCE_KEYS or not isinstance(value['value'], str)
                or not 1 <= len(value['value']) <= 160
                or value['domain'] is not None and value['domain'] not in PREFERENCE_DOMAINS
                or not isinstance(value['source_text'], str) or not 1 <= len(value['source_text']) <= 240
                or value['source_note_id'] is not None and not isinstance(value['source_note_id'], str)):
                return None
            return value
        except (ValueError, TypeError):
            return None
    key, sep, value = content.partition(':')
    if sep and key in PREFERENCE_KEYS and value:
        return dict(key=key, value=value, domain=None, source='legacy', source_text='', source_note_id=None)
    return None


def _project(row):
    result = dict(row)
    pref = _preference(result.get('content')) if result.get('memory_type') in {'style','preference'} else None
    result.update(preference_key=pref['key'] if pref else None, domain=pref['domain'] if pref else None,
                  source=pref['source'] if pref else 'legacy', editable=pref is not None,
                  deletable=result.get('memory_type') in {'style','preference'})
    if pref:
        result['content'] = pref['key'] + ':' + pref['value']
        result['value'] = pref['value']
        result['source_text'] = pref['source_text']
    return result


def _preference_rows(storage, user_id):
    return storage.fetchall("SELECT * FROM user_memories WHERE user_id=? AND memory_type IN ('style','preference') ORDER BY updated_at DESC,id", (user_id,))


def _invalidate_session_preference(storage, user_id, key):
    # Persisted sessions are projections, never the authority for a deleted key.
    rows = storage.fetchall('SELECT id,user_prefs_json FROM chat_sessions WHERE user_id=?', (user_id,))
    for row in rows:
        try:
            prefs = json.loads(row['user_prefs_json'] or '{}')
        except (ValueError, TypeError):
            continue
        if isinstance(prefs, dict) and key in prefs:
            prefs.pop(key)
            storage.execute('UPDATE chat_sessions SET user_prefs_json=? WHERE id=? AND user_id=?',
                            (json.dumps(prefs, ensure_ascii=False), row['id'], user_id))


def _write_preference(storage, user_id, value, *, memory_id=None):
    key, scope = value['key'], value['domain']
    matches = [row for row in _preference_rows(storage, user_id)
               if (pref := _preference(row['content'])) and (pref['key'], pref['domain']) == (key, scope)]
    mid = memory_id or (matches[0]['id'] if matches else str(uuid.uuid4()))
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    now = _now()
    if any(row['id'] == mid for row in matches):
        storage.execute('UPDATE user_memories SET content=?,importance=?,updated_at=? WHERE id=? AND user_id=?',
                        (raw, 0.8, now, mid, user_id))
    else:
        _add_memory_with_storage(storage, user_id, 'style', raw, importance=0.8, memory_id=mid)
    for row in matches:
        if row['id'] != mid:
            storage.execute('DELETE FROM user_memories WHERE id=? AND user_id=?', (row['id'], user_id))
    if scope is None:
        storage.execute('INSERT INTO user_learn(user_id,pref_key,pref_value,confidence,update_count,updated_at) '
            'VALUES(?,?,?,0.8,1,?) ON CONFLICT(user_id,pref_key) DO UPDATE SET pref_value=excluded.pref_value,'
            'confidence=excluded.confidence,update_count=user_learn.update_count+1,updated_at=excluded.updated_at',
            (user_id, key, value['value'], now))
    _invalidate_session_preference(storage, user_id, key)
    return _project(storage.fetchone('SELECT * FROM user_memories WHERE id=? AND user_id=?', (mid, user_id)))


def save_explicit_preferences(user_id, preferences, *, source_note_id=None):
    if not isinstance(preferences, list) or len(preferences) > 10:
        raise ValueError('invalid preference list')
    values = []
    for item in preferences:
        if (not isinstance(item, dict) or set(item) != {'key','value','domain','source_text'}
            or item['key'] not in PREFERENCE_KEYS or item['domain'] is not None and item['domain'] not in PREFERENCE_DOMAINS
            or not isinstance(item['value'], str) or not 1 <= len(item['value'].strip()) <= 160
            or not isinstance(item['source_text'], str) or not 1 <= len(item['source_text']) <= 240):
            raise ValueError('invalid explicit preference')
        values.append(dict(item, value=item['value'].strip(), schema=_PREFERENCE_SCHEMA,
                           source='explicit_user', source_note_id=source_note_id))
    if not values:
        return []
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        if source_note_id and not tx.fetchone('SELECT id FROM notes WHERE id=? AND user_id=?', (source_note_id, user_id)):
            raise ValueError('preference source not owned')
        # Long-term preference survives the source note's archive expiry; only
        # its non-content provenance ID is stored, never that note's body.
        return [_write_preference(tx, user_id, value) for value in values]


def update_preference(user_id, memory_id, *, value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 160:
        raise ValueError('invalid preference value')
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        row = tx.fetchone("SELECT * FROM user_memories WHERE id=? AND user_id=? AND memory_type IN ('style','preference')", (memory_id, user_id))
        pref = _preference(row['content']) if row else None
        if not pref:
            return None
        pref.update(schema=_PREFERENCE_SCHEMA, source='explicit_user', value=value.strip(), source_text=value.strip())
        return _write_preference(tx, user_id, pref, memory_id=memory_id)


def delete_preference(user_id, memory_id):
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        row = tx.fetchone("SELECT * FROM user_memories WHERE id=? AND user_id=? AND memory_type IN ('style','preference')", (memory_id, user_id))
        if not row:
            return False
        pref = _preference(row['content'])
        ids = [memory_id]
        if pref:
            ids = [other['id'] for other in _preference_rows(tx, user_id)
                   if (p := _preference(other['content'])) and (p['key'], p['domain']) == (pref['key'], pref['domain'])]
            if pref['domain'] is None:
                tx.execute('DELETE FROM user_learn WHERE user_id=? AND pref_key=?', (user_id, pref['key']))
            _invalidate_session_preference(tx, user_id, pref['key'])
        for mid in ids:
            tx.execute('DELETE FROM user_memories WHERE id=? AND user_id=?', (mid, user_id))
        return True


def read_preferences(user_id, *, domain=None):
    """Authoritative preferences; a known domain overrides only its own keys."""
    with db.transaction() as tx:
        rows = _preference_rows(tx, user_id)
        prefs = {row['pref_key']: row['pref_value'] for row in tx.fetchall(
            'SELECT pref_key,pref_value FROM user_learn WHERE user_id=?', (user_id,)) if row['pref_key'] in PREFERENCE_KEYS}
    for scope in (None, domain) if domain in PREFERENCE_DOMAINS else (None,):
        seen = set()
        for row in rows:
            value = _preference(row['content'])
            if value and value['domain'] == scope and value['key'] not in seen:
                prefs[value['key']] = value['value']; seen.add(value['key'])
    return prefs


def read_legacy_preference_summary(user_id):
    """Expose old single-store facts without a synthetic editable memory ID."""
    with db.transaction() as tx:
        represented = {pref['key'] for row in _preference_rows(tx, user_id)
                       if (pref := _preference(row['content'])) and pref['domain'] is None}
        rows = tx.fetchall('SELECT pref_key,pref_value,confidence,update_count,updated_at '
                           'FROM user_learn WHERE user_id=? ORDER BY pref_key', (user_id,))
    return [dict(preference_key=row['pref_key'], value=row['pref_value'], domain=None,
                 source='legacy_user_learn', editable=False, deletable=False,
                 updated_at=row['updated_at'], confidence=row['confidence'], update_count=row['update_count'])
            for row in rows if row['pref_key'] in PREFERENCE_KEYS and row['pref_key'] not in represented]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─────────────────────────────────────────────────────────────
# 写入
# ─────────────────────────────────────────────────────────────

def _add_memory_with_storage(
    storage,
    user_id: str,
    memory_type: str,
    content: str,
    importance: float = 0.6,
    source_note_id: str | None = None,
    memory_id: str | None = None,
    recorded_at: str | None = None,
) -> str:
    mid = memory_id or str(uuid.uuid4())
    now = recorded_at or _now()
    storage.execute(
        "INSERT INTO user_memories("
        "id,user_id,memory_type,content,importance,source_note_id,created_at,updated_at"
        ") VALUES(?,?,?,?,?,?,?,?)",
        (mid, user_id, memory_type, content, importance, source_note_id, now, now),
    )
    return mid


def add_memory(
    user_id: str,
    memory_type: str,
    content: str,
    importance: float = 0.6,
    source_note_id: str | None = None,
) -> str:
    """添加一条记忆，返回 id。"""
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        return _add_memory_with_storage(
            tx,
            user_id,
            memory_type,
            content,
            importance,
            source_note_id,
        )


def upsert_style(user_id: str, key: str, value: str, importance: float = 0.75) -> None:
    """更新或新增一条风格偏好（以 key 去重）。"""
    content = f"{key}:{value}"
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        row = tx.fetchone(
            "SELECT id FROM user_memories WHERE user_id=? "
            "AND memory_type='style' AND content LIKE ?",
            (user_id, f"{key}:%"),
        )
        now = _now()
        if row:
            tx.execute(
                "UPDATE user_memories SET content=?,importance=?,updated_at=? WHERE id=?",
                (content, min(importance + 0.05, 0.95), now, row["id"]),
            )
        else:
            _add_memory_with_storage(tx, user_id, "style", content, importance)


def record_achievement(user_id: str, text: str) -> None:
    """记录一次成就（不去重，每次都写）。"""
    add_memory(user_id, "achievement", text, importance=0.9)


def add_context(
    user_id: str,
    summary: str,
    *,
    source_note_id: str | None = None,
) -> None:
    """追加一条上下文记忆，并自动清理超出限制的旧记录。"""
    with db.transaction(write=True) as tx:
        content_retention.assert_user_writable_with_storage(tx, user_id)
        _add_memory_with_storage(
            tx,
            user_id,
            "context",
            summary,
            importance=0.5,
            source_note_id=source_note_id,
        )
        # 保留最新 _MAX_CONTEXT_MEMORIES*2 条，删除多余旧条
        rows = tx.fetchall(
            "SELECT id FROM user_memories WHERE user_id=? AND memory_type='context'"
            " ORDER BY created_at DESC",
            (user_id,),
        )
        for row in rows[_MAX_CONTEXT_MEMORIES * 2 :]:
            tx.execute("DELETE FROM user_memories WHERE id=?", (row["id"],))


# ─────────────────────────────────────────────────────────────
# 读取 & 注入
# ─────────────────────────────────────────────────────────────

def recall(user_id: str, memory_type: Optional[str] = None, limit: int = 10) -> list[dict]:
    """查询用户记忆，按 importance 降序。"""
    if memory_type:
        rows = db.fetchall(
            "SELECT * FROM user_memories WHERE user_id=? AND memory_type=?"
            " ORDER BY importance DESC LIMIT ?",
            (user_id, memory_type, limit),
        )
    else:
        rows = db.fetchall(
            "SELECT * FROM user_memories WHERE user_id=?"
            " ORDER BY importance DESC LIMIT ?",
            (user_id, limit),
        )
    return [_project(r) for r in rows]


def build_memory_prompt(user_id: str, *, domain: str | None = None) -> str:
    """
    构建注入到 system prompt 的记忆片段。
    返回空字符串表示无记忆（匿名用户）。
    """
    if not user_id:
        return ""

    try:
        with db.transaction(write=True) as tx:
            content_retention.assert_user_writable_with_storage(tx, user_id)
            candidates = tx.fetchall(
                "SELECT id,content FROM user_memories WHERE user_id=? "
                "AND memory_type IN ('style','preference')"
                " ORDER BY importance DESC,updated_at DESC,id",
                (user_id,),
            )
            scoped_keys = {pref['key'] for row in candidates
                           if (pref := _preference(row['content'])) and domain in PREFERENCE_DOMAINS and pref['domain'] == domain}
            style_rows, seen = [], set()
            for row in candidates:
                pref = _preference(row['content'])
                if pref:
                    if pref['domain'] not in (None, domain) or pref['key'] in seen or (pref['domain'] is None and pref['key'] in scoped_keys):
                        continue
                    seen.add(pref['key'])
                    style_rows.append(dict(id=row['id'], content=pref['key']+':'+pref['value']))
                elif not str(row['content']).lstrip().startswith('{'):
                    style_rows.append(dict(row))  # Original untyped history remains labeled as history.
            for row in tx.fetchall('SELECT pref_key,pref_value FROM user_learn WHERE user_id=?', (user_id,)):
                if row['pref_key'] in PREFERENCE_KEYS and row['pref_key'] not in seen:
                    style_rows.append(dict(id=None,content=row['pref_key']+':'+row['pref_value']))
            style_rows = style_rows[:_MAX_STYLE_MEMORIES]
            # General writing preferences remain shared. Historical task content
            # must be tied to this user's own note in the requested industry.
            domain_filter = ""
            context_params = [user_id]
            if domain:
                domain_filter = (
                    " AND EXISTS (SELECT 1 FROM notes n WHERE n.id=user_memories.source_note_id"
                    " AND n.user_id=user_memories.user_id AND n.domain=?)"
                )
                context_params.append(domain)
            context_rows = tx.fetchall(
                "SELECT id,content FROM user_memories WHERE user_id=? "
                "AND memory_type='context'" + domain_filter + " ORDER BY created_at DESC LIMIT ?",
                (*context_params, _MAX_CONTEXT_MEMORIES),
            )
            achieve_rows = tx.fetchall(
                "SELECT content FROM user_memories WHERE user_id=? "
                "AND memory_type='achievement' ORDER BY created_at DESC LIMIT 2",
                (user_id,),
            )
            for row in [*style_rows, *context_rows]:
                if row['id'] is None:
                    continue
                tx.execute(
                    "UPDATE user_memories SET importance=importance*?,"
                    "access_count=access_count+1 WHERE id=?",
                    (_DECAY_ON_ACCESS, row["id"]),
                )
    except ValueError:
        return ""

    parts = []
    if style_rows:
        prefs = "; ".join(r["content"] for r in style_rows)
        parts.append(f"【用户写作偏好】{prefs}")
    if context_rows:
        ctx = "; ".join(r["content"] for r in context_rows)
        parts.append(f"【近期优化记录】{ctx}")
    if achieve_rows:
        ach = "; ".join(r["content"] for r in achieve_rows)
        parts.append(f"【成长里程碑】{ach}")

    return "以下长期偏好仅作默认参考，本次明确要求优先；历史记录不是本次事实。\n" + "\n".join(parts) if parts else ""


# ─────────────────────────────────────────────────────────────
# 从 user_learn 表同步偏好到 user_memories（双写桥接）
# ─────────────────────────────────────────────────────────────

def sync_from_user_learn(user_id: str, prefs: dict) -> None:
    """将 /chat 学习信号写入的 user_learn 偏好同步到 user_memories。"""
    for key, value in prefs.items():
        upsert_style(user_id, key, value)


# ─────────────────────────────────────────────────────────────
# 成就检测
# ─────────────────────────────────────────────────────────────

def check_and_record_achievements(user_id: str, score: float, action: str) -> list[str]:
    """检测里程碑，有新成就则写入并返回成就文本列表。"""
    if not user_id or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
        return []
    with db.transaction(write=True) as tx:
        return check_and_record_achievements_with_storage(tx, user_id, score, action)


def check_and_record_achievements_with_storage(storage, user_id, score, action, *, source_note_id=None, recorded_at=None):
    """Same six milestones, atomically callable with the original growth write."""
    if not user_id or isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or not 0 <= score <= 100:
        return []
    if recorded_at is not None:
        parsed = datetime.fromisoformat(recorded_at.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('achievement clock must include timezone')
    content_retention.assert_user_writable_with_storage(storage, user_id)
    if source_note_id and not storage.fetchone('SELECT id FROM notes WHERE id=? AND user_id=?', (source_note_id,user_id)):
        raise ValueError('achievement source not owned')
    achieved = []
    milestones = [
        (50, "首次评分突破50分"),
        (60, "首次评分突破60分"),
        (65, "首次评分突破65分"),
        (70, "首次评分突破70分 🎉"),
        (75, "首次评分突破75分 🏆"),
        (80, "首次评分突破80分 🌟"),
    ]
    rows = storage.fetchall(
        "SELECT content FROM user_memories WHERE user_id=? "
        "AND memory_type='achievement'",
        (user_id,),
    )
    existing = {r["content"] for r in rows}
    for threshold, text in milestones:
        if score >= threshold and text not in existing:
            _add_memory_with_storage(
                storage,
                user_id,
                "achievement",
                text,
                importance=0.9,
                source_note_id=source_note_id,
                recorded_at=recorded_at,
            )
            achieved.append(text)
    return achieved
