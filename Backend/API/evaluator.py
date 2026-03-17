from langchain.llms.base import LLM
from google import genai
from google.genai import types
from openevals.prompts import (
    CORRECTNESS_PROMPT,
    RAG_HELPFULNESS_PROMPT,
    RAG_GROUNDEDNESS_PROMPT,
    RAG_RETRIEVAL_RELEVANCE_PROMPT,
)
import re  # For regular expressions
import os  # For environment variables
from dotenv import load_dotenv
from typing import Optional, List, Any # Import Optional and List
load_dotenv("API.env")
from llm_provider import GeminiLLM


def parse_gemini_judgment(text: str) -> dict:
    """
    Parses the judgment text from Gemini to extract score and comment.

    This function assumes that Gemini will return a score (True/False)
    and a comment in its response.  The exact format might need to be
    adjusted based on how Gemini responds to the OpenEvals prompts.

    Example Gemini Output:
    "Score: False. Comment: The answer is not correct."
    "Score: True, Comment:  The output is grounded in the context"

    Returns:
        dict: A dictionary containing the 'score' (boolean) and 'comment' (string).
              Returns score as None and comment as empty if parsing fails.
    """
    score_pattern = r"Score:\s*(True|False)"
    comment_pattern = r"Comment:\s*(.*)"

    score_match = re.search(score_pattern, text, re.IGNORECASE)
    comment_match = re.search(comment_pattern, text, re.IGNORECASE)

    score = None
    comment = ""
    if score_match:
        score_text = score_match.group(1).lower()
        if score_text == "true":
            score = True
        elif score_text == "false":
            score = False

    if comment_match:
        comment = comment_match.group(1).strip()

    return {"score": score, "comment": comment}


def evaluate_rag_parameters(llm: LLM, inputs: dict, outputs: dict, context: Optional[dict] = None, reference_outputs: Optional[dict] = None) -> dict:
    """
    Evaluates RAG parameters (correctness, helpfulness, groundedness, retrieval relevance)
    using the given LLM and OpenEvals prompts.

    Args:
        llm (LLM): The Langchain LLM to use for evaluation (e.g., GeminiLLM).
        inputs (dict): The input dictionary containing the query.  Must have "question" key for helpfulness and retrieval.
        outputs (dict): The output dictionary containing the answer. Must have "answer" key for all evals.
        context (dict, optional): The context dictionary containing the retrieved documents.
            Must have "documents" key, which is a list of strings. Required for groundedness and retrieval relevance.
        reference_outputs (dict, optional): The reference output dictionary containing the ground truth answer.
            Must have "answer" key. Required for correctness.

    Returns:
        dict: A dictionary containing the evaluation results for each parameter.
            The keys are "correctness", "helpfulness", "groundedness", and "retrieval_relevance".
            Each value is a dictionary with "score" (boolean), "comment" (string), and "raw_judgment" (string).
            If an evaluation cannot be performed (e.g., missing required arguments), the score will be None
            and the comment will indicate the reason.
    """
    results = {}

    # 1. Correctness
    if reference_outputs and "answer" in reference_outputs and "answer" in outputs and "question" in inputs:
        prompt = CORRECTNESS_PROMPT.format(
            inputs=inputs["question"], outputs=outputs["answer"], reference_outputs=reference_outputs["answer"]
        )
        raw_judgment = llm.predict(prompt)
        parsed_judgment = parse_gemini_judgment(raw_judgment)
        results["correctness"] = {
            "score": parsed_judgment["score"],
            "comment": parsed_judgment["comment"],
            "raw_judgment": raw_judgment,
        }
    else:
        results["correctness"] = {
            "score": None,
            "comment": "Missing required arguments: reference_outputs, outputs, or inputs",
            "raw_judgment": None,
        }

    # 2. Helpfulness
    if "question" in inputs and "answer" in outputs:
        prompt = RAG_HELPFULNESS_PROMPT.format(inputs=inputs["question"], outputs=outputs["answer"])
        raw_judgment = llm.predict(prompt)
        parsed_judgment = parse_gemini_judgment(raw_judgment)

        results["helpfulness"] = {
            "score": parsed_judgment["score"],
            "comment": parsed_judgment["comment"],
            "raw_judgment": raw_judgment,
        }
    else:
        results["helpfulness"] = {
            "score": None,
            "comment": "Missing required arguments: inputs or outputs",
            "raw_judgment": None,
        }

    # 3. Groundedness
    if context and "documents" in context and "answer" in outputs:
        prompt = RAG_GROUNDEDNESS_PROMPT.format(context=context["documents"], outputs=outputs["answer"])
        raw_judgment = llm.predict(prompt)
        parsed_judgment = parse_gemini_judgment(raw_judgment)
        results["groundedness"] = {
            "score": parsed_judgment["score"],
            "comment": parsed_judgment["comment"],
            "raw_judgment": raw_judgment,
        }
    else:
        results["groundedness"] = {
            "score": None,
            "comment": "Missing required arguments: context or outputs",
            "raw_judgment": None,
        }

    # 4. Retrieval Relevance
    if context and "documents" in context and "question" in inputs:
        prompt = RAG_RETRIEVAL_RELEVANCE_PROMPT.format(inputs=inputs["question"], context=context["documents"])
        raw_judgment = llm.predict(prompt)
        parsed_judgment = parse_gemini_judgment(raw_judgment)
        results["retrieval_relevance"] = {
            "score": parsed_judgment["score"],
            "comment": parsed_judgment["comment"],
            "raw_judgment": raw_judgment,
        }
    else:
        results["retrieval_relevance"] = {
            "score": None,
            "comment": "Missing required arguments: context or inputs",
            "raw_judgment": None,
        }

    return results

def eval_reflection(results: dict):
    heal_flag=False
    healing_prompt="Following is the reflection of the above response.\n"
    for eval_para, eval_results in results.items():
        if eval_results['score']==False:
            heal_flag=True
            healing_prompt+=f"For parameter {eval_para.upper()} following is the evaluation result's final comment:\n{eval_results['comment']}\n"

    if not heal_flag:
        return {"Healing_required": False, "Healing_Prompt":""} # NO Healing Required
    return {"Healing_required": True, "Healing_Prompt":healing_prompt}
    

if __name__ == "__main__":
    # Replace with your actual Gemini API key
    gemini_llm = GeminiLLM(api_key=os.getenv('GENAI_API_KEY'))

    # Example data for evaluation
    inputs = {"question": "Where was the first president of FoobarLand born?"}
    outputs = {"answer": "The first president of FoobarLand was Bagatur Askaryan, who was born in the capital city."}
    reference_outputs = {"answer": "The first president of FoobarLand was born in the capital city of that country."}
    context = {
        "documents": [
            "FoobarLand is a new country located on the dark side of the moon.",
            "Space dolphins are native to FoobarLand.",
            "FoobarLand is a constitutional democracy whose first president was Bagatur Askaryan.",
            "The current weather in FoobarLand is 80 degrees and clear. The capital city is called 'First City'.",
        ],
    }

    # Perform evaluation
    evaluation_results = evaluate_rag_parameters(
        gemini_llm, inputs, outputs, context
    )
    print(evaluation_results)
    healing_promp = eval_reflection(evaluation_results)
    # Print the results
    print(healing_promp)
