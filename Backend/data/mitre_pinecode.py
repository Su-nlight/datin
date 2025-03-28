import json
import os
import uuid
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
load_dotenv()

class JSONVectorUploader:
    def __init__(self, pinecone_api_key, index_name, user_namespace="",
                 embedding_model=os.getenv('MODEL'), 
                 embedding_field=None):
        """
        Initialize the uploader with Pinecone and embedding configurations
        
        :param pinecone_api_key: Your Pinecone API key
        :param index_name: Name of the Pinecone index
        :param embedding_model: Sentence Transformer model for embeddings
        :param embedding_field: Specific field to use for creating embeddings (optional)
        """
        # Initialize Pinecone client
        self.pinecone = Pinecone(api_key=pinecone_api_key)
        self.user_namespace = user_namespace
        # Check if index exists, otherwise create it
        existing_indexes = self.pinecone.list_indexes().names()
        if index_name not in existing_indexes:
            self.pinecone.create_index(
                name = index_name,
                dimension = 1024,  # Adjust according to model's output
                metric = os.getenv('SIMILARITY'),
                spec = ServerlessSpec(
                    cloud = os.getenv('CLOUD'),
                    region = os.getenv('REGION')
                )
            )

        # Connect to the index
        self.index = self.pinecone.Index(index_name)
        
        # Initialize embedding model
        self.model = SentenceTransformer(embedding_model)
        self.embedding_field = embedding_field
    
    def create_embedding(self, item):
        """
        Create embedding for a JSON object
        
        :param item: JSON object to create embedding for
        :return: List of embedding values
        """
        if self.embedding_field and self.embedding_field in item:
            text_to_embed = str(item[self.embedding_field])
        else:
            try:
                text_to_embed = json.dumps(item, ensure_ascii=False)
            except Exception:
                text_to_embed = str(item)
        
        return self.model.encode(text_to_embed, normalize_embeddings=True).tolist()
    
    def upload_json_files(self, json_directory, batch_size=127):
        """
        Upload JSON files from a directory to Pinecone
        
        :param json_directory: Directory containing JSON files
        :param batch_size: Number of vectors to upsert in each batch
        """
        batch_vectors = []
        
        for filename in os.listdir(json_directory):
            if filename.endswith('.json'):
                file_path = os.path.join(json_directory, filename)
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    embedding = self.create_embedding(item)
                    vector_id = str(uuid.uuid4())
                    metadata = {k: v for k, v in item.items() if k != "external_references"}
                    metadata['_source_file'] = filename
                    
                    batch_vectors.append((vector_id, embedding, metadata))
                    
                    if len(batch_vectors) >= batch_size:
                        self.index.upsert(vectors=batch_vectors, namespace=self.user_namespace)
                        batch_vectors = []
                
                print(f"Processed file: {filename}")
        
        if batch_vectors:
            self.index.upsert(vectors=batch_vectors, namespace=self.user_namespace)
    
    def query_vectors(self, query_text, top_k=5):
        """
        Query the vector database
        
        :param query_text: Text to query
        :param top_k: Number of top results to return
        :return: Query results
        """
        query_embedding = self.model.encode(
            query_text, 
            normalize_embeddings=True
        ).tolist()
        
        results = self.index.query(
            vector=query_embedding, 
            top_k=top_k, 
            include_metadata=True,
            namespace=self.user_namespace
        )
        
        return results

# Example usage
def main():
    # Replace with your actual Pinecone credentials
    PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
    INDEX_NAME = os.getenv('INDEX_NAME')
    NAMESPACE = os.getenv('NAMESPACE')
    EMBD_FIELD = os.getenv('EMBED_FIELD')
    
    # Initialize uploader
    # Optional: Specify a specific field for embedding if desired
    uploader = JSONVectorUploader(
        PINECONE_API_KEY, 
        INDEX_NAME,
        embedding_field=EMBD_FIELD,
        user_namespace=NAMESPACE  # Optional: specify a specific field
    )
    
    # Specify JSON directory
    json_directory = rf"{os.getenv('DATA_DIR')}"
    print(PINECONE_API_KEY, INDEX_NAME, NAMESPACE, EMBD_FIELD, json_directory)
    
    # Upload JSON files
    uploader.upload_json_files(json_directory)
    
    # Optional: Query example
    query_results = uploader.query_vectors("APT28 is a threat group that has been attributed to the Russian government.")
    print(query_results)

if __name__ == '__main__':
    main()