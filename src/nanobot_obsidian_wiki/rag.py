"""Chroma-backed RAG support for schema-driven Obsidian wiki vaults.

The engine stores chunk embeddings in a persistent Chroma collection under
``wiki/.nanobot/chroma``.  A deterministic local hashing embedder is used by
default so the project can run offline; the storage/search path is still a real
vector database and can later swap to a neural embedding provider.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Literal

from nanobot_obsidian_wiki.config import WikiAgentConfig
from nanobot_obsidian_wiki.obsidian_cli import ObsidianCLIAdapter
from nanobot_obsidian_wiki.utils.frontmatter import extract_wikilinks, parse_frontmatter
from nanobot_obsidian_wiki.vault_guard import VaultGuard

RagScope = Literal["wiki", "raw", "all"]

_SUPPORTED_SUFFIXES = {".md", ".txt"}
_DEFAULT_MAX_CHARS = 1400
_DEFAULT_OVERLAP_CHARS = 160
_INDEX_VERSION = 1
_EMBEDDING_DIM = 384
_COLLECTION_NAME = "nanobot_obsidian_rag"


@dataclass(frozen=True, slots=True)
class RagChunk:
    """One retrievable evidence chunk."""

    chunk_id: str
    path: str
    heading: str
    text: str
    metadata: dict[str, object] = field(default_factory=dict)
    tokens: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RagSearchResult:
    """Ranked retrieval result returned to the Agent."""

    chunk: RagChunk
    score: float
    snippet: str


@dataclass(frozen=True, slots=True)
class RagIndex:
    """Summary of the current Chroma-backed RAG index."""

    version: int
    created_at: str
    scopes: list[str]
    files: dict[str, str]
    chunks: list[RagChunk]


@dataclass(frozen=True, slots=True)
class RagSyncResult:
    """Result of synchronizing the persistent Chroma index."""

    status: str
    scopes: list[str]
    added_files: list[str] = field(default_factory=list)
    updated_files: list[str] = field(default_factory=list)
    removed_files: list[str] = field(default_factory=list)
    chunks: int = 0
    index_path: str = ""


class LocalRagEngine:
    """Build, search, and answer from a local Obsidian vault."""

    def __init__(
        self,
        config: WikiAgentConfig,
        guard: VaultGuard,
        obsidian: ObsidianCLIAdapter,
    ) -> None:
        self.config = config
        self.guard = guard
        self.obsidian = obsidian

    @property
    def index_path(self) -> Path:
        return self.config.wiki_dir / ".nanobot" / "chroma"

    @property
    def collection_name(self) -> str:
        return _COLLECTION_NAME

    def build_index(
        self,
        scopes: Iterable[RagScope | str] = ("wiki",),
        *,
        persist: bool = False,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> RagIndex:
        """Build an index from allowed vault paths.

        ``persist=True`` writes the Chroma DB only under ``wiki/.nanobot/chroma``
        after passing the same VaultGuard write boundary as other wiki writes.
        """

        normalized_scopes = _normalize_scopes(scopes)
        chunks, fingerprints = self._build_chunks(normalized_scopes, max_chars=max_chars)
        created_at = datetime.now().isoformat(timespec="seconds")
        index = RagIndex(
            version=_INDEX_VERSION,
            created_at=created_at,
            scopes=normalized_scopes,
            files=fingerprints,
            chunks=chunks,
        )
        if persist:
            client = self._chroma_client(persistent=True)
            collection = self._reset_collection(
                client,
                scopes=normalized_scopes,
                files=fingerprints,
                created_at=created_at,
            )
            self._add_chunks(collection, chunks)
        return index

    def load_index(self) -> RagIndex | None:
        try:
            client = self._chroma_client(persistent=True, create_dir=False)
            collection = client.get_collection(self.collection_name)
        except Exception:
            return None
        metadata = getattr(collection, "metadata", {}) or {}
        if int(metadata.get("version", 0) or 0) != _INDEX_VERSION:
            return None
        raw = collection.get(include=["documents", "metadatas"])
        chunks = _chunks_from_chroma_get(raw)
        return RagIndex(
            version=_INDEX_VERSION,
            created_at=str(metadata.get("created_at", "")),
            scopes=_json_list(metadata.get("scopes_json"), default=["wiki"]),
            files=_json_dict(metadata.get("files_json")),
            chunks=chunks,
        )

    def sync_index(
        self,
        scopes: Iterable[RagScope | str] = ("all",),
        *,
        force: bool = False,
        max_chars: int = _DEFAULT_MAX_CHARS,
    ) -> RagSyncResult:
        """Incrementally sync the persistent Chroma index.

        Changed and removed paths are deleted by path, then only new/changed
        chunks are embedded and added.  ``force=True`` rebuilds the collection.
        """

        normalized_scopes = _normalize_scopes(scopes)
        current_chunks, current_files = self._build_chunks(normalized_scopes, max_chars=max_chars)
        cached = self.load_index()
        if force or cached is None or not set(normalized_scopes).issubset(set(cached.scopes)):
            index = self.build_index(normalized_scopes, persist=True, max_chars=max_chars)
            return RagSyncResult(
                status="rebuilt" if force else "created",
                scopes=normalized_scopes,
                added_files=sorted(index.files),
                chunks=len(index.chunks),
                index_path=self._relative_posix(self.index_path),
            )

        old_files = cached.files
        added = sorted(path for path in current_files if path not in old_files)
        updated = sorted(
            path for path, fingerprint in current_files.items()
            if path in old_files and old_files[path] != fingerprint
        )
        removed = sorted(path for path in old_files if path not in current_files)
        changed_paths = set(added + updated)
        if not changed_paths and not removed:
            return RagSyncResult(
                status="fresh",
                scopes=normalized_scopes,
                chunks=len(cached.chunks),
                index_path=self._relative_posix(self.index_path),
            )

        client = self._chroma_client(persistent=True)
        collection = client.get_collection(self.collection_name)
        for path in [*removed, *updated]:
            self._delete_path_chunks(collection, path)
        self._add_chunks(
            collection,
            [chunk for chunk in current_chunks if chunk.path in changed_paths],
        )
        self._update_collection_metadata(
            collection,
            scopes=normalized_scopes,
            files=current_files,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        return RagSyncResult(
            status="updated",
            scopes=normalized_scopes,
            added_files=added,
            updated_files=updated,
            removed_files=removed,
            chunks=len(current_chunks),
            index_path=self._relative_posix(self.index_path),
        )

    def search(
        self,
        question: str,
        *,
        top_k: int = 5,
        scopes: Iterable[RagScope | str] = ("wiki",),
        use_cache: bool = False,
    ) -> list[RagSearchResult]:
        query_tokens = _tokenize(question)
        if not query_tokens:
            return []

        normalized_scopes = _normalize_scopes(scopes)
        top_k = max(1, min(top_k, 20))
        if use_cache:
            cached = self.load_index()
            if cached is not None and set(normalized_scopes).issubset(set(cached.scopes)):
                try:
                    client = self._chroma_client(persistent=True, create_dir=False)
                    collection = client.get_collection(self.collection_name)
                    return self._query_collection(collection, question, normalized_scopes, top_k)
                except Exception:
                    pass

        chunks, fingerprints = self._build_chunks(normalized_scopes, max_chars=_DEFAULT_MAX_CHARS)
        client = self._chroma_client(persistent=False)
        collection = self._reset_collection(
            client,
            scopes=normalized_scopes,
            files=fingerprints,
            created_at=datetime.now().isoformat(timespec="seconds"),
        )
        self._add_chunks(collection, chunks)
        return self._query_collection(collection, question, normalized_scopes, top_k)

    def answer(
        self,
        question: str,
        *,
        top_k: int = 5,
        scopes: Iterable[RagScope | str] = ("wiki",),
        use_cache: bool = False,
    ) -> str:
        results = self.search(question, top_k=top_k, scopes=scopes, use_cache=use_cache)
        if not results:
            return (
                "## 回答\n\n"
                "未找到足够依据。RAG 检索只会读取允许范围内的 raw/ 与 wiki/ 内容；"
                "当前问题没有匹配到可引用片段，因此不会编造答案。\n\n"
                "## 引用\n\n"
                "- 无\n\n"
                "## 建议\n\n"
                "- 先通过 Ingest 将相关 raw/ 资料沉淀到 wiki/，或补充更明确的关键词。\n"
            )

        evidence_lines = []
        citation_lines = []
        for idx, result in enumerate(results, start=1):
            chunk = result.chunk
            citation = _citation(chunk)
            evidence_lines.append(f"{idx}. {result.snippet} [{citation}]")
            citation_lines.append(
                f"- [{citation}] {chunk.path}"
                + (f" > {chunk.heading}" if chunk.heading else "")
            )

        return (
            "## 回答\n\n"
            "根据当前知识库中检索到的证据片段，最相关的信息如下：\n\n"
            + "\n".join(evidence_lines)
            + "\n\n"
            "以上内容是从可引用片段中抽取的证据摘要；如需形成稳定结论，建议再写回 "
            "wiki/overview 或 wiki/comparisons 页面。\n\n"
            "## 引用\n\n"
            + "\n".join(citation_lines)
            + "\n\n"
            "## 可写回建议\n\n"
            "- 默认不自动写回；如要沉淀为长期知识，先生成写回计划再确认执行。\n"
        )

    def health(self, scopes: Iterable[RagScope | str] = ("wiki",)) -> str:
        index = self.build_index(scopes, persist=False)
        empty_chunks = [chunk for chunk in index.chunks if not chunk.tokens]
        cached = self.load_index()
        cache_status = "missing"
        cached_chunks = 0
        if cached:
            cached_chunks = len(cached.chunks)
            cache_status = "fresh" if cached.files == index.files else "stale"
        return (
            "# RAG Health\n\n"
            "- backend: chroma\n"
            f"- indexed_files: {len(index.files)}\n"
            f"- indexed_chunks: {len(index.chunks)}\n"
            f"- cached_chunks: {cached_chunks}\n"
            f"- empty_chunks: {len(empty_chunks)}\n"
            f"- cache_status: {cache_status}\n"
            f"- index_path: {self._relative_posix(self.index_path)}\n"
        )

    def _build_chunks(
        self,
        scopes: list[str],
        *,
        max_chars: int,
    ) -> tuple[list[RagChunk], dict[str, str]]:
        files = self._collect_files(scopes)
        chunks: list[RagChunk] = []
        fingerprints: dict[str, str] = {}
        for relative in files:
            content = self._read_vault_file(relative)
            fingerprints[relative] = _fingerprint(content)
            chunks.extend(_chunk_document(relative, content, max_chars=max_chars))
        return chunks, fingerprints

    def _chroma_client(self, *, persistent: bool, create_dir: bool = True):
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is required for RAG. Install project dependencies or run "
                "`pip install chromadb`."
            ) from exc

        if not persistent:
            return chromadb.EphemeralClient()

        relative = self._relative_posix(self.index_path)
        if create_dir:
            resolved = self.guard.assert_can_write(relative)
            resolved.mkdir(parents=True, exist_ok=True)
        else:
            resolved = self.guard.assert_can_read(relative)
        return chromadb.PersistentClient(path=str(resolved))

    def _reset_collection(
        self,
        client: Any,
        *,
        scopes: list[str],
        files: dict[str, str],
        created_at: str,
    ):
        try:
            client.delete_collection(self.collection_name)
        except Exception:
            pass
        return client.get_or_create_collection(
            name=self.collection_name,
            metadata=_index_metadata(scopes=scopes, files=files, created_at=created_at),
        )

    def _update_collection_metadata(
        self,
        collection: Any,
        *,
        scopes: list[str],
        files: dict[str, str],
        created_at: str,
    ) -> None:
        metadata = _index_metadata(scopes=scopes, files=files, created_at=created_at)
        collection.modify(metadata=metadata)

    def _add_chunks(self, collection: Any, chunks: list[RagChunk]) -> None:
        if not chunks:
            return
        ids = [chunk.chunk_id for chunk in chunks]
        documents = [chunk.text for chunk in chunks]
        embeddings = [_embed_text(_embedding_text(chunk)) for chunk in chunks]
        metadatas = [_chroma_metadata(chunk) for chunk in chunks]
        for start in range(0, len(chunks), 200):
            end = start + 200
            collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                embeddings=embeddings[start:end],
                metadatas=metadatas[start:end],
            )

    def _delete_path_chunks(self, collection: Any, path: str) -> None:
        try:
            raw = collection.get(where={"path": path})
        except Exception:
            return
        ids = raw.get("ids") or []
        if ids:
            collection.delete(ids=ids)

    def _query_collection(
        self,
        collection: Any,
        question: str,
        scopes: list[str],
        top_k: int,
    ) -> list[RagSearchResult]:
        count = collection.count()
        if count <= 0:
            return []
        n_results = min(count, max(top_k * 4, top_k))
        where = {"scope": scopes[0]} if len(scopes) == 1 else None
        query_kwargs: dict[str, Any] = {
            "query_embeddings": [_embed_text(question)],
            "n_results": n_results,
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            query_kwargs["where"] = where
        raw = collection.query(**query_kwargs)
        candidates = _search_results_from_chroma_query(raw, question)
        allowed = set(scopes)
        filtered = [item for item in candidates if _chunk_scope(item.chunk) in allowed]
        filtered.sort(key=lambda item: (-item.score, item.chunk.path, item.chunk.chunk_id))
        return filtered[:top_k]

    def _collect_files(self, scopes: list[str]) -> list[str]:
        files: list[str] = []
        if "wiki" in scopes:
            for path in self.obsidian.list_files("wiki"):
                if _is_index_cache_path(path):
                    continue
                _append_unique(files, path)
        if "raw" in scopes:
            raw_dir = self.guard.assert_can_read("raw")
            for path in sorted(raw_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in _SUPPORTED_SUFFIXES:
                    _append_unique(files, self._relative_posix(path))
        return files

    def _read_vault_file(self, relative: str) -> str:
        resolved = self.guard.assert_can_read(relative)
        if resolved.suffix.lower() not in _SUPPORTED_SUFFIXES:
            return ""
        return resolved.read_text(encoding="utf-8", errors="replace")

    def _relative_posix(self, path: Path) -> str:
        return path.resolve().relative_to(self.config.vault_path).as_posix()


def format_search_results(results: list[RagSearchResult]) -> str:
    if not results:
        return "No RAG evidence found."
    lines = ["# RAG Search Results", ""]
    for idx, result in enumerate(results, start=1):
        chunk = result.chunk
        lines.extend(
            [
                f"## {idx}. {_citation(chunk)}",
                "",
                f"- score: {result.score:.4f}",
                f"- path: {chunk.path}",
                f"- heading: {chunk.heading or '(root)'}",
                f"- snippet: {result.snippet}",
                "",
            ]
        )
    return "\n".join(lines).rstrip()


def _normalize_scopes(scopes: Iterable[RagScope | str]) -> list[str]:
    values: list[str] = []
    for scope in scopes:
        clean = str(scope).strip().lower()
        if clean == "all":
            for value in ("wiki", "raw"):
                _append_unique(values, value)
            continue
        if clean not in {"wiki", "raw"}:
            raise ValueError(f"Unsupported RAG scope: {scope}. Use wiki, raw, or all.")
        _append_unique(values, clean)
    return values or ["wiki"]


def _chunk_document(relative: str, content: str, *, max_chars: int) -> list[RagChunk]:
    metadata, body = _safe_parse_frontmatter(content)
    links = extract_wikilinks(body)
    title = _document_title(relative, body, metadata)
    sections = _split_sections(body)
    chunks: list[RagChunk] = []
    for heading, section_text in sections:
        for part in _split_text(section_text, max_chars=max_chars):
            clean = part.strip()
            if not clean:
                continue
            ordinal = len(chunks) + 1
            chunk_id = f"{relative}#chunk-{ordinal:03d}"
            chunk_metadata: dict[str, object] = {
                "title": title,
                "type": metadata.get("type", ""),
                "tags": metadata.get("tags", []),
                "sources": metadata.get("sources", []),
                "updated": metadata.get("updated", ""),
                "wikilinks": links,
            }
            chunks.append(
                RagChunk(
                    chunk_id=chunk_id,
                    path=relative,
                    heading=heading,
                    text=clean,
                    metadata=chunk_metadata,
                    tokens=_tokenize(f"{title} {heading} {clean}"),
                )
            )
    return chunks


def _search_results_from_chroma_query(raw: dict[str, Any], question: str) -> list[RagSearchResult]:
    ids = _first_result_list(raw.get("ids"))
    documents = _first_result_list(raw.get("documents"))
    metadatas = _first_result_list(raw.get("metadatas"))
    distances = _first_result_list(raw.get("distances"))
    query_tokens = _tokenize(question)
    lower_question = question.lower()
    results: list[RagSearchResult] = []
    for idx, chunk_id in enumerate(ids):
        metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
        text = documents[idx] if idx < len(documents) else ""
        distance = float(distances[idx]) if idx < len(distances) else 1.0
        chunk = _chunk_from_chroma(chunk_id, text, metadata)
        vector_score = _distance_to_score(distance)
        lexical_score = _lexical_score(query_tokens, chunk.text)
        metadata_score = _metadata_score(query_tokens, lower_question, chunk)
        if lexical_score == 0 and metadata_score == 0:
            continue
        score = 0.75 * vector_score + 0.15 * lexical_score + 0.10 * metadata_score
        results.append(
            RagSearchResult(
                chunk=chunk,
                score=score,
                snippet=_best_snippet(chunk.text, query_tokens),
            )
        )
    return results


def _chunks_from_chroma_get(raw: dict[str, Any]) -> list[RagChunk]:
    ids = raw.get("ids") or []
    documents = raw.get("documents") or []
    metadatas = raw.get("metadatas") or []
    chunks: list[RagChunk] = []
    for idx, chunk_id in enumerate(ids):
        metadata = metadatas[idx] if idx < len(metadatas) and isinstance(metadatas[idx], dict) else {}
        text = documents[idx] if idx < len(documents) else ""
        chunks.append(_chunk_from_chroma(chunk_id, text, metadata))
    return chunks


def _chunk_from_chroma(chunk_id: str, text: str, metadata: dict[str, Any]) -> RagChunk:
    path = str(metadata.get("path") or str(chunk_id).split("#", 1)[0])
    heading = str(metadata.get("heading") or "")
    chunk_metadata: dict[str, object] = {
        "title": str(metadata.get("title") or ""),
        "type": str(metadata.get("type") or ""),
        "tags": _json_list(metadata.get("tags_json"), default=[]),
        "sources": _json_list(metadata.get("sources_json"), default=[]),
        "updated": str(metadata.get("updated") or ""),
        "wikilinks": _json_list(metadata.get("wikilinks_json"), default=[]),
    }
    return RagChunk(
        chunk_id=str(chunk_id),
        path=path,
        heading=heading,
        text=str(text),
        metadata=chunk_metadata,
        tokens=_tokenize(f"{metadata.get('title', '')} {heading} {text}"),
    )


def _distance_to_score(distance: float) -> float:
    if distance < 0:
        return 0.0
    return 1.0 / (1.0 + distance)


def _lexical_score(query_tokens: list[str], text: str) -> float:
    lower_text = text.lower()
    hits = sum(1 for token in set(query_tokens) if token in lower_text)
    return hits / max(len(set(query_tokens)), 1)


def _metadata_score(query_tokens: list[str], lower_question: str, chunk: RagChunk) -> float:
    metadata_text = " ".join(
        [
            str(chunk.metadata.get("title", "")),
            str(chunk.metadata.get("type", "")),
            " ".join(str(item) for item in _as_list(chunk.metadata.get("tags"))),
            " ".join(str(item) for item in _as_list(chunk.metadata.get("sources"))),
            chunk.path,
            chunk.heading,
        ]
    ).lower()
    hits = sum(1 for token in set(query_tokens) if token in metadata_text)
    exact_path_boost = 1 if chunk.path.lower() in lower_question else 0
    return min(1.0, (hits + exact_path_boost) / max(len(set(query_tokens)), 1))


def _embedding_text(chunk: RagChunk) -> str:
    metadata = chunk.metadata
    return " ".join(
        [
            str(metadata.get("title", "")),
            str(metadata.get("type", "")),
            " ".join(str(item) for item in _as_list(metadata.get("tags"))),
            " ".join(str(item) for item in _as_list(metadata.get("sources"))),
            chunk.path,
            chunk.heading,
            chunk.text,
        ]
    )


def _embed_text(text: str, *, dim: int = _EMBEDDING_DIM) -> list[float]:
    """Deterministic local embedding used for offline Chroma indexing."""

    vector = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:4], "big") % dim
        sign = 1.0 if digest[4] & 1 else -1.0
        vector[idx] += sign
    norm = sum(value * value for value in vector) ** 0.5
    if norm == 0:
        return vector
    return [value / norm for value in vector]


def _chroma_metadata(chunk: RagChunk) -> dict[str, object]:
    metadata = chunk.metadata
    return {
        "chunk_id": chunk.chunk_id,
        "path": chunk.path,
        "heading": chunk.heading,
        "scope": _chunk_scope(chunk),
        "title": str(metadata.get("title", "")),
        "type": str(metadata.get("type", "")),
        "tags_json": json.dumps(_as_list(metadata.get("tags")), ensure_ascii=False),
        "sources_json": json.dumps(_as_list(metadata.get("sources")), ensure_ascii=False),
        "updated": str(metadata.get("updated", "")),
        "wikilinks_json": json.dumps(_as_list(metadata.get("wikilinks")), ensure_ascii=False),
    }


def _index_metadata(*, scopes: list[str], files: dict[str, str], created_at: str) -> dict[str, object]:
    return {
        "version": _INDEX_VERSION,
        "created_at": created_at,
        "scopes_json": json.dumps(scopes, ensure_ascii=False, sort_keys=True),
        "files_json": json.dumps(files, ensure_ascii=False, sort_keys=True),
        "embedding": "nanobot-hashing-v1",
    }


def _chunk_scope(chunk: RagChunk) -> str:
    return "raw" if chunk.path.startswith("raw/") else "wiki"


def _first_result_list(value: Any) -> list[Any]:
    if not value:
        return []
    if isinstance(value, list) and value and isinstance(value[0], list):
        return value[0]
    if isinstance(value, list):
        return value
    return []


def _json_list(value: object, *, default: list[str]) -> list[str]:
    if not isinstance(value, str) or not value:
        return default
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return default
    if not isinstance(parsed, list):
        return default
    return [str(item) for item in parsed]


def _json_dict(value: object) -> dict[str, str]:
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(key): str(val) for key, val in parsed.items()}


def _safe_parse_frontmatter(markdown: str) -> tuple[dict[str, object], str]:
    try:
        metadata, body = parse_frontmatter(markdown)
    except ValueError:
        return {}, markdown
    return metadata, body


def _split_sections(body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in body.splitlines():
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match:
            if current_lines:
                sections.append((current_heading, current_lines))
                current_lines = []
            current_heading = _clean_markdown(match.group(2))
            continue
        current_lines.append(line)
    if current_lines:
        sections.append((current_heading, current_lines))
    if not sections and body.strip():
        sections.append(("", body.splitlines()))
    return [(heading, "\n".join(lines).strip()) for heading, lines in sections]


def _split_text(
    text: str,
    *,
    max_chars: int,
    overlap_chars: int = _DEFAULT_OVERLAP_CHARS,
) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        return [text[:max_chars]]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = current[-overlap_chars:].strip() if overlap_chars > 0 else ""
        if len(paragraph) > max_chars:
            chunks.extend(_window_text(paragraph, max_chars=max_chars, overlap_chars=overlap_chars))
            current = ""
        else:
            current = paragraph
    if current:
        chunks.append(current)
    return chunks


def _window_text(text: str, *, max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[str] = []
    step = max(max_chars - overlap_chars, 1)
    for start in range(0, len(text), step):
        chunk = text[start : start + max_chars].strip()
        if chunk:
            chunks.append(chunk)
        if start + max_chars >= len(text):
            break
    return chunks


def _best_snippet(text: str, query_tokens: list[str], max_chars: int = 280) -> str:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?。！？])\s+|\n+", text) if part.strip()]
    if not sentences:
        return _trim(text, max_chars)
    scored = []
    for sentence in sentences:
        lower = sentence.lower()
        score = sum(1 for token in set(query_tokens) if token in lower)
        scored.append((score, len(sentence), sentence))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return _trim(scored[0][2], max_chars)


def _document_title(relative: str, body: str, metadata: dict[str, object]) -> str:
    summary = metadata.get("title")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return _clean_markdown(match.group(1))
    return Path(relative).stem.replace("-", " ").replace("_", " ").strip()


def _tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in re.finditer(r"[A-Za-z0-9][A-Za-z0-9_-]*|[\u4e00-\u9fff]+", text.lower()):
        value = match.group(0).strip("_-")
        if not value:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", value):
            if len(value) >= 2 and value not in _STOPWORDS:
                tokens.append(value)
            continue
        tokens.append(value)
        tokens.extend(_char_ngrams(value, 2))
    return tokens


def _char_ngrams(value: str, n: int) -> list[str]:
    if len(value) <= n:
        return []
    return [value[idx : idx + n] for idx in range(0, len(value) - n + 1)]


def _clean_markdown(value: str) -> str:
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("[[", "").replace("]]", "")
    return re.sub(r"\s+", " ", value).strip()


def _trim(value: str, max_chars: int) -> str:
    clean = re.sub(r"\s+", " ", value).strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _fingerprint(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _citation(chunk: RagChunk) -> str:
    return chunk.chunk_id


def _append_unique(values: list[str], value: str) -> None:
    normalized = value.replace("\\", "/")
    if normalized not in values:
        values.append(normalized)


def _as_list(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _is_index_cache_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.startswith("wiki/.nanobot/")


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "be",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "what",
    "with",
}
