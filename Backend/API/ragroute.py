import json
from google import genai
from pineconedb import PineconeDB

class RagModel:
    def __init__(self, PineconeAPIKey, GenAIKey, NameSpaces: list, Index_Name, min_score):
        self.GenAI_Client = genai.Client(api_key = GenAIKey)
        self.Name_Spaces = NameSpaces
        self.Pinecone_DB = PineconeDB(pinecone_api_key=PineconeAPIKey, index_name=Index_Name) 
        # can add more fields for more robust framework
        self.Min_Score = min_score
        

    @staticmethod
    def  _unpack_dict_list(dict_list: list):
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
    
    def _vector_query_generator(self, raw_query):
        new_query = self.GenAI_Client.models.generate_content(
        model="gemini-2.0-flash",
        contents=f"""
        Convert the following question to a text query for vector searcher & keep only its keywords and avoid unnecessary words:
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
            cnxt += self._unpack_dict_list(query_results.get(name))
            full_context_data += cnxt
        return full_context_data
    
    def Rag_Generator_caller(self, user_query):
        full_context = self._vector_query_generator(raw_query=user_query)
        template = f"""
        You are A CYBERSECURITY EXPERT AI ASSISTANT. Directly ANSWER THE QUERY WITHOUT MENTIONING ANYTHING ABOUT YOURSELF. 
        Do not answer any question which is not your DOMAIN.\n
        following is the context:\n
        ---\n{full_context}\n
        Now answer the following user query by giving a DETAILED DESCRIPTION : \n "{user_query}".
        """
        rag_response = self.GenAI_Client.models.generate_content(
            model = "gemini-2.0-flash",
            contents = template
        ).text
        return rag_response
        



