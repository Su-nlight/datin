import json
import requests
import os
from google import genai
from google.genai import types
from pineconedb import PineconeDB

class RagModel:
    def __init__(self, PineconeAPIKey, GenAIKey, NameSpaces: list, Index_Name, min_score):
        self.GenAI_Client = genai.Client(api_key = GenAIKey)
        self.Name_Spaces = NameSpaces
        self.Pinecone_DB = PineconeDB(pinecone_api_key=PineconeAPIKey, index_name=Index_Name) 
        # can add more fields for more robust framework
        self.Min_Score = min_score
    
    @staticmethod
    def _detect_language_from_url(url):
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

    @staticmethod
    def _convert_gitlab_url_to_raw(url):
        """
        Converts a GitLab file URL to its raw format.
        Example:
        https://gitlab.com/username/repo/-/blob/main/file.py
        -> https://gitlab.com/username/repo/-/raw/main/file.py
        """
        if "/-/blob/" in url:
            return url.replace("/-/blob/", "/-/raw/")
        return url  # Already raw or invalid

    @staticmethod
    def  _unpack_dict_list_default(dict_list: list):
        output = []
        for item in dict_list:
            lines = []
            for key, value in item.items():
                # Convert non-string values to JSON-formatted string if needed
                if not isinstance(value, str):
                    value = json.dumps(value, indent=2)
                lines.append(f"{key}: {value}")
            output.append("\n".join(lines))
        return "\n\n---\n\n".join(output)
    
    def  _unpack_dict_list_ExploitDB(self, dict_list: list):
        output = []
        for item in dict_list:
            lines = []
            for key, value in item.items():
                # Convert non-string values to JSON-formatted string if needed
                if not isinstance(value, str):
                    value = json.dumps(value, indent=2)
                lines.append(f"{key}: {value}")
                if key=="file":
                    lines.append(self.gitlab_file_to_markdown(f"https://gitlab.com/exploit-database/exploitdb/-/raw/main/{value}"))
            output.append("\n".join(lines))
        return "\n\n---\n\n".join(output)
    
    def gitlab_file_to_markdown(self, url):
        raw_url = self._convert_gitlab_url_to_raw(url)
        language = self._detect_language_from_url(raw_url)

        response = requests.get(raw_url)
        if response.status_code != 200:
            return ""

        code = response.text
        markdown = f"```{language}\n{code}\n```"
        return markdown
    
    def _vector_query_generator(self, raw_query):
        new_query = self.GenAI_Client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"""Convert the following question to a text query for vector searcher & keep only its keywords and avoid unnecessary words:
        '{raw_query}'.\nRephrase whole to a very refined query avoid writing that we need info """).text
        return new_query

    def _vector_data_retriever(self, query):
        # send query to ai model to refine it for vector search then query -> new query
        query = self._vector_query_generator(query)
        # Execute query
        query_results = self.Pinecone_DB.query_vector_multiple(query_text=query, NameSpaces=self.Name_Spaces, min_score=self.Min_Score)
        # unpack results to text
        full_context_data=""
        for name in self.Name_Spaces:
            cnxt = "\n"
            if name == "exploit_db":
                cnxt += self._unpack_dict_list_ExploitDB(query_results.get(name))
            else:
                cnxt += self._unpack_dict_list_default(query_results.get(name))
            full_context_data += cnxt
        #with open('query1.txt', 'w') as f1:
            #f1.write(full_context_data) # debug2
        return full_context_data
    
    
    def Rag_Generator_caller(self, user_query):
        full_context = self._vector_data_retriever(query=user_query)
        template = f"""\n
        following is the context:\n
        ---\n{full_context}\n
        Now answer the following user query by giving a DETAILED DESCRIPTION : \n "{user_query}".
        """
        rag_response = self.GenAI_Client.models.generate_content(
            model = "gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction="Your name is Neko Chan. You are A CYBERSECURITY EXPERT AI ASSISTANT.Directly ANSWER THE QUERY WITHOUT MENTIONING ANYTHING ABOUT YOURSELF. Do not answer any question which is not your DOMAIN.",
                temperature=0.8
            ),
            contents = template
        ).text
        return rag_response
    
    def  Rag_Generator_stream_caller(self, user_query):
        full_context = self._vector_data_retriever(query=user_query)
        template = f"""\n
        following is the context:\n
        ---\n{full_context}\n
        Now answer the following user query by giving a DETAILED DESCRIPTION : \n "{user_query}".
        """
        response = self.GenAI_Client.models.generate_content_stream(
            model = "gemini-2.0-flash",
            config=types.GenerateContentConfig(
                system_instruction="Your name is Neko Chan. You are A CYBERSECURITY EXPERT AI ASSISTANT.Directly ANSWER THE QUERY WITHOUT MENTIONING ANYTHING ABOUT YOURSELF. Do not answer any question which is not your DOMAIN.",
                temperature=0.8
            ),
            contents = template
        )
        for chunk in response : 
            yield chunk.text