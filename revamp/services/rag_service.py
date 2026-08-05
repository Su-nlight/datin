"""
app/services/rag_service.py

Updated to match the upstream fixes in ragroute.py:
  - RagService now takes an optional `evaluation_llm`, falling back to
    `llm` (the generation model) if not supplied. This lets callers wire
    GENERATION_LLM_PROVIDER and EVALUATION_LLM_PROVIDER to genuinely
    different models.
  - The query refiner (_contextualize_query / _vector_query_generator)
    now uses `self.llm` directly — upstream's own TODO ("migrate to
    self.llm once a cheap/fast routing strategy is in place") was
    resolved, so this service does the same rather than keeping a
    separate refiner client.
  - The evaluation + healing pass in `generate()` is wrapped in its own
    try/except: a judge failure (e.g. a 429 from the evaluation
    provider) must never discard a response that already generated
    successfully — it just skips healing and returns the answer as-is.
"""
import os
from typing import Callable, List, Optional

import requests
from langchain.llms.base import LLM
from langchain_core.messages import BaseMessage

from app.providers.pinecone_provider import PineconeProvider
from app.services.evaluation_service import EvaluationService


class RagService:
    def __init__(
        self,
        llm: LLM,
        pinecone: PineconeProvider,
        namespaces: List[str],
        min_score: float,
        evaluation_service: EvaluationService,
        evaluation_llm: Optional[LLM] = None,
    ):
        self.llm = llm
        # Falls back to the generation LLM if no separate evaluation model
        # was supplied — matches ragroute.py's RagModel.__init__ behavior.
        self.evaluation_llm = evaluation_llm if evaluation_llm is not None else llm
        self.pinecone = pinecone
        self.namespaces = namespaces
        self.min_score = min_score
        self.evaluation_service = evaluation_service
        # Query refinement now reuses the generation LLM directly — no
        # separate lightweight client, matching upstream's resolved TODO.
        self._query_refiner = self.llm

    # -- static helpers (unchanged from ragroute.py) -----------------------

    @staticmethod
    def _detect_language_from_url(url: str) -> str:
        ext = os.path.splitext(url)[1].split("?")[0]
        return {
            ".py": "python", ".js": "javascript", ".java": "java",
            ".c": "c", ".cpp": "cpp", ".html": "html", ".css": "css",
            ".sh": "bash", ".rb": "ruby", ".go": "go", ".rs": "rust",
            ".php": "php", ".ts": "typescript", ".txt": "",
        }.get(ext, "")

    @staticmethod
    def _convert_gitlab_url_to_raw(url: str) -> str:
        if "/-/blob/" in url:
            return url.replace("/-/blob/", "/-/raw/")
        return url

    @staticmethod
    def _unpack_dict_list_default(dict_list: list) -> str:
        import json as _json

        output = []
        for item in dict_list:
            lines = []
            for key, value in item.items():
                if not isinstance(value, str):
                    value = _json.dumps(value, indent=2)
                lines.append(f"{key}: {value}")
            output.append("\n".join(lines))
        return "\n\n---\n\n".join(output)

    def _unpack_dict_list_exploitdb(self, dict_list: list) -> str:
        import json as _json

        output = []
        for item in dict_list:
            lines = []
            for key, value in item.items():
                if not isinstance(value, str):
                    value = _json.dumps(value, indent=2)
                lines.append(f"{key}: {value}")
                if key == "file":
                    lines.append(
                        self._gitlab_file_to_markdown(
                            f"https://gitlab.com/exploit-database/exploitdb/-/raw/main/{value}"
                        )
                    )
            output.append("\n".join(lines))
        return "\n\n---\n\n".join(output)

    def _gitlab_file_to_markdown(self, url: str) -> str:
        raw_url = self._convert_gitlab_url_to_raw(url)
        language = self._detect_language_from_url(raw_url)
        response = requests.get(raw_url)
        if response.status_code != 200:
            return ""
        return f"```{language}\n{response.text}\n```"

    @staticmethod
    def _format_history_for_prompt(history: List[BaseMessage]) -> str:
        if not history:
            return ""
        lines = []
        for msg in history:
            role = "User" if msg.type == "human" else "Assistant"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def _contextualize_query(self, raw_query: str, history: List[BaseMessage]) -> str:
        if not history:
            return raw_query
        history_str = self._format_history_for_prompt(history)
        prompt = (
            f"Given this conversation history:\n{history_str}\n\n"
            f"Rewrite the following question to be fully self-contained "
            f"(resolve all pronouns and references). Return ONLY the rewritten question, nothing else.\n"
            f"Question: {raw_query}"
        )
        return self._query_refiner.predict(prompt).strip()

    def _vector_query_generator(self, raw_query: str) -> str:
        prompt = (
            f"Convert the following question to a text query for vector searcher "
            f"& keep only its keywords and avoid unnecessary words:\n"
            f"'{raw_query}'.\nRephrase whole to a very refined query avoid writing that we need info"
        )
        return self._query_refiner.predict(prompt).strip()

    def _vector_data_retriever(self, query: str) -> str:
        refined_query = self._vector_query_generator(query)
        results = self.pinecone.query_multiple_namespaces(
            query_text=refined_query, namespaces=self.namespaces, min_score=self.min_score
        )
        full_context = ""
        for ns in self.namespaces:
            block = "\n"
            if ns == "exploit_db":
                block += self._unpack_dict_list_exploitdb(results.get(ns, []))
            else:
                block += self._unpack_dict_list_default(results.get(ns, []))
            full_context += block
        return full_context

    def _build_rag_prompt(self, user_query: str, context: str, history: List[BaseMessage]) -> str:
        history_block = self._format_history_for_prompt(history)
        history_section = f"Conversation History:\n{history_block}\n\n" if history_block else ""
        return (
            f"{history_section}"
            f"Context:\n---\n{context}\n---\n\n"
            f'Now answer the following user query with a DETAILED DESCRIPTION:\n"{user_query}"'
        )

    # -- public API ---------------------------------------------------------

    def generate(self, user_query: str, history: Optional[List[BaseMessage]] = None) -> str:
        history = history or []
        contextualized = self._contextualize_query(user_query, history)
        context = self._vector_data_retriever(query=contextualized)
        prompt = self._build_rag_prompt(user_query, context, history)
        response = self.llm.predict(prompt)

        # Evaluation + healing run on their own LLM and are wrapped in their
        # own try/except: a judge failure must never discard an
        # already-successful generation — it should just skip healing and
        # return the answer as-is.
        try:
            eval_results = self.evaluation_service.evaluate_rag_parameters(
                inputs={"question": user_query},
                outputs={"answer": response},
                context={"documents": [d.strip() for d in context.split("---")]},
            )
            healing = self.evaluation_service.eval_reflection(eval_results, question=user_query)

            if healing["Healing_required"]:
                healing_prompt = (
                    f'For the AI generated response: "{response}".\n'
                    f'{healing["Healing_Prompt"]}'
                    f"Correct the answer as per the healing required and return the response accurately."
                )
                response = self.llm.predict(healing_prompt)
        except Exception as exc:
            print(f"[RagService] evaluation/healing skipped due to error: {exc}")

        return response

    def generate_stream(
        self,
        user_query: str,
        history: Optional[List[BaseMessage]] = None,
        on_complete: Optional[Callable[[str], None]] = None,
    ):
        history = history or []
        contextualized = self._contextualize_query(user_query, history)
        context = self._vector_data_retriever(query=contextualized)
        prompt = self._build_rag_prompt(user_query, context, history)

        buffer = []
        for chunk in self.llm._stream(prompt):
            buffer.append(chunk)
            yield chunk

        if on_complete and buffer:
            on_complete("".join(buffer))