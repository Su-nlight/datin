import json
import requests
import os
from typing import Callable, Optional
from langchain.llms.base import LLM
from langchain_core.messages import BaseMessage
from pineconedb import PineconeDB
from evaluator import evaluate_rag_parameters, eval_reflection
from llm_provider import GeminiLLM  # for _vector_query_generator — stays on Gemini (cheap, fast)

from dotenv import load_dotenv
load_dotenv("API.env")


class RagModel:
    def __init__(self, PineconeAPIKey: str, NameSpaces: list, Index_Name: str, min_score: float, llm: LLM,
                 evaluation_llm: Optional[LLM] = None):
        """
        llm: injected LLM instance (GeminiLLM or OllamaLLM) used for generation.
             RagModel does not instantiate its own LLM — caller's responsibility.
        evaluation_llm: injected LLM instance used as the LLM-as-a-Judge for
             evaluate_rag_parameters(). Falls back to `llm` if not supplied,
             so existing callers that only pass `llm` keep working unchanged —
             but callers wiring up GENERATION_LLM_PROVIDER / EVALUATION_LLM_PROVIDER
             should pass both so generation and evaluation are truly independent.
        """
        self.llm = llm
        self.evaluation_llm = evaluation_llm if evaluation_llm is not None else llm
        self.Name_Spaces = NameSpaces
        self.Pinecone_DB = PineconeDB(pinecone_api_key=PineconeAPIKey, index_name=Index_Name)
        self.Min_Score = min_score

        # Dedicated lightweight Gemini client only for query refinement pre-processing.
        # TODO: migrate to self.llm once a cheap/fast routing strategy is in place.
        self._query_refiner = self.llm
        
    # -------------------------------------------------------------------------
    # Static / private helpers (unchanged from original)
    # -------------------------------------------------------------------------

    @staticmethod
    def _detect_language_from_url(url):
        ext = os.path.splitext(url)[1].split('?')[0]
        return {
            '.py': 'python', '.js': 'javascript', '.java': 'java',
            '.c': 'c', '.cpp': 'cpp', '.html': 'html', '.css': 'css',
            '.sh': 'bash', '.rb': 'ruby', '.go': 'go', '.rs': 'rust',
            '.php': 'php', '.ts': 'typescript', '.txt': ''
        }.get(ext, '')

    @staticmethod
    def _convert_gitlab_url_to_raw(url):
        if "/-/blob/" in url:
            return url.replace("/-/blob/", "/-/raw/")
        return url

    @staticmethod
    def _unpack_dict_list_default(dict_list: list):
        output = []
        for item in dict_list:
            lines = []
            for key, value in item.items():
                if not isinstance(value, str):
                    value = json.dumps(value, indent=2)
                lines.append(f"{key}: {value}")
            output.append("\n".join(lines))
        return "\n\n---\n\n".join(output)

    def _unpack_dict_list_ExploitDB(self, dict_list: list):
        output = []
        for item in dict_list:
            lines = []
            for key, value in item.items():
                if not isinstance(value, str):
                    value = json.dumps(value, indent=2)
                lines.append(f"{key}: {value}")
                if key == "file":
                    lines.append(self.gitlab_file_to_markdown(
                        f"https://gitlab.com/exploit-database/exploitdb/-/raw/main/{value}"
                    ))
            output.append("\n".join(lines))
        return "\n\n---\n\n".join(output)

    def gitlab_file_to_markdown(self, url):
        raw_url = self._convert_gitlab_url_to_raw(url)
        language = self._detect_language_from_url(raw_url)
        response = requests.get(raw_url)
        if response.status_code != 200:
            return ""
        return f"```{language}\n{response.text}\n```"

    # -------------------------------------------------------------------------
    # New helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _format_history_for_prompt(history: list[BaseMessage]) -> str:
        """
        Converts LangChain BaseMessage list to a plain string block for prompt injection.
        Portable across both Gemini and Ollama prompt formats.

        Output example:
            User: what is APT28?
            Assistant: APT28 is a Russian threat group...
        """
        if not history:
            return ""
        lines = []
        for msg in history:
            role = "User" if msg.type == "human" else "Assistant"
            lines.append(f"{role}: {msg.content}")
        return "\n".join(lines)

    def _contextualize_query(self, raw_query: str, history: list[BaseMessage]) -> str:
        """
        Rewrites an ambiguous query into a fully self-contained one using chat history.
        Runs only when history is non-empty — no overhead on first turn.

        Uses the lightweight query refiner (Gemini Flash Lite), not self.llm,
        since this is a cheap pre-processing step regardless of main provider.
        """
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
        query = self._vector_query_generator(query)
        query_results = self.Pinecone_DB.query_vector_multiple(
            query_text=query,
            NameSpaces=self.Name_Spaces,
            min_score=self.Min_Score
        )
        full_context_data = ""
        for name in self.Name_Spaces:
            cnxt = "\n"
            if name == "exploit_db":
                cnxt += self._unpack_dict_list_ExploitDB(query_results.get(name, []))
            else:
                cnxt += self._unpack_dict_list_default(query_results.get(name, []))
            full_context_data += cnxt
        return full_context_data

    def _build_rag_prompt(self, user_query: str, context: str, history: list[BaseMessage]) -> str:
        """
        Constructs the final prompt with history + context + query.
        Separated so both caller methods share identical prompt structure.
        """
        history_block = self._format_history_for_prompt(history)
        history_section = f"Conversation History:\n{history_block}\n\n" if history_block else ""
        return (
            f"{history_section}"
            f"Context:\n---\n{context}\n---\n\n"
            f"Now answer the following user query with a DETAILED DESCRIPTION:\n\"{user_query}\""
        )

    # -------------------------------------------------------------------------
    # Public callers
    # -------------------------------------------------------------------------

    def Rag_Generator_caller(self, user_query: str, history: list[BaseMessage] = None) -> str:
        """
        Non-streaming RAG response.

        Args:
            user_query: Raw user input.
            history: Trimmed BaseMessage list from get_trimmed_history().
                     Defaults to empty list if not provided (backward compatible).

        Returns:
            Final (possibly healed) response string.
        """
        history = history or []

        # Step 1: Resolve ambiguous references in query using history
        contextualized_query = self._contextualize_query(user_query, history)

        # Step 2: Retrieve context using the resolved query
        full_context = self._vector_data_retriever(query=contextualized_query)

        # Step 3: Build prompt and invoke LLM
        prompt = self._build_rag_prompt(user_query, full_context, history)
        rag_response = self.llm.predict(prompt)

        # Step 4: Evaluate — pass ORIGINAL query, not contextualized,
        # so evaluator scores align with what the user actually asked.
        # Evaluation runs on its own LLM (self.evaluation_llm) and is wrapped
        # in its own try/except: a judge failure (e.g. a 429 from the
        # evaluation provider) must never discard an already-successful
        # generation — it should just skip healing and return the answer.
        try:
            eval_results = evaluate_rag_parameters(
                llm=self.evaluation_llm,
                inputs={"question": user_query},
                outputs={"answer": rag_response},
                context={"documents": [i.strip() for i in full_context.split("---")]}
            )
            healing = eval_reflection(eval_results)
            print(healing)  # debug

            # Step 5: Healing pass if required
            if healing["Healing_required"]:
                healing_prompt = (
                    f'For the AI generated response: "{rag_response}".\n'
                    f'{healing["Healing_Prompt"]}'
                    f"Correct the answer as per the healing required and return the response accurately."
                )
                rag_response = self.llm.predict(healing_prompt)
        except Exception as exc:
            print(f"[RagModel] evaluation/healing skipped due to error: {exc}")

        return rag_response

    def Rag_Generator_stream_caller(
        self,
        user_query: str,
        history: list[BaseMessage] = None,
        on_complete: Optional[Callable[[str], None]] = None
    ):
        """
        Streaming RAG response.

        Args:
            user_query: Raw user input.
            history: Trimmed BaseMessage list from get_trimmed_history().
            on_complete: Callback fired with the full buffered response after
                         streaming ends. main.py uses this to persist history
                         without blocking the stream.

        Yields:
            str chunks from the LLM stream.
        """
        history = history or []

        contextualized_query = self._contextualize_query(user_query, history)
        full_context = self._vector_data_retriever(query=contextualized_query)
        prompt = self._build_rag_prompt(user_query, full_context, history)

        buffer = []
        for chunk in self.llm._stream(prompt):
            buffer.append(chunk)
            yield chunk

        # Fire callback with complete response for history persistence
        if on_complete and buffer:
            on_complete("".join(buffer))