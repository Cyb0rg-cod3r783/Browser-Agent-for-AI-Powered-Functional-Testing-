from sentence_transformers import SentenceTransformer

class EmbeddingService:
    def __init__(self, model_name='all-MiniLM-L6-v2'):
        """
        Initializes the EmbeddingService by loading a pre-trained
        sentence-transformer model.
        
        The 'all-MiniLM-L6-v2' model is a good starting point as it's
        lightweight and provides high-quality embeddings.
        """
        self.model = SentenceTransformer(model_name)

    def generate_embeddings(self, text_list: list[str]) -> list[list[float]]:
        """
        Generates vector embeddings for a list of text strings.
        
        Args:
            text_list: A list of strings to be embedded.
            
        Returns:
            A list of vector embeddings, where each embedding is a list of floats.
        """
        embeddings = self.model.encode(text_list, convert_to_tensor=False)
        return embeddings.tolist()

# Initialize a single instance of the EmbeddingService to be used across the application
embedding_service = EmbeddingService()