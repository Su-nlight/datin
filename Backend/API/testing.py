from pineconedb import PineconeDB
from ragroute import RagModel
from dotenv import load_dotenv
import os
import json
import requests

def detect_language_from_url(url):
    ext = os.path.splitext(url)[1].split('?')[0]  # remove query params
    return {
        '.py': 'python',
        '.js': 'javascript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.html': 'html',
        '.css': 'css',
        '.sh': 'bash',
        '.rb': 'ruby',
        '.go': 'go',
        '.rs': 'rust',
        '.php': 'php',
        '.ts': 'typescript',
        '.txt': ''
    }.get(ext, '')

def convert_gitlab_url_to_raw(url):
    """
    Converts a GitLab file URL to its raw format.
    Example:
    https://gitlab.com/username/repo/-/blob/main/file.py
    -> https://gitlab.com/username/repo/-/raw/main/file.py
    """
    if "/-/blob/" in url:
        return url.replace("/-/blob/", "/-/raw/")
    return url  # Already raw or invalid

def gitlab_file_to_markdown(url):
    raw_url = convert_gitlab_url_to_raw(url)
    language = detect_language_from_url(raw_url)

    response = requests.get(raw_url)
    if response.status_code != 200:
        return ""

    code = response.text
    markdown = f"```{language}\n{code}\n```"
    return markdown



load_dotenv("API.env")
INDEX_NAME = os.getenv("INDEX_NAME")
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
GENAI_API_KEY = os.getenv("GENAI_API_KEY")

namespaces = os.getenv("NAMESPACES","")
namespaces = [item.strip() for item in namespaces.split(',') if item]
Rag_Model = RagModel(PINECONE_API_KEY, GENAI_API_KEY, NameSpaces=namespaces, Index_Name=INDEX_NAME, min_score=0.75)

query = "Linux/x86 - execve(_/bin/sh__ _0__ _0_) With umask 16 (sys_umask(14)) Shellcode (45 bytes)"

def  _unpack_dict_list_ExploitDB(dict_list: list):
    output = []
    for item in dict_list:
        lines = []
        for key, value in item.items():
            # Convert non-string values to JSON-formatted string if needed
            if not isinstance(value, str):
                value = json.dumps(value, indent=2)
            lines.append(f"{key}: {value}")
            if key=="file":
                lines.append(gitlab_file_to_markdown(f"https://gitlab.com/exploit-database/exploitdb/-/raw/main/{value}"))
        output.append("\n".join(lines))
    return "\n\n---\n\n".join(output)

#Rag_Resp = Rag_Model.Rag_Generator_caller(user_query=query)
Pinecone_DB = PineconeDB(pinecone_api_key=PINECONE_API_KEY, index_name=INDEX_NAME) 
query_results = Pinecone_DB.query_vector_multiple(query_text=query, NameSpaces=namespaces, min_score=0.75)
full_context_data=""
for name in namespaces:
        cnxt = "\n"
        if name == "exploit_db":
            cnxt += new_unpack_dict_list(query_results.get(name))
        else: 
            cnxt += Rag_Model._unpack_dict_list(query_results.get(name))
        full_context_data += cnxt
                    
print(full_context_data)