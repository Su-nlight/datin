import json
import csv
import os
import uuid
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

load_dotenv()

class PineconeDB:
    def __init__(self, pinecone_api_key, index_name, user_namespace="",
                 embedding_model=os.getenv('MODEL'), batch_size=127, 
                 embedding_fields=None):
        """
        Initialize the PineconeDB with Pinecone and embedding configurations
        
        Args:
            pinecone_api_key (str): Your Pinecone API key
            index_name (str): Name of the Pinecone index
            user_namespace (str, optional): Namespace to use in Pinecone
            embedding_model (str, optional): Sentence Transformer model for embeddings
            batch_size (int, optional): Size of batches for upsert operations
            embedding_fields (list, optional): Specific fields to use for creating embeddings
        """
        # Initialize Pinecone client
        self.pinecone = Pinecone(api_key=pinecone_api_key)
        self.user_namespace = user_namespace
        self.index = self._create_index(index_name)  # Connect to the index
        # Initialize embedding model
        self.model = SentenceTransformer(embedding_model, device='cuda')
        self.fields = embedding_fields
        self.batch_size = batch_size

    def _create_index(self, index_name):
        """
        Create a Pinecone index if it doesn't exist, or connect to it if it does
        
        Args:
            index_name (str): Name of the index to create or connect to
            
        Returns:
            pinecone.Index: Pinecone index object
        """
        existing_indexes = self.pinecone.list_indexes().names()
        if index_name not in existing_indexes:
            self.pinecone.create_index(
                name=index_name,
                dimension=1024,  # Adjust according to model's output
                metric=os.getenv('SIMILARITY', 'cosine'),
                spec=ServerlessSpec(
                    cloud=os.getenv('CLOUD', 'aws'),
                    region=os.getenv('REGION', 'us-west-2')
                )
            )
        return self.pinecone.Index(index_name)
    
    def create_embedding(self, item):
        """
        Create embedding for a JSON object
        
        Args:
            item (dict): JSON object to create embedding for
            
        Returns:
            list: List of embedding values
        """
        text_to_embed = ""
        if self.fields:
            text_to_embed = " ".join(str(item.get(field, "")) for field in self.fields).strip()
        if not text_to_embed:
            try:
                text_to_embed = json.dumps(item, ensure_ascii=False)
            except Exception as e:
                print(f"Error converting item to JSON: {e}")
                text_to_embed = str(item)
        return self.model.encode(text_to_embed, normalize_embeddings=True).tolist()

    def upsert_index(self, batch_vectors):
        """
        Upsert a batch of vectors to the Pinecone index
        
        Args:
            batch_vectors (list): List of tuples (id, vector, metadata)
        """
        self.index.upsert(vectors=batch_vectors, namespace=self.user_namespace)

    def query_vectors(self, query_text, top_k=5):
        """
        Query the vector database
        
        Args:
            query_text (str): Text to query
            top_k (int, optional): Number of top results to return
            
        Returns:
            dict: Query results
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

    def upload_json_files(self, json_directory):
        """
        Upload JSON files from a directory to Pinecone
        
        Args:
            json_directory (str): Directory containing JSON files
        """
        batch_vectors = []
        file_count = 0
        item_count = 0
        batch_no = 1
        
        for filename in os.listdir(json_directory):
            if filename.endswith('.json'):
                file_path = os.path.join(json_directory, filename)
                
                with open(file_path, 'r', encoding='utf-8') as f:
                    try:
                        data = json.load(f)
                    except json.JSONDecodeError as e:
                        print(f"Error decoding JSON in {filename}: {e}")
                        continue
                
                if not isinstance(data, list):
                    data = [data]
                
                for item in data:
                    embedding = self.create_embedding(item)
                    vector_id = str(uuid.uuid4())
                    # Create metadata based on item content
                    metadata = {k: v for k, v in item.items() if k != "external_references"} 
                    metadata['_source_file'] = filename
                    
                    batch_vectors.append((vector_id, embedding, metadata))
                    item_count += 1
                    
                    if len(batch_vectors) >= self.batch_size:
                        self.upsert_index(batch_vectors)
                        print(f"Uploaded Batch Number : {batch_no}")
                        batch_no += 1
                        batch_vectors = []
                
                file_count += 1
                print(f"Processed file: {filename}")
        
        if batch_vectors:
            self.upsert_index(batch_vectors)
        
        print(f"Upload completed: {file_count} files and {item_count} items processed.")


class MitreVectorUploader:
    def __init__(self, json_directory=os.getenv('DATA_DIR_MITRE')):
        """
        Initialize the MITRE ATT&CK uploader with Pinecone configuration
        
        Args:
            json_directory (str): Directory containing MITRE JSON files
        """
        if not json_directory:
            raise ValueError("DATA_DIR_MITRE environment variable is not set")
            
        self.json_directory = json_directory
        # Get settings from environment variables
        PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
        if not PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY environment variable is not set")
            
        INDEX_NAME = os.getenv('INDEX_NAME')
        NAMESPACE = os.getenv('NAMESPACE_MITRE')
        EMBD_FIELD = os.getenv('EMBED_FIELD')
        
        # Convert embed field to list if it's a string
        embedding_fields = [EMBD_FIELD] if EMBD_FIELD else None
    
        # Initialize uploader
        self.uploader = PineconeDB(
            PINECONE_API_KEY, 
            INDEX_NAME,
            embedding_fields=embedding_fields,
            user_namespace=NAMESPACE
        )
       
    def upload_files(self):
        """
        Upload MITRE JSON files to Pinecone
        """
        self.uploader.upload_json_files(self.json_directory)
    

class CsvVectorUploader:
    def __init__(self, directory=os.getenv('DATA_DIR_EXDB')):
        """
        Initialize the CSV to vector uploader
        
        Args:
            directory (str): Directory containing CSV files
        """
        if not directory:
            raise ValueError("DATA_DIR_EXDB environment variable is not set")
            
        self.directory = directory
        # Replace with your actual Pinecone credentials
        PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
        if not PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY environment variable is not set")
            
        INDEX_NAME = os.getenv('INDEX_NAME')
        NAMESPACE = os.getenv('NAMESPACE_EXDB')
        EMBD_FIELD = os.getenv('EMBED_FIELDS_EXDB')
        
        # Convert embed field to list if it's a string
        embedding_fields = EMBD_FIELD.split(',') if EMBD_FIELD else None
    
        # Initialize uploader
        self.uploader = PineconeDB(
            PINECONE_API_KEY, 
            INDEX_NAME,
            embedding_fields=embedding_fields,
            user_namespace=NAMESPACE
        )
        
        # Convert CSV to JSON
        self._convert_csv_to_json()
    
    def _convert_csv_to_json(self):
        """
        Converts all CSV files in the directory to JSON files.
        Each JSON file will have the same name as the CSV file but with a .json extension.
        """
        if not os.path.exists(self.directory):
            print(f"Error: Directory '{self.directory}' does not exist.")
            return

        for filename in os.listdir(self.directory):
            if filename.endswith(".csv"):
                csv_path = os.path.join(self.directory, filename)
                json_path = os.path.join(self.directory, filename.replace(".csv", ".json"))
            
                try:
                    with open(csv_path, mode='r', encoding='utf-8') as csv_file:
                        reader = csv.DictReader(csv_file)
                        data = list(reader)
                    
                    with open(json_path, mode='w', encoding='utf-8') as json_file:
                        json.dump(data, json_file, indent=4)
                
                    print(f"Converted '{filename}' to '{os.path.basename(json_path)}'")
                except Exception as e:
                    print(f"Error converting '{filename}': {e}")

    def upload_files(self):
        """
        Upload the converted JSON files to Pinecone
        """
        self.uploader.upload_json_files(self.directory)


def main():
    """
    Main function to run the uploaders
    """
    try:
        # Check for required environment variables
        PINECONE_API_KEY = os.getenv('PINECONE_API_KEY')
        if not PINECONE_API_KEY:
            raise ValueError("PINECONE_API_KEY environment variable is not set")
            
        INDEX_NAME = os.getenv('INDEX_NAME')
        if not INDEX_NAME:
            raise ValueError("INDEX_NAME environment variable is not set")
            
        # Process operation mode
        operation = os.getenv('OPERATION', 'query').lower()
        
        if operation == 'mitre':
            # Upload MITRE ATT&CK data
            uploader = MitreVectorUploader()
            uploader.upload_files()
            
        elif operation == 'exploitdb':
            # Upload ExploitDB data
            uploader = CsvVectorUploader()
            uploader.upload_files()
            
        elif operation == 'query':
            # Perform a query operation
            NAMESPACE = os.getenv('NAMESPACE', '')
            EMBD_FIELD = os.getenv('EMBED_FIELD')
            embedding_fields = [EMBD_FIELD] if EMBD_FIELD else None
            
            # Initialize with query configuration
            pinecone_db = PineconeDB(
                PINECONE_API_KEY, 
                INDEX_NAME,
                embedding_fields=embedding_fields,
                user_namespace=NAMESPACE
            )
            
            # Get query from environment or use default
            query_text = os.getenv('QUERY_TEXT', "APT28 is a threat group that has been attributed to the Russian government.")
            top_k = int(os.getenv('TOP_K', 5))
            
            # Execute query
            query_results = pinecone_db.query_vectors(query_text, top_k=top_k)
            print(f"Query: '{query_text}'")
            print(f"Results: {json.dumps(query_results, indent=2)}")
            
        else:
            print(f"Unknown operation: {operation}. Valid options are: mitre, exploitdb, query")
            
    except Exception as e:
        print(f"Error in main execution: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()